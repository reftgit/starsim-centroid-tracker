#!/usr/bin/env python3
"""
compare.py  —  ground_truth.csv (star-sim) ile centroids.csv (starsim-centroid-tracker) karsilastirmasi.

Her kare icin gercek yildizlari tespit edilen centroid'lerle eslestirir (en yakin
komsu, tolerans yaricapi R piksel) ve hata metrikleri hesaplar:
  * TP (dogru)   : R piksel icinde eslesen gercek yildiz
  * FN (kacan)   : hicbir tespitle eslesmeyen gercek yildiz
  * FP (sahte)   : hicbir gercek yildizla eslesmeyen tespit
  * recall       = TP/(TP+FN)   -> gercek yildizlarin ne kadari bulundu
  * precision    = TP/(TP+FP)   -> tespitlerin ne kadari gercek
  * piksel hata  : eslesenlerin konum farki (ortalama + RMS)

Kullanim:
  python3 compare.py ground_truth.csv centroids.csv [--radius 3.0] [--per-frame]

Sutunlar:
  ground_truth.csv : frame_id,star_x,star_y,mag
  centroids.csv    : frame_id,timestamp,star_id,cx,cy,flux,npix
"""

import argparse
import csv
import sys
from collections import defaultdict

import numpy as np


def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def load_ground_truth(path):
    d = defaultdict(list)
    skipped = 0
    with open(path) as f:
        for row in csv.DictReader(f):
            fid, x, y = row.get("frame_id"), _to_float(row.get("star_x")), _to_float(row.get("star_y"))
            if fid is None or fid == "" or x is None or y is None:
                skipped += 1
                continue
            try:
                d[int(fid)].append((x, y))
            except ValueError:
                skipped += 1
    if skipped:
        print(f"[uyari] ground_truth: {skipped} bozuk/eksik satir atlandi", file=sys.stderr)
    return d


def load_detections(path):
    d = defaultdict(list)
    skipped = 0
    with open(path) as f:
        for row in csv.DictReader(f):
            fid, cx, cy = row.get("frame_id"), _to_float(row.get("cx")), _to_float(row.get("cy"))
            if fid is None or fid == "" or cx is None or cy is None:
                skipped += 1
                continue
            try:
                d[int(fid)].append((cx, cy))
            except ValueError:
                skipped += 1
    if skipped:
        print(f"[uyari] centroids: {skipped} bozuk/eksik satir atlandi", file=sys.stderr)
    return d


def match_indices(gt, det, radius):
    """Greedy en-yakin-komsu eslestirme. Her tespit en fazla bir kez kullanilir.

    Bu, eslestirmenin TEK kaynagidir; hem asagidaki match_frame() hem de
    mc_driver.py bunu kullanir. Boylece Monte Carlo'nun urettigi recall/
    precision ile elle kosulan compare.py'nin urettigi sayilar ayni koddan
    gelir (metrik ayrismasi imkansiz).

    gt     : [(x, y), ...]    gercek yildiz konumlari
    det    : [(cx, cy), ...]  tracker centroid'leri
    radius : eslestirme tolerans yaricapi (piksel)

    Donus  : {gt_index: (det_index, mesafe)}  -- eslesenler
    """
    used = [False] * len(det)
    matches = {}
    for i, (gx, gy) in enumerate(gt):
        best_j, best_d = -1, radius
        for j, (dx, dy) in enumerate(det):
            if used[j]:
                continue
            dd = ((gx - dx) ** 2 + (gy - dy) ** 2) ** 0.5
            if dd < best_d:
                best_d, best_j = dd, j
        if best_j >= 0:
            used[best_j] = True
            matches[i] = (best_j, best_d)
    return matches


def match_frame(gt, det, radius):
    """(geriye uyumlu) TP/FN/FP + eslesenlerin konum farklari."""
    matches = match_indices(gt, det, radius)
    tp = len(matches)
    dists = [d for (_j, d) in matches.values()]
    return tp, len(gt) - tp, len(det) - tp, dists


def main():
    ap = argparse.ArgumentParser(description="ground truth vs starsim-centroid-tracker tespit karsilastirmasi")
    ap.add_argument("ground_truth", help="ground_truth.csv (frame_id,star_x,star_y,mag)")
    ap.add_argument("centroids", help="centroids.csv (frame_id,timestamp,star_id,cx,cy,flux,npix)")
    ap.add_argument("--radius", type=float, default=3.0, help="eslestirme tolerans yaricapi (piksel)")
    ap.add_argument("--per-frame", action="store_true", help="her kare icin ayri satir yazdir")
    args = ap.parse_args()

    gt = load_ground_truth(args.ground_truth)
    det = load_detections(args.centroids)
    frames = sorted(set(gt) | set(det))
    if not frames:
        sys.exit("Hic kare bulunamadi; dosyalari kontrol et.")

    TP = FN = FP = 0
    all_dists = []
    per_frame_rows = []

    for fid in frames:
        g = gt.get(fid, [])
        d = det.get(fid, [])
        tp, fn, fp, dists = match_frame(g, d, args.radius)
        TP += tp; FN += fn; FP += fp
        all_dists.extend(dists)
        rms_f = (np.sqrt(np.mean(np.square(dists))) if dists else 0.0)
        per_frame_rows.append((fid, len(g), len(d), tp, fn, fp, rms_f))

    all_dists = np.array(all_dists) if all_dists else np.array([0.0])
    recall = TP / (TP + FN) if (TP + FN) else 0.0
    precision = TP / (TP + FP) if (TP + FP) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    mean_err = float(np.mean(all_dists))
    rms_err = float(np.sqrt(np.mean(np.square(all_dists))))
    max_err = float(np.max(all_dists))

    if args.per_frame:
        print(f"{'kare':>5} {'gercek':>7} {'tespit':>7} {'dogru':>6} {'kacan':>6} {'sahte':>6} {'rms_px':>8}")
        for (fid, ng, nd, tp, fn, fp, rms_f) in per_frame_rows:
            print(f"{fid:>5} {ng:>7} {nd:>7} {tp:>6} {fn:>6} {fp:>6} {rms_f:>8.3f}")
        print()

    print("=" * 52)
    print("  DOGRULAMA OZETI")
    print("=" * 52)
    print(f"  Kare sayisi          : {len(frames)}")
    print(f"  Eslestirme yaricapi  : {args.radius:.1f} piksel")
    print(f"  Toplam gercek yildiz : {TP + FN}")
    print(f"  Toplam tespit        : {TP + FP}")
    print(f"  Dogru (TP)           : {TP}")
    print(f"  Kacan (FN)           : {FN}")
    print(f"  Sahte (FP)           : {FP}")
    print("-" * 52)
    print(f"  Recall  (bulunan/gercek)  : {recall*100:6.2f} %")
    print(f"  Precision (dogru/tespit)  : {precision*100:6.2f} %")
    print(f"  F1 skoru                  : {f1*100:6.2f} %")
    print("-" * 52)
    print(f"  Konum hatasi ortalama : {mean_err:.4f} piksel")
    print(f"  Konum hatasi RMS      : {rms_err:.4f} piksel")
    print(f"  Konum hatasi maks     : {max_err:.4f} piksel")
    print("=" * 52)


if __name__ == "__main__":
    main()
