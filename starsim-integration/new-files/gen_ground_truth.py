#!/usr/bin/env python3
"""
gen_ground_truth.py — Offline ground truth + kare uretici (Yol 3)

star-sim'in RealTimeRenderer'ini GUI/thread OLMADAN, deterministik bir dongude
calistirir. Real-time koprusuyle BIREBIR AYNI kod yolunu kullanir
(_render_frame_internal): ayni pointing (frame_counter/fps), ayni render, ayni
ground truth. Boylece uretilen .bin + ground_truth.csv, real-time'da uretilenle
bit-bit ayni olur (ayni parametreler + ayni seed sartiyla).

Uretir:
  <out>.bin           -> starsim-centroid-tracker'nin --stamped OLMADAN okuyacagi ham float32 kareler
  <out kok>_ground_truth.csv  -> compare.py icin (frame_id,star_x,star_y,mag,star_id)
  <out kok>_params.txt -> bu calistirmada kullanilan TUM parametreler (referans icin)
  --png verilirse      -> goruntulenebilir PNG (GUI ile ayni log-stretch varsayilani)

Tek kare + PNG ornegi:
  python3 gen_ground_truth.py --frames 1 --ra 120 --dec 10 --roll 0 \
      --ra-rate 1 --dec-rate 1 --roll-rate 2 --fov 10 --exposure 0.05 \
      --seed 42 --width 1024 --height 1024 --out /tmp/test.bin --png /tmp/test.png

Kullanim ornegi:
  python3 gen_ground_truth.py --frames 200 --ra-rate 1 --dec-rate 1 \
      --roll-rate 3 --exposure 0.05 --seed 42 --width 1024 --height 1024 \
      --out /tmp/test.bin

Sonra:
  ./tracker /tmp/test.bin /tmp/centroids.csv 1024 1024 --k 3 --min-flux 1500
  python3 compare.py /tmp/test_ground_truth.csv /tmp/centroids.csv --radius 1.0

NOT: Bu offline .bin DAMGASIZ'dir (id'ler 0'dan sirali). starsim-centroid-tracker'yi --stamped
     OLMADAN calistir. compare.py frame_id'leri sirali oldugu icin eslesir.
"""

import argparse
import datetime
import os
import re
import sys

import numpy as np


def save_png(frame, path, stretch="log"):
    """Ham float64 kareyi (0..65535 DN) goruntulenebilir 8-bit PNG'ye cevirir.

    Varsayilan 'log': star-sim GUI'sinin image_viewer varsayilaniyla BIREBIR ayni
    (log10 + auto min/max normalize). Boylece PNG, GUI'de gordugunle ayni gorunur.
    Alternatifler: 'linear', 'sqrt', 'asinh' (sonuk yildizlari daha da kaldirir).
    """
    a = np.asarray(frame, dtype=np.float64)

    if stretch == "log":
        # GUI ile ayni: log10(max(data,1)), sonra min-max -> 0..255
        d = np.log10(np.maximum(a, 1.0))
        dmin, dmax = d.min(), d.max()
        if dmax > dmin:
            img = np.clip((d - dmin) / (dmax - dmin) * 255.0, 0, 255)
        else:
            img = np.zeros_like(d)
    else:
        # Arka plani (median) sifira cek, max'a normalize et, sonra esnet
        b = a - np.percentile(a, 50.0)
        b[b < 0] = 0.0
        hi = b.max()
        if hi <= 0:
            img = np.zeros_like(b)
        else:
            x = b / hi
            if stretch == "linear":
                y = x
            elif stretch == "sqrt":
                y = np.sqrt(x)
            else:  # asinh
                k = 20.0
                y = np.arcsinh(k * x) / np.arcsinh(k)
            img = np.clip(y * 255.0, 0, 255)

    img = img.astype(np.uint8)
    try:
        from PIL import Image
        Image.fromarray(img, mode="L").save(path)
    except ImportError:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.imsave(path, img, cmap="gray", vmin=0, vmax=255)


def main():
    ap = argparse.ArgumentParser(
        description="star-sim offline ground truth + kare uretici (real-time ile birebir ayni)."
    )
    # Hareket (deg/s)
    ap.add_argument("--ra-rate", type=float, default=0.0, help="RA hizi (deg/s)")
    ap.add_argument("--dec-rate", type=float, default=0.0, help="Dec hizi (deg/s)")
    ap.add_argument("--roll-rate", type=float, default=0.0, help="Roll hizi (deg/s)")
    # Baslangic yonelimi (deg)
    ap.add_argument("--ra", type=float, default=85.0, help="Baslangic RA (deg)")
    ap.add_argument("--dec", type=float, default=0.0, help="Baslangic Dec (deg)")
    ap.add_argument("--roll", type=float, default=0.0, help="Baslangic Roll (deg)")
    # Poz / optik
    ap.add_argument("--exposure", type=float, default=0.1, help="Poz suresi (s)")
    ap.add_argument("--aperture", type=float, default=0.1, help="Aciklik (m)")
    ap.add_argument("--fwhm", type=float, default=2.0, help="PSF FWHM (px)")
    ap.add_argument("--background", type=float, default=100.0, help="Arka plan (DN)")
    # Goruntu
    ap.add_argument("--width", type=int, default=1024, help="Genislik (px)")
    ap.add_argument("--height", type=int, default=1024, help="Yukseklik (px)")
    ap.add_argument("--fov", type=float, default=10.0, help="Gorus alani (deg)")
    ap.add_argument("--mag-limit", type=float, default=6.5, help="Parlaklik limiti")
    ap.add_argument("--catalog", type=str, default="hipparcos", help="Katalog")
    # Uretim
    ap.add_argument("--frames", type=int, default=200, help="Uretilecek kare sayisi")
    ap.add_argument("--fps", type=int, default=60,
                    help="target_fps (pointing = frame/fps). Real-time ile AYNI olmali (60).")
    ap.add_argument("--seed", type=int, default=42,
                    help="Gurultu seed'i (ayni seed = ayni goruntu). Tekrarlanabilirlik icin sabit tut.")
    ap.add_argument("--no-noise", action="store_true", help="Gurultuyu kapat")
    # Cikti
    ap.add_argument("--out", type=str, default="/tmp/starsim_gt.bin",
                    help="Cikti .bin yolu (yaninda _ground_truth.csv yazilir)")
    ap.add_argument("--no-image", action="store_true",
                    help="Sadece ground_truth.csv yaz, .bin uretme (referans veri icin)")
    ap.add_argument("--png", type=str, default=None,
                    help="Kare(ler)i PNG olarak da yaz. 1'den fazla kare varsa ada _0000 eki gelir.")
    ap.add_argument("--stretch", choices=["log", "linear", "sqrt", "asinh"], default="log",
                    help="PNG parlaklik esnetmesi (varsayilan log: star-sim GUI ile ayni gorunum).")
    args = ap.parse_args()

    # star-sim modullerini import et (bu script starsim paketini bulabilmeli:
    # ya repo kokunden calistir, ya da venv aktif olsun)
    try:
        from starsim.render.realtime import RealTimeRenderer, RealTimeConfig
        from starsim.io.config import RenderScenarioConfig
    except ImportError as e:
        print(f"[HATA] star-sim import edilemedi: {e}", file=sys.stderr)
        print("       Bu script'i star-sim repo kokunden (venv aktifken) calistir.", file=sys.stderr)
        print("       Ornek: cd ~/projeler/star-sim-tu-main && source .venv/bin/activate", file=sys.stderr)
        sys.exit(1)

    # Cikti yollari
    out_bin = args.out
    # Cikti klasoru yoksa olustur (mkdir -p gereksizlesir); varsa dokunma.
    # Dosyalar zaten "w"/"wb" ile acildigi icin ustune yazma dogal davranistir.
    out_dir = os.path.dirname(os.path.abspath(out_bin))
    os.makedirs(out_dir, exist_ok=True)
    if args.png:
        os.makedirs(os.path.dirname(os.path.abspath(args.png)) or out_dir, exist_ok=True)
    root, _ = os.path.splitext(out_bin)
    out_csv = root + "_ground_truth.csv"
    out_txt = root + "_params.txt"

    # Kullanilan tum parametreleri txt olarak kaydet (referans icin)
    # Format: "RA=120.0, Dec=10.0, Roll=0.0, seed=42" stili, gruplu satirlar
    with open(out_txt, "w") as ftxt:
        ftxt.write(f"# gen_ground_truth.py calistirma kaydi\n")
        ftxt.write(f"# tarih: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
        ftxt.write(f"# komut: {' '.join(sys.argv)}\n\n")
        a = vars(args)
        ftxt.write(f"RA={a['ra']}, Dec={a['dec']}, Roll={a['roll']}, seed={a['seed']}\n")
        ftxt.write(f"RaRate={a['ra_rate']}, DecRate={a['dec_rate']}, RollRate={a['roll_rate']}\n")
        ftxt.write(f"FOV={a['fov']}, Exposure={a['exposure']}, Aperture={a['aperture']}\n")
        ftxt.write(f"Width={a['width']}, Height={a['height']}, Frames={a['frames']}\n")
        # Yukarida yazilmayan geri kalan parametreler (ayni virgullu formatta)
        yazilan = {"ra", "dec", "roll", "seed", "ra_rate", "dec_rate", "roll_rate",
                   "fov", "exposure", "aperture", "width", "height", "frames"}
        kalan = [f"{k}={v}" for k, v in sorted(a.items()) if k not in yazilan]
        if kalan:
            ftxt.write(", ".join(kalan) + "\n")

    # Senaryo config'i (real-time'in kullandigi ile ayni alanlar)
    scenario = RenderScenarioConfig(
        ra=args.ra, dec=args.dec, roll=args.roll,
        ra_rate=args.ra_rate, dec_rate=args.dec_rate, roll_rate=args.roll_rate,
        fov=args.fov, width=args.width, height=args.height,
        mag_limit=args.mag_limit, catalog=args.catalog,
        fwhm=args.fwhm, exposure=args.exposure, aperture=args.aperture,
        background=args.background, add_noise=(not args.no_noise), seed=args.seed,
    )
    rt_config = RealTimeConfig(target_fps=args.fps)

    print(f"[gen] renderer kuruluyor (katalog='{args.catalog}', {args.width}x{args.height}, fov={args.fov})...",
          file=sys.stderr)
    renderer = RealTimeRenderer(scenario_config=scenario, realtime_config=rt_config)

    # start_time'i real-time'daki gibi ayarla (pointing frame_counter'a bagli oldugu
    # icin start_time degeri sonucu ETKILEMEZ; yine de tutarlilik icin set ediyoruz).
    renderer._start_time = 0.0
    renderer._frame_counter = 0

    # Dosyalari ac
    fbin = None
    if not args.no_image:
        fbin = open(out_bin, "wb")
    fcsv = open(out_csv, "w")
    fcsv.write("frame_id,star_x,star_y,mag,star_id\n")

    print(f"[gen] {args.frames} kare uretiliyor "
          f"(ra_rate={args.ra_rate} dec_rate={args.dec_rate} roll_rate={args.roll_rate} "
          f"exp={args.exposure} seed={args.seed})...", file=sys.stderr)

    total_stars = 0
    for fid in range(args.frames):
        # frame_counter'i elle ayarla -> _render_frame_internal ayni frame_id icin
        # ayni pointing/goruntu/truth uretir (real-time ile BIREBIR ayni kod yolu).
        renderer._frame_counter = fid
        frame, ra, dec, roll, truth = renderer._render_frame_internal()

        # Goruntuyu ham float32 olarak yaz (starsim-centroid-tracker .bin modu bunu bekler)
        if fbin is not None:
            np.ascontiguousarray(frame, dtype=np.float32).tofile(fbin)

        # PNG cikti (istege bagli) - starsim-centroid-tracker'ye gitmez, sadece gozle bakmak icin
        if args.png:
            if args.frames == 1:
                png_path = args.png
            else:
                pbase, pext = os.path.splitext(args.png)
                png_path = f"{pbase}_{fid:04d}{pext or '.png'}"
            save_png(frame, png_path, args.stretch)

        # Ground truth: goruntu-ici valid yildizlar [(x,y,mag,star_id),...]
        if truth:
            for (x, y, mag, sid) in truth:
                # "HIP30834" -> "30834" (rakam olmayan onek atilir; hic rakam yoksa oldugu gibi kalir)
                sid_num = re.sub(r"^\D+", "", str(sid)) or sid
                fcsv.write(f"{fid},{x:.4f},{y:.4f},{mag:.3f},{sid_num}\n")
                total_stars += 1

        if (fid + 1) % 50 == 0:
            print(f"  {fid+1}/{args.frames} kare...", file=sys.stderr)

    if fbin is not None:
        fbin.close()
    fcsv.close()

    print(f"\n[gen] BITTI.", file=sys.stderr)
    if fbin is not None:
        sz_mb = os.path.getsize(out_bin) / 1e6
        print(f"  goruntu : {out_bin}  ({sz_mb:.1f} MB, {args.frames} kare)", file=sys.stderr)
    print(f"  truth   : {out_csv}  ({total_stars} yildiz-satiri)", file=sys.stderr)
    print(f"  params  : {out_txt}", file=sys.stderr)
    if args.png:
        if args.frames == 1:
            print(f"  png     : {args.png}  (stretch={args.stretch})", file=sys.stderr)
        else:
            pbase, pext = os.path.splitext(args.png)
            print(f"  png     : {pbase}_0000{pext or '.png'} ... ({args.frames} adet, stretch={args.stretch})",
                  file=sys.stderr)
    print(f"\n  Sonra starsim-centroid-tracker (DAMGASIZ):", file=sys.stderr)
    if fbin is not None:
        print(f"    ./tracker {out_bin} /tmp/centroids.csv {args.width} {args.height} "
              f"--k 3 --min-flux 1500 --max-pix 20000", file=sys.stderr)
        print(f"    python3 compare.py {out_csv} /tmp/centroids.csv --radius 1.0", file=sys.stderr)


if __name__ == "__main__":
    main()
