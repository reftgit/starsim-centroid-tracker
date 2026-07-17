#!/usr/bin/env bash
# ============================================================
#  starsim-integration/apply.sh
#  Temiz bir star-sim-tu kopyasina starsim-centroid-tracker entegrasyon yamasini uygular.
#
#  Kullanim:
#    ./apply.sh /path/to/star-sim-tu-main
#
#  Yaptigi isler:
#    1) Degistirilecek 3 dosyanin .bak yedegini alir
#    2) patches/starsim-changes.patch'i uygular (renderer/realtime/main_window)
#    3) new-files/ altindaki 4 yeni dosyayi dogru yerlerine kopyalar
#
#  Geri almak icin: ./apply.sh <kok> --revert
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${1:?Kullanim: ./apply.sh /path/to/star-sim-tu-main [--revert]}"
MODE="${2:-apply}"

if [ ! -f "$ROOT/src/starsim/render/renderer.py" ]; then
    echo "HATA: '$ROOT' bir star-sim-tu koku gibi gorunmuyor." >&2
    exit 1
fi

if [ "$MODE" = "--revert" ]; then
    echo "[geri alma] .bak yedekleri geri yukleniyor..."
    for f in src/starsim/render/renderer.py \
             src/starsim/render/realtime.py \
             src/starsim/gui/main_window.py; do
        if [ -f "$ROOT/$f.bak" ]; then
            mv "$ROOT/$f.bak" "$ROOT/$f"
            echo "  geri alindi: $f"
        fi
    done
    rm -f "$ROOT/src/starsim/gui/fifo_tap.py" \
          "$ROOT/gen_ground_truth.py" \
          "$ROOT/otomasyon.sh" \
          "$ROOT/random_pointing_runs.py"
    echo "[geri alma] tamam."
    exit 0
fi

echo "[1/3] Yedek aliniyor..."
for f in src/starsim/render/renderer.py \
         src/starsim/render/realtime.py \
         src/starsim/gui/main_window.py; do
    cp -n "$ROOT/$f" "$ROOT/$f.bak" && echo "  yedek: $f.bak"
done

echo "[2/3] Patch uygulaniyor..."
patch -p1 -d "$ROOT" < "$HERE/patches/starsim-changes.patch"

echo "[3/3] Yeni dosyalar kopyalaniyor..."
cp "$HERE/new-files/src/starsim/gui/fifo_tap.py" "$ROOT/src/starsim/gui/fifo_tap.py"
cp "$HERE/new-files/gen_ground_truth.py"        "$ROOT/gen_ground_truth.py"
cp "$HERE/new-files/otomasyon.sh"               "$ROOT/otomasyon.sh"
cp "$HERE/new-files/random_pointing_runs.py"    "$ROOT/random_pointing_runs.py"
chmod +x "$ROOT/otomasyon.sh"

echo
echo "TAMAM. Dogrulama icin:"
echo "  cd $ROOT && source .venv/bin/activate"
echo "  python3 gen_ground_truth.py --frames 1 --ra 120 --dec 10 --roll 0 \\"
echo "      --ra-rate 1 --dec-rate 1 --roll-rate 2 --fov 10 --exposure 0.05 \\"
echo "      --seed 42 --aperture 0.025 --width 1024 --height 1024 \\"
echo "      --out /tmp/test.bin --png /tmp/test.png"
echo "  head -3 /tmp/test_ground_truth.csv   # basligi kontrol et: ...,star_id"
