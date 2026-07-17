"""
fifo_tap.py  —  star-sim GUI -> starsim-centroid-tracker koprusu (FIFO musluk).

GUI'nin real-time modda EKRANA bastigi karelerin AYNISINI bir named pipe'a
(FIFO) float32 ham, header'siz, row-major olarak yazar. starsim-centroid-tracker 'tracker'
bu pipe'i siradan bir .bin girdisi gibi okur -> starsim-centroid-tracker'de kod degisikligi YOK.

Tasarim (neden GUI donmaz):
  * Yazma islemi AYRI bir thread'de yapilir. FIFO bloklarsa (tracker yavas)
    sadece bu thread bekler; GUI thread'i hic etkilenmez.
  * "Sadece en son kare" mantigi: GUI her karede submit() ile slot'u uzerine
    yazar. Yazici thread yetisemezse eski kareler dusurulur (star-sim'in kendi
    'queue full -> drop' felsefesinin aynisi). Boylece GUI akici kalir.
  * Tam-kare atomik yazma: her kare TEK write ile gider; yarim kare yazilmaz,
    akis hizasi korunur.

Boyut guvenligi:
  * Ilk yazilan (W,H) "kilit boyut" olur. GUI'de cozunurluk (width/height)
    degistirilirse kare boyutu degisir; bu durum algilanir, BUYUK bir uyari
    basilir ("starsim-centroid-tracker'yi yeni W H ile yeniden baslat") ve yeni boyuta re-lock
    edilerek devam edilir. FOV/FWHM/mag_limit gibi degisimler boyutu
    degistirmedigi icin starsim-centroid-tracker hic kesintiye ugramaz.
"""

import os
import re
import struct
import sys
import threading

import numpy as np


class FifoFrameWriter:
    """GUI karelerini ayri bir thread'de FIFO'ya yazan musluk."""

    def __init__(self, path: str, gt_path: str | None = None):
        self._path = path
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        # ATOMIK slot: (buf, dims, truth, frame_id) tek demet olarak tasinir.
        # Ayri alanlar olsaydi writer bir karenin goruntusunu alirken GUI truth/id'yi
        # bir sonraki kareninkiyle degistirebilir -> goruntu ile damga kayar (senkron bug).
        self._latest = None                    # (buf, dims, truth, frame_id) | None
        self._stop = False
        self._fp = None
        self._gt_fp = None                     # ground_truth.csv dosyasi
        self._locked_dims: tuple[int, int] | None = None
        self._dropped = 0
        self._written = 0

        # FIFO'yu olustur (yoksa). Native FS sart (HGFS'de calismaz).
        if "/mnt/hgfs/" in path:
            raise ValueError("FIFO HGFS (Shared Folder) altinda olamaz; /tmp veya ev dizini kullan.")
        if not path.endswith(".bin"):
            raise ValueError("FIFO yolu .bin ile bitmeli ki tracker .bin modunu secsin.")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if not os.path.exists(path):
            os.mkfifo(path)
            self._created = True
        else:
            self._created = False

        # Ground truth CSV'yi ac (varsa). starsim-centroid-tracker'nin centroids.csv frame_id'si ile
        # ayni sayaci (FIFO'ya yazilan kare sirasi) kullanir -> kareler hizali.
        if gt_path:
            os.makedirs(os.path.dirname(os.path.abspath(gt_path)), exist_ok=True)
            self._gt_fp = open(gt_path, "w")
            self._gt_fp.write("frame_id,star_x,star_y,mag,star_id\n")
            self._gt_fp.flush()
            print(f"[fifo_tap] ground truth -> {gt_path}", file=sys.stderr)

        # Yazici thread'i baslat. open() okuyucu (tracker) baglanana kadar
        # bu thread'de BLOKE olur -> GUI etkilenmez.
        self._thread = threading.Thread(target=self._run, name="fifo-writer", daemon=True)
        self._thread.start()
        print(f"[fifo_tap] hazir: {path}", file=sys.stderr)
        print(f"[fifo_tap] tracker'i ayri terminalde baslat:", file=sys.stderr)
        print(f"           ./tracker {path} centroids.csv <W> <H>", file=sys.stderr)

    def submit(self, frame: np.ndarray, truth=None, frame_id: int = 0):
        """GUI thread'inden cagrilir. Kareyi ATOMIK demet olarak tutar (overwrite)."""
        if self._stop:
            return
        h, w = frame.shape[0], frame.shape[1]
        buf = np.ascontiguousarray(frame, dtype=np.float32).tobytes()
        with self._cond:
            if self._latest is not None:
                self._dropped += 1   # onceki demet yazilmadan ustune yazildi -> dustu
            # Goruntu + boyut + truth + id ASLA birbirinden ayrilmaz
            self._latest = (buf, (w, h), truth, int(frame_id))
            self._cond.notify()

    def _run(self):
        try:
            # Bloklayan acilis: tracker pipe'i acana kadar bekler.
            self._fp = open(self._path, "wb")
            print("[fifo_tap] tracker baglandi, kare akisi basladi.", file=sys.stderr)
        except Exception as e:
            print(f"[fifo_tap] FIFO acilamadi: {e}", file=sys.stderr)
            return

        while True:
            with self._cond:
                while self._latest is None and not self._stop:
                    self._cond.wait()
                if self._stop and self._latest is None:
                    break
                # Atomik demeti tek seferde al: goruntu-damga-truth asla ayrilmaz
                buf, dims, truth, frame_id = self._latest
                self._latest = None  # tuketildi

            # Boyut kilidi / degisim uyarisi
            if self._locked_dims is None:
                self._locked_dims = dims
                print(f"[fifo_tap] kare boyutu kilitlendi: {dims[0]}x{dims[1]} (float32)",
                      file=sys.stderr)
                print(f"[fifo_tap] >>> tracker'i su komutla baslat: "
                      f"./tracker {self._path} centroids.csv {dims[0]} {dims[1]}",
                      file=sys.stderr)
            elif dims != self._locked_dims:
                print("=" * 64, file=sys.stderr)
                print(f"[fifo_tap] DIKKAT: kare boyutu DEGISTI "
                      f"{self._locked_dims[0]}x{self._locked_dims[1]} -> {dims[0]}x{dims[1]}",
                      file=sys.stderr)
                print(f"[fifo_tap] starsim-centroid-tracker ESKI boyutla okudugu icin akis HIZASIZ olacak.",
                      file=sys.stderr)
                print(f"[fifo_tap] Cozum: tracker'i durdur ve sununla yeniden baslat:",
                      file=sys.stderr)
                print(f"[fifo_tap]   ./tracker {self._path} centroids.csv {dims[0]} {dims[1]}",
                      file=sys.stderr)
                print("=" * 64, file=sys.stderr)
                self._locked_dims = dims  # yeni boyuta re-lock, devam et

            try:
                # Her kareden ONCE 8 bayt GERCEK kare-id damgasi (little-endian uint64).
                # starsim-centroid-tracker bu id'yi --stamped modda okur; kare dusse bile ground
                # truth ile birebir eslesir (sayac kaymasi imkansiz).
                self._fp.write(struct.pack("<Q", frame_id & 0xFFFFFFFFFFFFFFFF))
                self._fp.write(buf)   # sonra tam kare
                self._fp.flush()
                # Ground truth'u AYNI gercek frame_id ile yaz
                if self._gt_fp is not None and truth:
                    for t in truth:
                        # renderer 4'lu (x,y,mag,star_id) uretir; eski 3'lu de kabul
                        x, y, mag = t[0], t[1], t[2]
                        sid = t[3] if len(t) > 3 else ""
                        # gen_ground_truth.py ile ayni format: "HIP30834" -> "30834"
                        sid = re.sub(r"^\D+", "", str(sid)) or sid
                        self._gt_fp.write(f"{frame_id},{x:.4f},{y:.4f},{mag:.3f},{sid}\n")
                    self._gt_fp.flush()
                self._written += 1
            except BrokenPipeError:
                print("[fifo_tap] tracker kapandi (broken pipe). Yazici durduruluyor.",
                      file=sys.stderr)
                break
            except Exception as e:
                print(f"[fifo_tap] yazma hatasi: {e}", file=sys.stderr)
                break

        self._cleanup()

    def _cleanup(self):
        try:
            if self._fp:
                self._fp.close()
        except Exception:
            pass
        self._fp = None
        try:
            if self._gt_fp:
                self._gt_fp.close()
        except Exception:
            pass
        self._gt_fp = None
        if self._created and os.path.exists(self._path):
            try:
                os.remove(self._path)
                print(f"[fifo_tap] FIFO silindi: {self._path}", file=sys.stderr)
            except Exception:
                pass
        print(f"[fifo_tap] kapandi. yazilan={self._written} dusurulen={self._dropped}",
              file=sys.stderr)

    def close(self):
        """GUI kapanirken veya real-time durunca cagrilir."""
        with self._cond:
            self._stop = True
            self._cond.notify()
        # Thread bir sonraki uyanista temizlenir. Kisa join denemesi:
        self._thread.join(timeout=2.0)
