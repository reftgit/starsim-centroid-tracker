#!/usr/bin/env python3
"""
mc_driver.py — starsim-centroid-tracker Monte Carlo dogrulama surucusu.

Bu depoya aittir (compare.py'nin yanina). star-sim, uzerinde deney yapilan bir
VERI KAYNAGI bagimliligidir; bu script onu disaridan surer, kendisi star-sim'in
icinde yasamaz.

    [star-sim (yamali)] --kareler--> [./tracker] --centroids.csv--> [compare]
             |                                                          ^
             +------------------ ground truth --------------------------+
                        (ayni surec icinde, N farkli gurultu seed'i ile)

NE OLCER
--------
Sabit bir senaryoda (orn. ra_rate=dec_rate=roll_rate=1 deg/s) SADECE sensor
gurultusunu rastgeleleyip tracker'in su metriklerinin hangi degerlere
yakinsadigini olcer:

  * recall / precision / F1        (run bazinda, %95 guven araligiyla)
  * P_det(mag)                     magnitude gore tespit olasiligi egrisi
  * limiting magnitude             P_det'in %50'yi kestigi nokta
  * centroid konum hatasi          RMS, magnitude binleri halinde

NEDEN GECERLI
-------------
star-sim'de geometri (pointing, yildiz konumlari, streak) frame_id'ye
DETERMINISTIK bagli -- starsim-changes.patch realtime.py'de pointing'i
time.time() yerine frame_counter/target_fps'e bagladi. Dolayisiyla tek
stokastik girdi sensor gurultusudur ve

    recall(seed), precision(seed), rms(seed)

birer rastgele degiskendir; ortalamalari buyuk sayilar yasasiyla beklenen
degere yakinsar, standart hata sigma/sqrt(N) ile duser.

UC KRITIK NOKTA (koda gomuldu, degistirme)
------------------------------------------
1) fast_sensor_mode=True iken SensorModel.simulate_fast() seed'i TAMAMEN yok
   sayar (imzasinda seed yok; NoiseLUT seed=None ile kurulmus). O yuzden
   burada fast_sensor_mode=False kullaniyoruz -> simulate(..., seed=seed)
   yolu devreye girer, seed gercekten etkili olur ve PRNU/DSNU/dark current
   de dahil olur ("gercege en yakin" hedefine uygun).

2) Kare basina AYRI seed turetiyoruz (seed*P + frame_id). Tek bir seed tum
   karelerde ayni gurultu desenini uretirdi -> kareler bagimsiz olmazdi.

3) Ornekleme birimi = 1 RUN (1 seed). Bir run'in tum karelerinin toplami o
   run'in TEK istatistigidir. "100 kare = 100 ornek" YANLIS olur: kareler ayni
   yorunge uzerinde ayni yildizlari tekrar gorur, bagimsiz degildirler.

DIZINLER (bu makinede)
----------------------
    star-sim : /home/tubref/projeler/star-sim-tu-main
    tracker  : /home/tubref/projeler/starsim-centroid-tracker        <-- bu dosya burada durur

Ikisi de varsayilan olarak gomulu; --starsim-root / --tracker ile ezilebilir.

ON KOSUL
--------
star-sim'e bu deponun yamasi kurulmus olmali:

    cd /home/tubref/projeler/starsim-centroid-tracker/starsim-integration
    ./apply.sh /home/tubref/projeler/star-sim-tu-main

Script yamayi otomatik denetler ve eksikse ne yapman gerektigini soyler.

KULLANIM
--------
    source /home/tubref/projeler/star-sim-tu-main/.venv/bin/activate
    cd /home/tubref/projeler/starsim-centroid-tracker

    # 1) Gurultusuz ust sinir (referans nokta; MC ortalamasi bunun ALTINDA kalmali)
    python3 mc_driver.py --no-noise --runs 1 --frames 20

    # 2) Pilot: sigma'yi olc, gereken run sayisini ogren
    python3 mc_driver.py --runs 10 --frames 60

    # 3) Tam kosu (pilotun sana soyledigi N ile)
    python3 mc_driver.py --runs 62 --frames 60

    # 4) k taramasi, AYNI seed'lerle (Common Random Numbers -> eslestirilmis fark)
    python3 mc_driver.py --runs 40 --frames 60 --sweep-k 2,3,4,5,6
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # compare.py'yi yanindan import edebilmek icin

from compare import match_indices       # noqa: E402  -- eslestirmenin TEK kaynagi

# --- Bu makinedeki dizinler (varsayilanlar; CLI ile ezilebilir) ---------------
# tracker deposu  : /home/tubref/projeler/starsim-centroid-tracker   <- bu dosyanin bulundugu yer
# star-sim deposu : /home/tubref/projeler/star-sim-tu-main
#
# TRACKER_BIN'i mutlak yol yerine HERE uzerinden turetiyoruz: klasoru tasisan
# ya da yeniden adlandirsan bile calismaya devam eder.
DEFAULT_STARSIM = "/home/tubref/projeler/star-sim-tu-main"
DEFAULT_TRACKER = str(HERE / "tracker")

_SEED_PRIME = 1_000_003                 # kare-seed turetme (run'lar cakismasin)


# ---------------------------------------------------------------------------
# star-sim'i bul ve yamayi denetle
# ---------------------------------------------------------------------------

def load_starsim(starsim_root: str | None):
    """star-sim'i import eder. Once venv'e kurulu mu diye bakar, degilse
    --starsim-root/src yolunu sys.path'e ekler."""
    try:
        import starsim  # noqa: F401
    except ImportError:
        if not starsim_root:
            sys.exit(
                "[HATA] star-sim import edilemedi ve --starsim-root verilmedi.\n"
                f"  Beklenen: {DEFAULT_STARSIM}"
            )
        src = Path(starsim_root).expanduser().resolve() / "src"
        if not (src / "starsim").is_dir():
            sys.exit(
                f"[HATA] Burasi bir star-sim koku degil (src/starsim yok): {starsim_root}\n"
                f"  Beklenen: {DEFAULT_STARSIM}\n"
                "  venv aktif mi?  source "
                f"{DEFAULT_STARSIM}/.venv/bin/activate"
            )
        sys.path.insert(0, str(src))

    from starsim.render.realtime import RealTimeRenderer, RealTimeConfig
    from starsim.render.renderer import StarFieldRenderer
    from starsim.io.config import RenderScenarioConfig
    return RealTimeRenderer, RealTimeConfig, StarFieldRenderer, RenderScenarioConfig


def prepare_sensor(renderer, no_noise: bool):
    """SensorModel'i Monte Carlo icin dogru moda sokar. IKI KRITIK MUDAHALE:

    (1) NoiseLUT'u KAPAT.
        RealTimeRenderer sensoru SensorModel(..., use_noise_lut=True) ile kurar.
        Bu haldeyken simulate() -- fast_sensor_mode=False olsa bile --
        add_shot_noise / add_dark_current / add_read_noise fonksiyonlarinin
        HEPSI seed'den turetilen rng'yi YOK SAYIP onceden hesaplanmis LUT'tan
        okur. Yani seed hicbir gurultuyu etkilemez.

        Dahasi LUT indeksi kapanir: 1024^2 = 1.048M ornek/cagri, LUT 10M ->
        9 cagri sigar, 10.'da index 0'a doner. simulate() kare basina 3 cagri
        yapar (shot+dark+read) -> gurultu HER 3 KAREDE BIR tekrarlar. 60 karelik
        bir run = 180 cagri = tam 20 tur -> index yine 0'a doner -> BIR SONRAKI
        RUN BIT-BIT AYNI GORUNTUYLE baslar.

        Belirti: butun run'larda recall/precision/rms ayni, sigma = 0.00.
        Cozum: LUT'u kapat -> simulate() rng = default_rng(seed) kullanir,
        shot noise gercek Poisson, read noise gercek Gaussian olur.

    (2) Gurultusuz mod: sensoru ATLAMA, sadece gurultu terimlerini kapat.
        add_noise=False verilirse render() _apply_noise_pipeline'i HIC cagirmaz
        -> sensor devre disi kalir -> cikti ADU degil HAM FOTON (float64) olur.
        SmearedPSF fftconvolve kullandigi icin 49x49'luk damganin her pikselinde
        ~1e-11 mertebesinde pozitif FFT kuyrugu kalir. Arka plan 0 oldugundan
        median=MAD=0 -> tracker'in dejenere dali thr=0 verir -> maske TUM damgayi
        yutar -> blob npix ~2400 > max_pix -> HEPSI ELENIR -> %0 tespit.

        Cozum: add_noise'u ACIK birak (boylece foton -> ADU kuantizasyonu olsun,
        np.round FFT kuyruklarini sifira yuvarlasin) ama simulate()'in butun
        gurultu terimlerini kapat. Boylece "tavan" olcumu MC kosularilyla AYNI
        birimde (ADU) olur ve dogrudan kiyaslanabilir.
    """
    sensor = renderer._sensor

    # (1) LUT'u kapat -> seed gercekten etkili olsun
    sensor.use_noise_lut = False
    sensor._noise_lut = None

    if not no_noise:
        return

    # (2) Gurultusuz tavan: sensor calissin, gurultu terimleri kapali olsun
    _orig_simulate = sensor.simulate

    def _noiseless(photons, exposure_time, seed=None, **_kw):
        return _orig_simulate(
            photons, exposure_time, seed=seed,
            include_shot_noise=False, include_read_noise=False,
            include_dark_current=False, include_prnu=False, include_dsnu=False,
        )

    sensor.simulate = _noiseless


def check_patch(StarFieldRenderer):
    """starsim-changes.patch uygulanmis mi? Uygulanmamissa MC gecersizdir:
    ground truth donmez ve pointing duvar saatine bagli olur (deterministik degil)."""
    if "return_truth" not in inspect.signature(StarFieldRenderer.render).parameters:
        sys.exit(
            "[HATA] star-sim'e bu deponun yamasi UYGULANMAMIS.\n"
            "  renderer.render() 'return_truth' parametresini tanimiyor -> ground truth alinamaz.\n"
            "  Ayrica yamasiz realtime.py pointing'i time.time()'a baglar -> geometri\n"
            "  deterministik olmaz ve Monte Carlo varsayimi cokerdi.\n\n"
            "  Cozum:\n"
            f"    cd {HERE / 'starsim-integration'}\n"
            f"    ./apply.sh {DEFAULT_STARSIM}"
        )


# ---------------------------------------------------------------------------
# Senaryo sagligi: streak uzunlugu -> gereken com_half
# ---------------------------------------------------------------------------

def streak_px(a):
    """Poz suresince yildizin piksel duzleminde katettigi yol (oteleme, roll)."""
    plate_rad_px = math.tan(math.radians(a.fov / 2.0)) / (a.width / 2.0)
    plate_deg_px = math.degrees(plate_rad_px)
    sky_rate = math.hypot(a.ra_rate * math.cos(math.radians(a.dec)), a.dec_rate)
    trans = sky_rate * a.exposure / plate_deg_px
    r_corner = math.hypot(a.width, a.height) / 2.0
    roll = r_corner * math.radians(a.roll_rate) * a.exposure
    return trans, roll


def suggest_com_half(a):
    trans, roll = streak_px(a)
    return int(math.ceil((trans + roll) / 2.0 + 3.0 * (a.fwhm / 2.3548))) + 1


# ---------------------------------------------------------------------------
# Tek run: kareleri uret -> tracker'i kos -> degerlendir
# ---------------------------------------------------------------------------

def sample_pointing(seed):
    """Kure uzerinde DUZGUN dagilmis rastgele bir bakis yonu (seed'e bagli, tekrar uretilebilir).

    dec icin arcsin(U(-1,1)) kullaniyoruz; dogrudan U(-90,90) kutuplari asiri ornekler.
    """
    rng = np.random.default_rng(seed ^ 0xA5A5A5A5)
    ra = float(rng.uniform(0.0, 360.0))
    dec = float(np.degrees(np.arcsin(rng.uniform(-1.0, 1.0))))
    roll = float(rng.uniform(0.0, 360.0))
    # Kutuplara cok yakin bakis, catalog cache'inin RA-cos daralmasi yuzunden
    # her karede yeniden sorgu tetikler -> cok yavas. +-80'e kelepcele.
    dec = max(-80.0, min(80.0, dec))
    return ra, dec, roll


def render_run(renderer, seed, frames, bin_path):
    """Bir seed icin tum kareleri .bin'e yazar, ground truth'u dondurur.

    scenario_config.seed'i HER KARE icin yeniden set ediyoruz:
    _render_frame_internal onu okur -> renderer.render(seed=...) ->
    fast_sensor_mode=False oldugu icin sensor.simulate(..., seed=seed) calisir.
    """
    gt = defaultdict(list)
    fingerprint = None      # ilk karenin parmak izi -> gurultu seed'e cevap veriyor mu?
    with open(bin_path, "wb") as fb:
        for fid in range(frames):
            renderer._frame_counter = fid
            renderer.scenario_config.seed = (seed * _SEED_PRIME + fid) % (2 ** 31 - 1)
            frame, _ra, _dec, _roll, truth = renderer._render_frame_internal()
            arr = np.ascontiguousarray(frame, dtype=np.float32)
            arr.tofile(fb)
            if fid == 0:
                fingerprint = float(arr.astype(np.float64).sum())
            for t in (truth or []):
                # renderer 4'lu (x,y,mag,star_id) uretir; eski 3'lu de kabul
                x, y, mag = t[0], t[1], t[2]
                gt[fid].append((float(x), float(y), float(mag)))
    return gt, fingerprint


def run_tracker(a, bin_path, csv_path, k, com_half):
    """./tracker'i kosar, centroids.csv'yi {frame_id: [(cx,cy), ...]} olarak okur.

    DIKKAT (main.c): pozisyonel toplayici, '--' ile baslayan ve '--no-window'
    OLMAYAN her bayragin ARDINDAKI argumani atlar. '--stamped' degersiz bir
    bayrak oldugu halde bu istisnaya dahil degil. Bu yuzden bayraklar HER ZAMAN
    pozisyonellerden SONRA verilir.
    """
    cmd = [
        str(a.tracker), bin_path, csv_path, str(a.width), str(a.height),
        "--no-window",
        "--k", str(k),
        "--min-pix", str(a.min_pix),
        "--max-pix", str(a.max_pix),
        "--min-flux", str(a.min_flux),
        "--com-half", str(com_half),
        "--subsample", str(a.subsample),
        "--max-stars", str(a.max_stars),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"tracker basarisiz (rc={p.returncode}):\n{p.stderr[-2000:]}")

    det = defaultdict(list)
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            try:
                det[int(row["frame_id"])].append((float(row["cx"]), float(row["cy"])))
            except (KeyError, ValueError, TypeError):
                continue
    return det


def evaluate(gt_by_frame, det_by_frame, radius, mag_bins, dump=None, W=0, H=0, margin=0.0):
    """Bir run'in TUM karelerini tek bir metrik demetine indirger.
    Eslestirme compare.match_indices ile yapilir -> compare.py ile birebir ayni sayilar.

    dump: None degilse, eslesemeyen HER gercek yildiz icin bir teshis satiri eklenir:
        mag, x, y, kenara_uzaklik, en_yakin_komsu_yildiz, en_yakin_tespit
    Bu uc sayi basarisizligin sebebini AYIRT EDER:
        kenara_uzaklik kucuk   -> streak kadraj disina tasiyor, COM kayiyor
        komsu_uzaklik kucuk    -> yildizlar tek bloba birlesmis (blending)
        en_yakin_tespit buyuk  -> ortada hic tespit yok (gercek kacirma: aki/esik)
    """
    TP = FN = FP = 0
    dists = []
    # --- ISARETLI (bias) hata birikimi ---------------------------------------
    # rms ISARETSIZ mesafedir; sistematik kaymayi GOREMEZ. Ayni rms iki cok
    # farkli durumdan cikabilir:
    #   (a) saf sacilma  -> hatalar gercek konumun ETRAFINDA, ortalamasi 0
    #                       -> N yildiz uzerinden ortalama alinca 1/sqrt(N) ile kuculur
    #   (b) sistematik kayma -> hatalar hep AYNI yone
    #                       -> ortalama almak HICBIR SEYI duzeltmez, attitude'a
    #                          dogrudan sabit bir hata olarak biner
    # Star tracker icin bu ayrim hayati. Onun icin isaretli farklari da topluyoruz.
    sum_dx = sum_dy = sum_dr = 0.0
    n_bias = 0
    cx0, cy0 = (W - 1) / 2.0, (H - 1) / 2.0     # goruntu merkezi (radyal bilesen icin)
    nb = len(mag_bins) - 1
    mag_tp = np.zeros(nb, dtype=np.int64)
    mag_total = np.zeros(nb, dtype=np.int64)
    mag_sqerr = np.zeros(nb, dtype=np.float64)
    mag_n = np.zeros(nb, dtype=np.int64)

    for fid in sorted(set(gt_by_frame) | set(det_by_frame)):
        gt = gt_by_frame.get(fid, [])
        det = det_by_frame.get(fid, [])

        # KENAR MARJI: streak'i kadraj disina tasan yildizin merkezi ILKESEL olarak
        # kurtarilamaz -- COM gorunen isigi merkezler, yildizi degil. Gercek star
        # tracker'lar bu bolgeyi zaten reddeder. Hem GT'den hem tespitlerden atiyoruz
        # ki ne sahte FN ne sahte FP uretsin.
        if margin > 0.0:
            gt = [(x, y, m) for (x, y, m) in gt
                  if margin <= x <= (W - 1 - margin) and margin <= y <= (H - 1 - margin)]
            det = [(x, y) for (x, y) in det
                   if margin <= x <= (W - 1 - margin) and margin <= y <= (H - 1 - margin)]

        gt_xy = [(x, y) for (x, y, _m) in gt]
        matches = match_indices(gt_xy, det, radius)

        TP += len(matches)
        FN += len(gt) - len(matches)
        FP += len(det) - len(matches)

        for i, (x, y, mag) in enumerate(gt):
            b = int(np.digitize([mag], mag_bins)[0]) - 1
            if 0 <= b < nb:
                mag_total[b] += 1
            if i in matches:
                j, d = matches[i]
                dists.append(d)

                # Isaretli hata: olculen - gercek
                dx = det[j][0] - x
                dy = det[j][1] - y
                sum_dx += dx
                sum_dy += dy
                # Radyal bilesen: hata, goruntu merkezinden yildiza dogru olan
                # yonde mi? (+ disari, - iceri). Optik distorsiyon ve roll kaynakli
                # sistematikler bu bilesende gorunur.
                rx, ry = x - cx0, y - cy0
                r = math.hypot(rx, ry)
                if r > 1e-6:
                    sum_dr += (dx * rx + dy * ry) / r
                n_bias += 1

                if 0 <= b < nb:
                    mag_tp[b] += 1
                    mag_sqerr[b] += d * d
                    mag_n[b] += 1
            elif dump is not None:
                # Eslesemedi -> nedenini ayirt edecek olculeri yaz
                edge = min(x, y, (W - 1) - x, (H - 1) - y)
                nn = min((math.hypot(x - gx, y - gy)
                          for j, (gx, gy) in enumerate(gt_xy) if j != i), default=float("inf"))
                nd = min((math.hypot(x - dx, y - dy) for (dx, dy) in det), default=float("inf"))
                dump.append((fid, mag, x, y, edge, nn, nd))

    recall = TP / (TP + FN) if (TP + FN) else 0.0
    precision = TP / (TP + FP) if (TP + FP) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    d = np.array(dists) if dists else np.array([0.0])

    return {
        "TP": TP, "FN": FN, "FP": FP,
        "recall": recall, "precision": precision, "f1": f1,
        "mean_err": float(d.mean()), "rms_err": float(np.sqrt((d ** 2).mean())),
        # Isaretli ortalama hata (bias). 0'a yakinsa sacilma saf; degilse sistematik.
        "bias_x": (sum_dx / n_bias) if n_bias else 0.0,
        "bias_y": (sum_dy / n_bias) if n_bias else 0.0,
        "bias_r": (sum_dr / n_bias) if n_bias else 0.0,
        "mag_tp": mag_tp, "mag_total": mag_total,
        "mag_sqerr": mag_sqerr, "mag_n": mag_n,
    }


def report_failures(rows, out_csv, half_streak, sigma_psf):
    """Basarisiz eslesmeleri siniflandirip ozet basar + CSV yazar.

    ONEMLI: esikler SABIT DEGIL, senaryodan turetilir. Onceki surumde HALF=8.0
    sabit yaziliydi (0.1 s pozun yari-streak'i); poz degisince KENAR/BLEND
    esikleri yanlis oluyor ve sinif sayilari pozlar arasi kiyaslanamiyordu.

        half_streak : streak'in yarisi (px) -- yildizin merkezden ne kadar yayildigi
        sigma_psf   : PSF sigmasi (px)

    KENAR  : yildiz kenara half_streak+3sigma'dan yakin -> izinin bir kismi
             kadraj disinda; COM gorulen isigin merkezini verir, gercek merkezi
             DEGIL. Kurtarilamaz (tracker hatasi degil).
    BLEND  : en yakin komsu yildiz 2*(half_streak+3sigma) icinde -> izler ust
             uste biniyor, tek blob olusuyor.
    KACIRMA: ortada hic tespit yok -> gercek kacirma (aki esigi ya da SNR).
    DIGER  : tespit var ama radius'tan fazla kaymis.
    """
    if not rows:
        print("  [teshis] eslesemeyen yildiz yok.")
        return

    reach = half_streak + 3.0 * sigma_psf     # yildizin isiginin uzandigi yaricap

    arr = np.array([(m, e, nn, nd) for (_f, m, _x, _y, e, nn, nd) in rows], dtype=float)
    mag, edge, nn, nd = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]

    is_edge  = edge < reach                          # izi kadraj disina tasiyor
    is_blend = (~is_edge) & (nn < 2.0 * reach)       # komsu izle ust uste
    is_miss  = (~is_edge) & (~is_blend) & (nd > 5.0) # ortada hic tespit yok
    is_other = ~(is_edge | is_blend | is_miss)

    n = len(rows)
    print(f"\n  [teshis] eslesemeyen {n} yildiz siniflandirildi "
          f"(erisim yaricapi = {reach:.1f} px = yari-streak {half_streak:.1f} + 3σ_psf):")
    for name, m_ in (("KENAR   (streak kadraj disi)", is_edge),
                     ("BLEND   (komsu ile birlesmis)", is_blend),
                     ("KACIRMA (hic tespit yok)", is_miss),
                     ("DIGER   (tespit var, >radius kaymis)", is_other)):
        c = int(m_.sum())
        mm = f"  ort.mag={mag[m_].mean():.2f}" if c else ""
        print(f"    {name:36s} {c:7d}  ({100.0*c/n:5.1f} %){mm}")

    with open(out_csv, "w") as f:
        f.write("frame_id,mag,x,y,kenar_uzaklik,komsu_uzaklik,en_yakin_tespit,sinif\n")
        for i, (fid, m_, x, y, e, k, d) in enumerate(rows):
            cls = ("KENAR" if is_edge[i] else "BLEND" if is_blend[i]
                   else "KACIRMA" if is_miss[i] else "DIGER")
            f.write(f"{fid},{m_:.3f},{x:.3f},{y:.3f},{e:.2f},{k:.2f},{d:.2f},{cls}\n")
    print(f"  [teshis] ayrinti -> {out_csv}")


# ---------------------------------------------------------------------------
# Istatistik
# ---------------------------------------------------------------------------

def ci95(v):
    """Ortalama ve %95 guven araligi yari-genisligi."""
    a = np.asarray(v, dtype=float)
    if len(a) < 2:
        return (float(a.mean()) if len(a) else 0.0), float("nan")
    return float(a.mean()), 1.96 * float(a.std(ddof=1)) / math.sqrt(len(a))


def required_n(sigma, target):
    """Hedef CI yari-genisligine ulasmak icin gereken run sayisi."""
    return math.ceil((1.96 * sigma / target) ** 2) if target > 0 else float("inf")


def wilson(k, n, z=1.96):
    """Binom oran icin Wilson guven araligi (P_det egrisi icin -- normal
    yaklasim p=0 ve p=1 civarinda cokup anlamsiz aralik verir)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, c - h), min(1.0, c + h)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="starsim-centroid-tracker Monte Carlo dogrulama surucusu",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    g = ap.add_argument_group("star-sim baglantisi")
    g.add_argument("--starsim-root", type=str, default=DEFAULT_STARSIM,
                   help="star-sim deposunun koku")

    g = ap.add_argument_group("Senaryo (gen_ground_truth.py ile ayni isimler)")
    g.add_argument("--ra", type=float, default=120.0)
    g.add_argument("--dec", type=float, default=10.0)
    g.add_argument("--roll", type=float, default=0.0)
    g.add_argument("--ra-rate", type=float, default=1.0, help="deg/s")
    g.add_argument("--dec-rate", type=float, default=1.0, help="deg/s")
    g.add_argument("--roll-rate", type=float, default=1.0, help="deg/s")
    g.add_argument("--fov", type=float, default=10.0)
    g.add_argument("--width", type=int, default=1024)
    g.add_argument("--height", type=int, default=1024)
    g.add_argument("--fwhm", type=float, default=2.0)
    g.add_argument("--exposure", type=float, default=0.1)
    g.add_argument("--aperture", type=float, default=0.1)
    g.add_argument("--background", type=float, default=100.0)
    g.add_argument("--mag-limit", type=float, default=6.5)
    g.add_argument("--catalog", type=str, default="hipparcos")
    g.add_argument("--fps", type=int, default=60, help="target_fps (pointing = frame/fps)")
    g.add_argument("--no-noise", action="store_true",
                   help="gurultusuz UST SINIR olcumu (MC ortalamasi bunun altinda kalmali)")

    g = ap.add_argument_group("Monte Carlo")
    g.add_argument("--runs", type=int, default=40, help="MC ornek sayisi (= seed sayisi)")
    g.add_argument("--frames", type=int, default=60, help="run basina kare")
    g.add_argument("--seed0", type=int, default=1000)
    g.add_argument("--target-halfwidth", type=float, default=0.005,
                   help="recall/precision icin hedef %%95 CI yari-genisligi (oran)")

    g = ap.add_argument_group("Tracker")
    g.add_argument("--tracker", type=str, default=DEFAULT_TRACKER,
                   help="tracker ikilisinin yolu")
    g.add_argument("--k", type=float, default=3.0)
    g.add_argument("--sweep-k", type=str, default=None,
                   help="virgullu k listesi; AYNI seed'lerle taranir (CRN)")
    g.add_argument("--min-pix", type=int, default=3)
    g.add_argument("--max-pix", type=int, default=500)
    g.add_argument("--min-flux", type=float, default=1500.0)
    g.add_argument("--subsample", type=int, default=4)
    g.add_argument("--max-stars", type=int, default=1024)
    g.add_argument("--com-half", type=int, default=None,
                   help="verilmezse streak uzunlugundan otomatik hesaplanir")
    g.add_argument("--radius", type=float, default=1.0, help="eslestirme toleransi (px)")
    g.add_argument("--edge-margin", type=str, default="0",
                   help="kenar seridi (px): bu kadar kenara yakin yildizlar HEM GT'den HEM "
                        "tespitlerden dusulur. Streak'i kadraj disina tasan yildizin merkezi "
                        "ILKESEL olarak kurtarilamaz; metrige katmak tracker'i olmayan bir "
                        "sucla suclamaktir. 'auto' = yari-streak + 3*sigma_psf. '0' = kapali.")
    g.add_argument("--dump-failures", action="store_true",
                   help="eslesemeyen yildizlari siniflandir (KENAR/BLEND/KACIRMA/DIGER) ve CSV yaz")

    g = ap.add_argument_group("Gokyuzu ornekleme")
    g.add_argument("--random-pointing", action="store_true",
                   help="HER RUN farkli, rastgele bir gokyuzu bolgesine baksin. "
                        "60 kare @60fps = 1 saniye = 1 derece yol, FOV ise 10 derece -> "
                        "tek bir run BOYUNCA neredeyse AYNI yildizlar goruluyor (%%81 ortusme). "
                        "Bu bayrak olmadan magnitude binlerindeki 'n' sahtedir (ayni ~14 yildiz "
                        "60 kez sayilir) ve guven araliklari ASIRI DAR cikar.")

    g = ap.add_argument_group("Cikti")
    g.add_argument("--out-dir", type=str, default=str(HERE / "mc_sonuclari"))
    g.add_argument("--scratch", type=str, default=None,
                   help="gecici .bin dizini. YEREL FS olmali (HGFS/paylasilan klasor DEGIL).")
    a = ap.parse_args()

    if not os.access(a.tracker, os.X_OK):
        sys.exit(f"[HATA] tracker calistirilabilir degil: {a.tracker}\n  Once 'make' calistir.")

    RealTimeRenderer, RealTimeConfig, StarFieldRenderer, RenderScenarioConfig = \
        load_starsim(a.starsim_root)
    check_patch(StarFieldRenderer)

    if not os.path.exists(a.tracker):
        sys.exit(f"[HATA] tracker binary bulunamadi: {a.tracker}\n"
                 f"  Cozum: repo kokunde 'make' calistir veya --tracker ile yol ver.")
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(a.scratch) if a.scratch else Path(tempfile.gettempdir())
    # Gecici dosyalara PID ekle: ayni anda birden fazla mc_driver calistirilirsa
    # birbirlerinin karelerini/centroid'lerini EZERLER ve sessizce yanlis sonuc
    # uretirler (cokme yok, sadece anlamsiz sayilar). PID cakismayi engeller.
    pid = os.getpid()
    bin_path = str(scratch / f"mc_frames_{pid}.bin")
    csv_path = str(scratch / f"mc_centroids_{pid}.csv")

    # --- Senaryo saglik kontrolu: streak vs com_half ---
    trans, roll = streak_px(a)
    auto_ch = suggest_com_half(a)
    com_half = a.com_half if a.com_half is not None else auto_ch

    half_streak = (trans + roll) / 2.0
    sigma_psf = a.fwhm / 2.3548
    auto_margin = half_streak + 3.0 * sigma_psf     # yildizin isiginin uzandigi yaricap

    # --edge-margin: "auto" -> hesapla, sayi -> aynen kullan
    if str(a.edge_margin).strip().lower() == "auto":
        a.edge_margin = auto_margin
    else:
        a.edge_margin = float(a.edge_margin)

    print("=" * 74)
    print("  SENARYO SAGLIK KONTROLU")
    print("=" * 74)
    print(f"  Oteleme izi (poz basina)  : {trans:6.2f} px")
    print(f"  Roll'un kenar katkisi     : {roll:6.2f} px")
    print(f"  Toplam streak             : {trans + roll:6.2f} px")
    print(f"  Onerilen --com-half       : {auto_ch}   (kullanilan: {com_half})")
    if a.edge_margin > 0:
        print(f"  Kenar marji               : {a.edge_margin:6.2f} px  (onerilen: {auto_margin:.2f})")
        print(f"     -> kenardaki kurtarilamaz yildizlar metrikten DUSULUYOR")
    else:
        print(f"  Kenar marji               :  KAPALI  (--edge-margin auto -> {auto_margin:.2f} px)")
        print(f"     -> streak'i kadraj disina tasan yildizlar hala FN+FP sayiliyor")
    if com_half < auto_ch:
        print("  !! UYARI: com_half streak'i kapsamiyor. COM penceresi izi kirpar ->")
        print("     konum hatasi GURULTUDEN degil pencere boyundan gelir; MC anlamsizlasir.")
    print()

    # --- Renderer'i BIR KERE kur (katalog yuklemesi pahali) ---
    #     fast_sensor_mode=False -> simulate(..., seed=seed): seed GERCEKTEN etkili
    scenario = RenderScenarioConfig(
        ra=a.ra, dec=a.dec, roll=a.roll,
        ra_rate=a.ra_rate, dec_rate=a.dec_rate, roll_rate=a.roll_rate,
        fov=a.fov, width=a.width, height=a.height,
        mag_limit=a.mag_limit, catalog=a.catalog,
        fwhm=a.fwhm, exposure=a.exposure, aperture=a.aperture,
        # DIKKAT: add_noise HER ZAMAN True. --no-noise'da bile sensor pipeline'i
        # calismali ki foton -> ADU kuantizasyonu (np.round) yapilsin; aksi halde
        # cikti ham float foton olur, FFT kuyruklari sifirlanmaz ve tracker'in
        # esigi 0'a coker. Gurultusuzlugu prepare_sensor() sensor seviyesinde
        # (include_*_noise=False ile) saglar.
        background=a.background, add_noise=True, seed=a.seed0,
    )
    print(f"[mc] renderer kuruluyor (katalog={a.catalog}, {a.width}x{a.height}, fov={a.fov})...")
    renderer = RealTimeRenderer(
        scenario_config=scenario,
        realtime_config=RealTimeConfig(target_fps=a.fps, fast_sensor_mode=False),
    )
    renderer._start_time = 0.0

    # KRITIK: NoiseLUT'u kapat (seed'in gercekten etkili olmasi icin) ve
    # gurultusuz modda sensoru atlamak yerine gurultu terimlerini kapat.
    prepare_sensor(renderer, a.no_noise)
    print("[mc] NoiseLUT kapatildi -> shot noise=Poisson(rng), read noise=Gauss(rng), seed etkin"
          + ("  |  GURULTU TERIMLERI KAPALI (tavan olcumu, ADU domeninde)" if a.no_noise else ""))

    mag_bins = np.arange(0.0, a.mag_limit + 0.5, 0.5)
    nb = len(mag_bins) - 1

    k_list = [float(x) for x in a.sweep_k.split(",")] if a.sweep_k else [a.k]
    seeds = [a.seed0 + i for i in range(a.runs)]   # CRN: tum k'lar AYNI seed setini kullanir

    gt_ref = None
    results = {}

    for k in k_list:
        print("=" * 74)
        print(f"  MONTE CARLO  |  k={k}  |  {a.runs} run x {a.frames} kare"
              f"{'  |  GURULTUSUZ' if a.no_noise else ''}")
        print("=" * 74)

        per_run = []
        fail_rows = []
        noise_responds = None      # run 2'de olculur: goruntu seed'e cevap veriyor mu?
        A_tp = np.zeros(nb, dtype=np.int64); A_tot = np.zeros(nb, dtype=np.int64)
        A_sq = np.zeros(nb, dtype=np.float64); A_n = np.zeros(nb, dtype=np.int64)
        t0 = time.time()

        for i, seed in enumerate(seeds):
            if a.random_pointing:
                # Her run BASKA bir gokyuzu bolgesi -> yildizlar gercekten bagimsiz
                # ornekler olur ve P_det(mag) bir POPULASYON istatistigi haline gelir.
                ra_i, dec_i, roll_i = sample_pointing(seed)
                renderer.scenario_config.ra = ra_i
                renderer.scenario_config.dec = dec_i
                renderer.scenario_config.roll = roll_i

            gt, fp = render_run(renderer, seed, a.frames, bin_path)

            if gt_ref is None:
                gt_ref, fp_ref = gt, fp
            elif i == 1 and not a.random_pointing:
                # Test 1 (determinizm): GEOMETRI seed'den BAGIMSIZ olmali.
                # (--random-pointing modunda gokyuzu bilerek degistigi icin bu test atlanir.)
                ok_geo = (set(gt_ref) == set(gt)) and all(
                    np.allclose([p[:2] for p in gt_ref[f]], [p[:2] for p in gt[f]], atol=1e-9)
                    for f in gt_ref
                )
                print("  [ok] ground truth seed'den bagimsiz (determinizm dogrulandi)" if ok_geo else
                      "  !! UYARI: ground truth seed'e gore DEGISIYOR -> MC varsayimi bozuk!")

                # Test 2 (dejenerelik): GURULTU seed'e CEVAP VERMELI.
                # DIKKAT: burada goruntunun degisip degismedigine bakiyoruz.
                # Goruntu degisiyor ama metrikler sabit kaliyorsa bu bir HATA
                # DEGIL, gecerli bir bulgudur (metrik gurultuye duyarsiz).
                if not a.no_noise and fp is not None and fp_ref is not None:
                    if abs(fp - fp_ref) < 1e-6 * max(1.0, abs(fp_ref)):
                        noise_responds = False
                        print("  !! KRITIK: iki farkli seed AYNI goruntuyu uretti.")
                        print("     Gurultu seed'e cevap vermiyor -> Monte Carlo DEJENERE.")
                        print("     (NoiseLUT hala acik mi? prepare_sensor() calisti mi?)")
                    else:
                        noise_responds = True
                        print("  [ok] gurultu seed'e cevap veriyor (kareler farkli)")

            det = run_tracker(a, bin_path, csv_path, k, com_half)
            # Teshis dokumu SADECE ilk run'da toplanir (sistematik hatalar zaten
            # seed'den bagimsiz; N run boyunca toplamak sadece dosyayi sisirir).
            dump = fail_rows if (a.dump_failures and i == 0) else None
            r = evaluate(gt, det, a.radius, mag_bins, dump=dump,
                         W=a.width, H=a.height, margin=a.edge_margin)
            per_run.append(r)
            A_tp += r["mag_tp"]; A_tot += r["mag_total"]
            A_sq += r["mag_sqerr"]; A_n += r["mag_n"]

            rm, rh = ci95([x["recall"] for x in per_run])
            pm, ph = ci95([x["precision"] for x in per_run])
            sm, sh = ci95([x["rms_err"] for x in per_run])
            print(f"  run {i+1:3d}/{a.runs}  seed={seed}  "
                  f"recall={rm*100:6.2f}±{rh*100:5.2f}  "
                  f"precision={pm*100:6.2f}±{ph*100:5.2f}  "
                  f"rms={sm:.4f}±{sh:.4f} px")

            if os.path.exists(bin_path):
                os.remove(bin_path)          # 1024^2 x 60 kare x 4B = 250 MB/run -> biriktirme

        dt = time.time() - t0
        rec = np.array([x["recall"] for x in per_run])
        pre = np.array([x["precision"] for x in per_run])
        rms = np.array([x["rms_err"] for x in per_run])
        rm, rh = ci95(rec); pm, ph = ci95(pre); sm, sh = ci95(rms)

        print(f"\n  --- k={k} OZET ({dt:.0f} s) ---")
        if len(rec) > 1:
            s_rec, s_pre = rec.std(ddof=1), pre.std(ddof=1)
            n_rec = required_n(s_rec, a.target_halfwidth)
            n_pre = required_n(s_pre, a.target_halfwidth)
            print(f"  recall    : {rm*100:6.2f} % ± {rh*100:.2f}   (sigma={s_rec*100:.2f})")
            print(f"  precision : {pm*100:6.2f} % ± {ph*100:.2f}   (sigma={s_pre*100:.2f})")
            print(f"  rms hata  : {sm:.4f} px ± {sh:.4f}")
            if s_rec == 0.0 and s_pre == 0.0 and not a.no_noise:
                if noise_responds is False:
                    print("  !! KRITIK: sigma = 0.00 ve goruntuler de AYNI -> MC DEJENERE.")
                    print("     Guven araliklari ANLAMSIZ. NoiseLUT kapatilmis mi kontrol et.")
                else:
                    # Goruntuler farkli ama tespit sonucu ayni -> BU BIR HATA DEGIL.
                    print("  [bilgi] recall/precision sigma = 0, ama goruntuler FARKLI.")
                    print("          => Tespit bu rejimde GURULTUYE DUYARSIZ: yildizlarin SNR'i")
                    print("             o kadar yuksek ki gurultu hicbir tespiti devirmiyor.")
                    print("             Bu bir bug degil, olculmus bir SONUC.")

                    # SIFIR BASARISIZLIK -> "±0.00" YANILTICI.
                    # Sifir hata gormek, hata olasiligi sifir demek degildir. Dogru ifade
                    # UC KURALI (rule of three): n denemede 0 basarisizlik gorulduyse,
                    # gercek basarisizlik oraninin %95 ust siniri 3/n'dir.
                    tot_gt = int(sum(r["TP"] + r["FN"] for r in per_run))
                    tot_det = int(sum(r["TP"] + r["FP"] for r in per_run))
                    tot_fn = int(sum(r["FN"] for r in per_run))
                    tot_fp = int(sum(r["FP"] for r in per_run))

                    print()
                    print(f"  [uc kurali] {a.runs} kosu x {a.frames} kare boyunca:")
                    if tot_fn == 0 and tot_gt > 0:
                        lo = 100.0 * (1.0 - 3.0 / tot_gt)
                        print(f"    {tot_gt:7d} yildiz-tespiti, {tot_fn} kacan")
                        print(f"    -> recall    >= {lo:.3f} %  (%95 guvenle, 3/n ust siniri)")
                    if tot_fp == 0 and tot_det > 0:
                        lo = 100.0 * (1.0 - 3.0 / tot_det)
                        print(f"    {tot_det:7d} tespit,          {tot_fp} sahte")
                        print(f"    -> precision >= {lo:.3f} %  (%95 guvenle)")
                    if tot_fn == 0 and tot_gt > 0:
                        # Siniri sikilastirmak icin gereken kosu sayisi
                        for hedef in (99.99, 99.999):
                            need_gt = math.ceil(3.0 / (1.0 - hedef / 100.0))
                            need_runs = math.ceil(need_gt / max(1, tot_gt / a.runs))
                            if need_runs > a.runs:
                                print(f"    recall >= {hedef} % diyebilmek icin: --runs {need_runs}")
                                break
                    print()
                    print(f"  rms icin gereken run (hedef ±0.001 px): "
                          f"{required_n(rms.std(ddof=1), 0.001)}")
            else:
                need = max(n_rec, n_pre)
                print(f"  hedef ±{a.target_halfwidth*100:.1f}% icin gereken run: "
                      f"recall={n_rec}, precision={n_pre}")
                print(f"  !! YAKINSAMADI -> --runs {need} ile tekrar kos." if need > a.runs
                      else "  [ok] hedef guven araligina ulasildi.")
        else:
            print(f"  recall={rm*100:.2f} %  precision={pm*100:.2f} %  rms={sm:.4f} px  (tek kosu)")
            n_rec = n_pre = 0

        # --- P_det(mag) egrisi ---
        # KACAN sutunu KRITIK: P_det oranina bakip "sonuk yildizlar daha iyi
        # tespit ediliyor" gibi imkansiz sonuclar cikarmayi engeller. Ayni MUTLAK
        # kacan sayisi, farkli paydalarda cok farkli oranlar uretir.
        print(f"\n  {'mag':>11} {'gercek':>8} {'tespit':>8} {'KACAN':>6} {'P_det':>8}  "
              f"{'%95 CI':>14} {'rms_px':>8}")
        pdet = []
        for b in range(nb):
            if not A_tot[b]:
                continue
            p, lo, hi = wilson(int(A_tp[b]), int(A_tot[b]))
            rb = math.sqrt(A_sq[b] / A_n[b]) if A_n[b] else float("nan")
            miss = int(A_tot[b] - A_tp[b])
            pdet.append((0.5 * (mag_bins[b] + mag_bins[b + 1]), p, int(A_tot[b])))
            print(f"  {mag_bins[b]:4.1f}-{mag_bins[b+1]:4.1f} {A_tot[b]:8d} {A_tp[b]:8d} "
                  f"{miss:6d} {p*100:7.2f}%  [{lo*100:5.1f},{hi*100:5.1f}] {rb:8.4f}")

        # Tespit sinirindan uzak miyiz? Butun binlerde P_det yuksekse MC'nin
        # recall tarafi bilgi tasimaz.
        if pdet and min(p for (_m, p, _n) in pdet) > 0.90:
            print("\n  [bilgi] Butun magnitude binlerinde P_det > %90 -> sistem tespit")
            print("          sinirinin COK uzaginda. Limiting magnitude olcmek icin")
            print("          --mag-limit 9.5 gibi daha derin bir katalog kullan.")

        lim = None
        for j in range(1, len(pdet)):
            m0, p0, _ = pdet[j - 1]; m1, p1, _ = pdet[j]
            if p0 >= 0.5 > p1:
                lim = m0 + (0.5 - p0) * (m1 - m0) / (p1 - p0)
                break
        print(f"\n  Limiting magnitude (P_det=%50) : "
              + (f"{lim:.2f}" if lim else "bu mag araliginda kesismedi"))
        print()

        if a.dump_failures:
            report_failures(fail_rows,
                            str(out_dir / f"basarisizliklar_k{k}_seed{a.seed0}.csv"),
                            half_streak=half_streak, sigma_psf=sigma_psf)
            print()

        # ===================================================================
        #  BIAS ANALIZI  --  star tracker icin EN KRITIK olcum
        # ===================================================================
        # rms isaretsizdir, sistematik kaymayi gizler. Burada isaretli ortalama
        # hatayi olcup, hatanin ne kadarinin SACILMA (ortalamayla kuculur) ne
        # kadarinin BIAS (ortalamayla kuculmez) oldugunu ayiriyoruz.
        bx = np.array([r["bias_x"] for r in per_run])
        by = np.array([r["bias_y"] for r in per_run])
        br = np.array([r["bias_r"] for r in per_run])
        bxm, bxh = ci95(bx)
        bym, byh = ci95(by)
        brm, brh = ci95(br)
        bias_mag = math.hypot(bxm, bym)

        # Plate scale: piksel -> arcsec
        plate_arcsec = math.degrees(
            math.tan(math.radians(a.fov / 2.0)) / (a.width / 2.0)) * 3600.0

        print()
        print("  --- BIAS ANALIZI (sistematik kayma var mi?) ---")
        print(f"  ortalama dx : {bxm:+.4f} px ± {bxh:.4f}   "
              f"{'ANLAMLI BIAS' if abs(bxm) > bxh else 'sifirdan ayirt edilemiyor'}")
        print(f"  ortalama dy : {bym:+.4f} px ± {byh:.4f}   "
              f"{'ANLAMLI BIAS' if abs(bym) > byh else 'sifirdan ayirt edilemiyor'}")
        print(f"  radyal      : {brm:+.4f} px ± {brh:.4f}   "
              f"{'ANLAMLI (distorsiyon/roll?)' if abs(brm) > brh else 'sifirdan ayirt edilemiyor'}")
        print(f"  |bias|      : {bias_mag:.4f} px  = {bias_mag*plate_arcsec:.2f} arcsec")
        print(f"  rms (toplam): {sm:.4f} px  = {sm*plate_arcsec:.2f} arcsec")

        # Hatayi iki bilesene ayir:  rms^2 = bias^2 + sacilma^2
        sacilma = math.sqrt(max(0.0, sm**2 - bias_mag**2))
        pay = 100.0 * bias_mag**2 / sm**2 if sm > 0 else 0.0
        print(f"  -> sacilma  : {sacilma:.4f} px   (ortalamayla 1/sqrt(N) kuculur)")
        print(f"  -> bias     : {bias_mag:.4f} px   (ortalamayla KUCULMEZ)")
        print(f"  -> hatanin %{pay:.1f}'i sistematik")

        # Attitude hatasi: N yildiz uzerinden ortalama alindiginda ne kalir?
        n_yildiz = (sum(r["TP"] for r in per_run) / a.runs) / a.frames
        if n_yildiz >= 1:
            att = math.sqrt(bias_mag**2 + (sacilma**2) / n_yildiz)
            att_bias_yok = sacilma / math.sqrt(n_yildiz)
            print()
            print(f"  --- ATTITUDE HATASI TAHMINI (kare basina {n_yildiz:.1f} yildiz) ---")
            print(f"  attitude hatasi ≈ sqrt(bias² + sacilma²/N)")
            print(f"    = {att:.4f} px = {att*plate_arcsec:.2f} arcsec")
            if bias_mag > 0.05 * sm:
                print(f"  !! bias olmasaydi: {att_bias_yok*plate_arcsec:.2f} arcsec olurdu.")
                print(f"     Bias, attitude hatasinin TABANINI belirliyor -- daha cok yildiz")
                print(f"     eklemek bu tabani DUSURMEZ. Kaynagini bulmak gerekir.")
            else:
                print(f"  [ok] bias ihmal edilebilir; hata saf sacilma, yildiz sayisiyla kuculur.")

        results[k] = {
            "runs": a.runs, "frames": a.frames, "seeds": seeds,
            "com_half": com_half, "streak_px": trans + roll, "no_noise": a.no_noise,
            "edge_margin": a.edge_margin,
            "recall_mean": rm, "recall_ci95": rh,
            "precision_mean": pm, "precision_ci95": ph,
            "rms_mean": sm, "rms_ci95": sh,
            "bias_x": bxm, "bias_x_ci95": bxh,
            "bias_y": bym, "bias_y_ci95": byh,
            "bias_r": brm, "bias_r_ci95": brh,
            "bias_mag_px": bias_mag,
            "sacilma_px": sacilma,
            "plate_arcsec_px": plate_arcsec,
            "required_n_recall": n_rec, "required_n_precision": n_pre,
            "limiting_mag": lim,
            "pdet": [{"mag": m, "p": p, "n": n} for (m, p, n) in pdet],
            "per_run": [{kk: v for kk, v in r.items() if not isinstance(v, np.ndarray)}
                        for r in per_run],
        }

    # --- CRN: k'lar ayni seed'lerle kosuldu -> ESLESTIRILMIS fark (dusuk varyans) ---
    if len(k_list) > 1:
        print("=" * 74)
        print("  k KARSILASTIRMASI (Common Random Numbers -> eslestirilmis fark)")
        print("=" * 74)
        base = k_list[0]
        for k in k_list[1:]:
            dp = np.array([r["precision"] for r in results[k]["per_run"]]) - \
                 np.array([r["precision"] for r in results[base]["per_run"]])
            dr = np.array([r["recall"] for r in results[k]["per_run"]]) - \
                 np.array([r["recall"] for r in results[base]["per_run"]])
            mp, hp = ci95(dp); mr, hr = ci95(dr)
            print(f"  k={k} vs k={base}:  "
                  f"Δprecision={mp*100:+6.2f}±{hp*100:.2f} "
                  f"({'ANLAMLI' if abs(mp) > hp else 'anlamsiz'})   "
                  f"Δrecall={mr*100:+6.2f}±{hr*100:.2f} "
                  f"({'ANLAMLI' if abs(mr) > hr else 'anlamsiz'})")
        print()

    # Cikti adina seed araligini goem: paralel kosular birbirini ezmesin ve
    # hangi dosyanin hangi seed'lere ait oldugu adindan anlasilsin.
    out = out_dir / f"mc_sonuc_seed{a.seed0}-{a.seed0 + a.runs - 1}.json"
    with open(out, "w") as f:
        json.dump({"args": vars(a), "results": {str(k): v for k, v in results.items()}},
                  f, indent=2, default=float)
    print(f"[mc] sonuclar -> {out}")

    if os.path.exists(csv_path):
        os.remove(csv_path)


if __name__ == "__main__":
    main()
