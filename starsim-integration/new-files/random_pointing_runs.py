#!/usr/bin/env python3
"""
random_pointing_runs.py — Uctan uca otomasyon (calisma alani: /tmp/tmp_ornek)

Senin elle kosman komutlarin AYNISINI, N kez, RASTGELE ama ANLAMLI pointing
(RA/Dec/Roll) ile calistirir. Diger tum parametreler SABIT kalir.

Her ornek icin sirasiyla:
  1) /tmp/tmp_ornek/ TEMIZLENIR (cakisma olmasin) -- senin rm -f komutunun karsiligi
  2) gen_ground_truth.py --out /tmp/tmp_ornek/test.bin --png /tmp/tmp_ornek/test.png
  3) tracker /tmp/tmp_ornek/test.bin /tmp/tmp_ornek/centroids.csv 1024 1024 ...
  4) compare.py /tmp/tmp_ornek/test_ground_truth.csv /tmp/tmp_ornek/centroids.csv --radius 1.0
  5) uretilenler  <outdir>/ornek_NNNN/  altina kopyalanir
  6) /tmp/tmp_ornek/ yeniden temizlenir

Cikti duzeni:
  sonuclar/
      ozet.csv                  <- tum ornekler tek tabloda (numara + RA/Dec/Roll + metrikler)
      ornek_0001/
          parametreler.txt      <- pointing + gen komutu + tracker komutu + _params.txt
          test_ground_truth.csv
          centroids.csv
          test.png
          karsilastirma.txt     <- compare.py ciktisi
          test.bin              <- yalnizca --keep-bin verilirse
      ornek_0002/
      ...

"Anlamli" rastgele pointing:
  RA   : U(0,360)
  Dec  : arcsin(U(-1,1))  -> gokyuzunde GERCEKTEN duzgun (isotropik) dagilim.
         (Dec'i dogrudan U(-90,90) secmek kutuplari asiri orneklerdi.)
  Roll : U(0,360)

Ornek:
  cd ~/projeler/star-sim-tu-main
  python3 random_pointing_runs.py --runs 20 \
      --ra-rate 1 --dec-rate 1 --roll-rate 2 \
      --fov 10 --exposure 0.05 --aperture 0.025 \
      --width 1024 --height 1024 --seed 42 \
      --k 3 --min-flux 100 --max-pix 20000 --com-half 8 \
      --radius 1.0 --outdir sonuclar

Sabit pointing (senin ornek komutunun aynen tekrari) istersen:
  --fixed-ra 120 --fixed-dec 10 --fixed-roll 0
"""

import argparse
import csv
import glob
import math
import os
import random
import re
import shutil
import subprocess
import sys

WORK = "/tmp/tmp_ornek"          # tum ara dosyalarin uretildigi calisma klasoru

# Senin rm -f komutundaki dosyalar (WORK icinde). Her ornek ONCESI ve SONRASI silinir.
TMP_NAMES = [
    "ground_truth.csv",
    "centroids.csv",
    "starsim.bin",
    "test.bin",
    "test_ground_truth.csv",
    "test.png",
    "test_params.txt",
]


def temizle_work():
    """rm -f /tmp/tmp_ornek/...  (cok kareli PNG'ler test_0000.png ... dahil)"""
    for name in TMP_NAMES:
        try:
            os.remove(os.path.join(WORK, name))
        except FileNotFoundError:
            pass
    for p in glob.glob(os.path.join(WORK, "test_[0-9][0-9][0-9][0-9].png")):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def draw_pointing(rng, dec_max):
    """Kure uzerinde duzgun (isotropik) rastgele yonelim."""
    ra = rng.uniform(0.0, 360.0)
    s = math.sin(math.radians(dec_max))
    dec = math.degrees(math.asin(rng.uniform(-s, s)))
    roll = rng.uniform(0.0, 360.0)
    return ra, dec, roll


def gt_istatistik(csv_path):
    """ground_truth.csv -> (toplam yildiz-satiri, kare basina ortalama)"""
    if not os.path.exists(csv_path):
        return 0, 0.0
    frames, n = set(), 0
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            fid = row.get("frame_id")
            if not fid:
                continue
            frames.add(fid)
            n += 1
    return n, (n / len(frames) if frames else 0.0)


def compare_metrikleri(cikti):
    def yakala(desen):
        m = re.search(desen, cikti)
        return float(m.group(1)) if m else None
    return {
        "recall": yakala(r"Recall.*?:\s*([\d.]+)\s*%"),
        "precision": yakala(r"Precision.*?:\s*([\d.]+)\s*%"),
        "f1": yakala(r"F1 skoru\s*:\s*([\d.]+)\s*%"),
        "rms_px": yakala(r"RMS\s*:\s*([\d.]+)"),
        "mean_px": yakala(r"ortalama\s*:\s*([\d.]+)"),
        "max_px": yakala(r"maks\s*:\s*([\d.]+)"),
        "tp": yakala(r"Dogru \(TP\)\s*:\s*(\d+)"),
        "fn": yakala(r"Kacan \(FN\)\s*:\s*(\d+)"),
        "fp": yakala(r"Sahte \(FP\)\s*:\s*(\d+)"),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Rastgele/sabit pointing ile gen + tracker + compare otomasyonu."
    )
    ap.add_argument("--runs", type=int, required=True, help="Kac ornek uretilecek")
    ap.add_argument("--outdir", type=str, default="sonuclar", help="Sonuc klasoru")

    # Arac yollari
    ap.add_argument("--gen", type=str, default="gen_ground_truth.py")
    ap.add_argument("--tracker", type=str, default=os.path.expanduser("~/projeler/starsim-centroid-tracker/tracker"))
    ap.add_argument("--compare", type=str, default=os.path.expanduser("~/projeler/starsim-centroid-tracker/compare.py"))
    ap.add_argument("--no-compare", action="store_true", help="compare.py'yi calistirma")

    # Rastgelelik
    ap.add_argument("--pointing-seed", type=int, default=1234,
                    help="Pointing dizisi seed'i (ayni seed = ayni RA/Dec/Roll dizisi)")
    ap.add_argument("--dec-max", type=float, default=90.0, help="|Dec| ust siniri (deg)")
    ap.add_argument("--min-stars", type=int, default=0,
                    help="Kare basina bundan az yildiz dusen pointing'i at (0=kapali)")
    ap.add_argument("--max-retries", type=int, default=50)
    ap.add_argument("--vary-noise-seed", action="store_true",
                    help="Her ornekte gurultu seed'ini degistir (varsayilan: sabit)")
    # Sabit pointing modu (senin ornek komutunun aynen tekrari icin)
    ap.add_argument("--fixed-ra", type=float, default=None)
    ap.add_argument("--fixed-dec", type=float, default=None)
    ap.add_argument("--fixed-roll", type=float, default=None)

    # SABIT star-sim parametreleri
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--ra-rate", type=float, default=1.0)
    ap.add_argument("--dec-rate", type=float, default=1.0)
    ap.add_argument("--roll-rate", type=float, default=2.0)
    ap.add_argument("--fov", type=float, default=10.0)
    ap.add_argument("--exposure", type=float, default=0.05)
    ap.add_argument("--aperture", type=float, default=0.025)
    ap.add_argument("--fwhm", type=float, default=2.0)
    ap.add_argument("--background", type=float, default=100.0)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--mag-limit", type=float, default=6.5)
    ap.add_argument("--catalog", type=str, default="hipparcos")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42, help="Gurultu seed'i")
    ap.add_argument("--no-noise", action="store_true")
    ap.add_argument("--stretch", choices=["log", "linear", "sqrt", "asinh"], default="log")
    ap.add_argument("--no-png", action="store_true", help="PNG uretme")

    # SABIT tracker parametreleri
    ap.add_argument("--k", type=float, default=3.0)
    ap.add_argument("--min-flux", type=float, default=100.0)
    ap.add_argument("--max-pix", type=int, default=20000)
    ap.add_argument("--min-pix", type=int, default=None)
    ap.add_argument("--com-half", type=int, default=8)

    # compare
    ap.add_argument("--radius", type=float, default=1.0)

    # arsivleme
    ap.add_argument("--keep-bin", action="store_true",
                    help="test.bin'i de sakla (~4 MB/kare)")

    args = ap.parse_args()

    if not os.path.exists(args.gen):
        sys.exit(f"[HATA] bulunamadi: {args.gen}  (--gen ile yolunu ver)")
    if not os.path.exists(args.tracker):
        sys.exit(f"[HATA] tracker bulunamadi: {args.tracker}  (--tracker ile yolunu ver)")
    yap_compare = (not args.no_compare) and os.path.exists(args.compare)
    if not args.no_compare and not yap_compare:
        print(f"[uyari] compare.py bulunamadi ({args.compare}); karsilastirma atlanacak.",
              file=sys.stderr)

    sabit_pointing = (args.fixed_ra is not None and
                      args.fixed_dec is not None and
                      args.fixed_roll is not None)

    os.makedirs(WORK, exist_ok=True)
    os.makedirs(args.outdir, exist_ok=True)
    rng = random.Random(args.pointing_seed)

    # WORK icindeki sabit dosya yollari
    p_bin = os.path.join(WORK, "test.bin")
    p_png = os.path.join(WORK, "test.png")
    p_gt = os.path.join(WORK, "test_ground_truth.csv")
    p_cen = os.path.join(WORK, "centroids.csv")
    p_par = os.path.join(WORK, "test_params.txt")

    ozet_path = os.path.join(args.outdir, "ozet.csv")
    of = open(ozet_path, "w", newline="")
    ow = csv.writer(of)
    ow.writerow(["ornek", "ra", "dec", "roll", "noise_seed",
                 "gercek_yildiz", "kare_basina", "tespit_satiri",
                 "TP", "FN", "FP", "recall_%", "precision_%", "f1_%",
                 "rms_px", "ortalama_px", "maks_px", "klasor"])

    print(f"[runner] {args.runs} ornek -> {os.path.abspath(args.outdir)}/")
    print(f"[runner] calisma alani  : {WORK}")
    if sabit_pointing:
        print(f"[runner] SABIT pointing : RA={args.fixed_ra} Dec={args.fixed_dec} "
              f"Roll={args.fixed_roll}  (rastgele degil)")
    else:
        print(f"[runner] RASTGELE pointing (isotropik) | pointing_seed={args.pointing_seed} "
              f"dec_max={args.dec_max}")
    print(f"[runner] SABIT star-sim : fov={args.fov} exp={args.exposure} ap={args.aperture} "
          f"rates=({args.ra_rate},{args.dec_rate},{args.roll_rate}) "
          f"{args.width}x{args.height} mag<={args.mag_limit} catalog={args.catalog}")
    print(f"[runner] SABIT tracker  : --k {args.k} --min-flux {args.min_flux} "
          f"--max-pix {args.max_pix} --com-half {args.com_half}")
    print("-" * 90)

    basarili = 0
    for run in range(1, args.runs + 1):
        tag = f"ornek_{run:04d}"
        hedef = os.path.join(args.outdir, tag)
        noise_seed = (args.seed + run) if args.vary_noise_seed else args.seed

        deneme = 0
        while True:
            deneme += 1
            temizle_work()                      # 1) ONCE temizle

            if sabit_pointing:
                ra, dec, roll = args.fixed_ra, args.fixed_dec, args.fixed_roll
            else:
                ra, dec, roll = draw_pointing(rng, args.dec_max)

            # 2) gen_ground_truth.py
            gen_cmd = [
                sys.executable, args.gen,
                "--frames", str(args.frames),
                "--ra", f"{ra:.6f}", "--dec", f"{dec:.6f}", "--roll", f"{roll:.6f}",
                "--ra-rate", str(args.ra_rate),
                "--dec-rate", str(args.dec_rate),
                "--roll-rate", str(args.roll_rate),
                "--fov", str(args.fov),
                "--exposure", str(args.exposure),
                "--aperture", str(args.aperture),
                "--fwhm", str(args.fwhm),
                "--background", str(args.background),
                "--width", str(args.width),
                "--height", str(args.height),
                "--mag-limit", str(args.mag_limit),
                "--catalog", args.catalog,
                "--fps", str(args.fps),
                "--seed", str(noise_seed),
                "--out", p_bin,
            ]
            if args.no_noise:
                gen_cmd.append("--no-noise")
            if not args.no_png:
                gen_cmd += ["--png", p_png, "--stretch", args.stretch]

            r = subprocess.run(gen_cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[{tag}] gen HATASI (rc={r.returncode}):\n{r.stderr.strip()[-800:]}")
                temizle_work()
                break

            toplam_gt, kare_basina = gt_istatistik(p_gt)

            if args.min_stars > 0 and kare_basina < args.min_stars and not sabit_pointing:
                if deneme < args.max_retries:
                    print(f"[{tag}] atlandi (kare basina {kare_basina:.1f} < {args.min_stars}) "
                          f"-> yeni pointing (deneme {deneme})")
                    continue
                print(f"[{tag}] UYARI: {args.max_retries} denemede min-stars saglanamadi.")

            # 3) tracker
            trk_cmd = [
                args.tracker, p_bin, p_cen,
                str(args.width), str(args.height),
                "--k", str(args.k),
                "--min-flux", str(args.min_flux),
                "--max-pix", str(args.max_pix),
                "--com-half", str(args.com_half),
                "--no-window",
            ]
            if args.min_pix is not None:
                trk_cmd += ["--min-pix", str(args.min_pix)]

            t = subprocess.run(trk_cmd, capture_output=True, text=True)
            if t.returncode != 0:
                print(f"[{tag}] tracker HATASI (rc={t.returncode}):\n{t.stderr.strip()[-800:]}")
                temizle_work()
                break

            tespit_satiri = 0
            if os.path.exists(p_cen):
                with open(p_cen) as f:
                    tespit_satiri = max(0, sum(1 for _ in f) - 1)

            # 4) compare.py
            m = {k: None for k in ("recall", "precision", "f1", "rms_px",
                                   "mean_px", "max_px", "tp", "fn", "fp")}
            cmp_cikti = ""
            if yap_compare:
                c = subprocess.run(
                    [sys.executable, args.compare, p_gt, p_cen, "--radius", str(args.radius)],
                    capture_output=True, text=True,
                )
                cmp_cikti = c.stdout + ("\n[stderr]\n" + c.stderr if c.stderr.strip() else "")
                if c.returncode == 0:
                    m = compare_metrikleri(c.stdout)
                else:
                    print(f"[{tag}] compare HATASI (rc={c.returncode})")

            # 5) Arsivle
            os.makedirs(hedef, exist_ok=True)
            with open(os.path.join(hedef, "parametreler.txt"), "w") as fp:
                fp.write(f"# {tag}\n\n# --- POINTING ---\n")
                fp.write(f"ra   = {ra:.6f}\ndec  = {dec:.6f}\nroll = {roll:.6f}\n")
                fp.write(f"pointing_modu = {'SABIT' if sabit_pointing else 'RASTGELE'}\n")
                fp.write(f"pointing_seed = {args.pointing_seed}\n")
                fp.write(f"noise_seed    = {noise_seed}\n\n")
                fp.write("# --- gen_ground_truth.py komutu ---\n" + " ".join(gen_cmd) + "\n\n")
                fp.write("# --- tracker komutu ---\n" + " ".join(trk_cmd) + "\n\n")
                if yap_compare:
                    fp.write("# --- compare.py komutu (calisma aninda) ---\n")
                    fp.write(f"{sys.executable} {args.compare} {p_gt} {p_cen} "
                             f"--radius {args.radius}\n")
                    fp.write("# bu klasordeki dosyalarla tekrar kosmak icin:\n")
                    fp.write(f"# {sys.executable} {args.compare} test_ground_truth.csv "
                             f"centroids.csv --radius {args.radius}\n\n")
                if os.path.exists(p_par):
                    fp.write("# --- gen_ground_truth.py _params.txt ---\n")
                    with open(p_par) as src:
                        fp.write(src.read())

            for src, dst in [(p_gt, "test_ground_truth.csv"),
                             (p_cen, "centroids.csv"),
                             (p_png, "test.png")]:
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(hedef, dst))
            for p in sorted(glob.glob(os.path.join(WORK, "test_[0-9][0-9][0-9][0-9].png"))):
                shutil.copy2(p, os.path.join(hedef, os.path.basename(p)))
            if args.keep_bin and os.path.exists(p_bin):
                shutil.copy2(p_bin, os.path.join(hedef, "test.bin"))
            if cmp_cikti:
                with open(os.path.join(hedef, "karsilastirma.txt"), "w") as fc:
                    fc.write(cmp_cikti)

            ow.writerow([
                run, f"{ra:.6f}", f"{dec:.6f}", f"{roll:.6f}", noise_seed,
                toplam_gt, f"{kare_basina:.2f}", tespit_satiri,
                m["tp"], m["fn"], m["fp"],
                m["recall"], m["precision"], m["f1"],
                m["rms_px"], m["mean_px"], m["max_px"], hedef,
            ])
            of.flush()

            durum = ""
            if m["recall"] is not None and m["rms_px"] is not None:
                durum = (f" | recall={m['recall']:.1f}% prec={m['precision']:.1f}% "
                         f"rms={m['rms_px']:.3f}px")
            print(f"[{tag}] RA={ra:8.3f} Dec={dec:+7.3f} Roll={roll:8.3f} "
                  f"| gt={toplam_gt} ({kare_basina:.1f}/kare) tespit={tespit_satiri}{durum}")

            temizle_work()                      # 6) SONRA temizle
            basarili += 1
            break

    of.close()
    print("-" * 90)
    print(f"[runner] BITTI: {basarili}/{args.runs} ornek basarili")
    print(f"[runner] ozet   : {ozet_path}")
    print(f"[runner] klasor : {os.path.abspath(args.outdir)}/")


if __name__ == "__main__":
    main()
