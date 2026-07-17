#!/usr/bin/env bash
# ============================================================
#  star-sim-tu + starsim-centroid-tracker otomatik parametre tarama scripti
#  Kullanim:
#    cd ~/projeler/star-sim-tu-main
#    source .venv/bin/activate
#    ./otomasyon.sh
# ============================================================
set -u

# ---------------- AYARLAR ----------------
STARSIM_DIR="$HOME/projeler/star-sim-tu-main"
TRACKER="$HOME/projeler/starsim-centroid-tracker/tracker"
COMPARE="$HOME/projeler/starsim-centroid-tracker/compare.py"

SONUC_DIR="$STARSIM_DIR/otomasyon_sonuclari"

# Yol dogrulamasi: eksikse net hata ver (sessiz "command not found" yerine)
[ -d "$STARSIM_DIR" ] || { echo "[HATA] star-sim bulunamadi: $STARSIM_DIR (STARSIM_DIR degiskenini duzenle)"; exit 1; }
[ -x "$TRACKER" ]     || { echo "[HATA] tracker bulunamadi: $TRACKER (repo kokunde 'make' calistir veya TRACKER degiskenini duzenle)"; exit 1; }
[ -f "$COMPARE" ]     || { echo "[HATA] compare.py bulunamadi: $COMPARE (COMPARE degiskenini duzenle)"; exit 1; }

# Sabit parametreler
FRAMES=100
RA=120; DEC=10; ROLL=0
FOV=10; SEED=42
W=1024; H=1024

# Tracker parametreleri
K=3; MIN_FLUX=2000; MAX_PIX=20000
RADIUS=1.0

# Denenecek exposure degerleri
EXPOSURES=(0.1 0.05)

# Rate baslangic degerleri (kaldigin yerden devam icin degistir)
BASLANGIC_RA=48
BASLANGIC_DEC=46
BASLANGIC_ROLL=17

# Her artista rate kac artsin (buyuk adim = hizli cokus, kaba tarama)
ADIM=4

# Her exposure icin en fazla kac deneme
MAX_RATE_DENEME=40

# HEDEF: precision %0'a DUSUNCE dur (tum tespitler yanlis olana kadar
# rate'ler artirilarak denenir).
HEDEF_PRECISION=0.00

# /tmp temizligi (senin verdigin komutun aynisi)
temizle_tmp() {
    rm -f /tmp/ground_truth.csv /tmp/centroids.csv /tmp/starsim.bin \
          /tmp/test.bin /tmp/test_ground_truth.csv /tmp/test.png /tmp/test_params.txt
}

hedef_tutturuldu() {
    # $1 = precision degeri (or. 99.47)
    # precision <= HEDEF_PRECISION (yani %0) ise 0 (basari) doner
    awk -v p="$1" -v h="$HEDEF_PRECISION" 'BEGIN { exit !(p <= h) }'
}

# ---------------- HAZIRLIK ----------------
cd "$STARSIM_DIR" || { echo "HATA: $STARSIM_DIR bulunamadi"; exit 1; }

# venv aktif degilse otomatik aktive et
if [ -z "${VIRTUAL_ENV:-}" ]; then
    if [ -f "$STARSIM_DIR/.venv/bin/activate" ]; then
        source "$STARSIM_DIR/.venv/bin/activate"
        echo "[otomasyon] venv otomatik aktive edildi: $VIRTUAL_ENV"
    else
        echo "HATA: venv bulunamadi ($STARSIM_DIR/.venv). Once venv olustur."
        exit 1
    fi
fi

mkdir -p "$SONUC_DIR"
OZET="$SONUC_DIR/ozet.csv"
if [ ! -f "$OZET" ]; then
    echo "deneme,exposure,ra_rate,dec_rate,roll_rate,precision,recall,f1,rms_px" > "$OZET"
fi

# Deneme numarasi mevcut en buyuk klasor numarasindan devam etsin
# (eski sonuclarin uzerine yazilmasin)
son_no=$(ls -d "$SONUC_DIR"/deneme_* 2>/dev/null | sed 's/.*deneme_//' | sort -n | tail -1)
deneme_no=${son_no:-0}
deneme_no=$((10#$deneme_no))
echo "[otomasyon] Deneme numaralari $((deneme_no + 1))'den devam edecek."
bulundu=0

# ---------------- ANA DONGU ----------------
for EXP in "${EXPOSURES[@]}"; do
    [ "$bulundu" -eq 1 ] && break

    # rate'ler baslangic degerlerinden baslar
    RA_RATE=$BASLANGIC_RA; DEC_RATE=$BASLANGIC_DEC; ROLL_RATE=$BASLANGIC_ROLL
    hangi=0          # 0=ra, 1=dec (donusumlu artar)
    artis_sayaci=0   # toplam artis sayisi; her 5 artista roll +ADIM

    for ((i=1; i<=MAX_RATE_DENEME; i++)); do
        deneme_no=$((deneme_no + 1))
        klasor=$(printf "%s/deneme_%03d" "$SONUC_DIR" "$deneme_no")
        mkdir -p "$klasor"

        echo ""
        echo "############################################################"
        echo "# DENEME $deneme_no | exp=$EXP ra_rate=$RA_RATE dec_rate=$DEC_RATE roll_rate=$ROLL_RATE"
        echo "############################################################"

        # Onceki kalintilari temizle
        temizle_tmp

        # 1) Goruntu + ground truth uret
        python3 gen_ground_truth.py --frames "$FRAMES" \
            --ra "$RA" --dec "$DEC" --roll "$ROLL" \
            --ra-rate "$RA_RATE" --dec-rate "$DEC_RATE" --roll-rate "$ROLL_RATE" \
            --fov "$FOV" --exposure "$EXP" --seed "$SEED" \
            --width "$W" --height "$H" --out /tmp/test.bin \
            2>&1 | tee "$klasor/gen_log.txt"

        # Goruntunun olusmasi icin 10 saniye bekle
        echo "[otomasyon] 10 saniye bekleniyor..."
        sleep 10

        if [ ! -f /tmp/test.bin ]; then
            echo "[otomasyon] HATA: /tmp/test.bin olusmadi, bu deneme atlaniyor."
            echo "HATA: test.bin olusmadi" > "$klasor/HATA.txt"
            temizle_tmp
            continue
        fi

        # 2) Tracker'i calistir
        "$TRACKER" /tmp/test.bin /tmp/centroids.csv "$W" "$H" \
            --k "$K" --min-flux "$MIN_FLUX" --max-pix "$MAX_PIX" \
            2>&1 | tee "$klasor/tracker_log.txt"

        if [ ! -f /tmp/centroids.csv ]; then
            echo "[otomasyon] HATA: centroids.csv olusmadi, bu deneme atlaniyor."
            echo "HATA: centroids.csv olusmadi" > "$klasor/HATA.txt"
            temizle_tmp
            continue
        fi

        # 3) Karsilastir
        python3 "$COMPARE" /tmp/test_ground_truth.csv /tmp/centroids.csv \
            --radius "$RADIUS" 2>&1 | tee "$klasor/compare_cikti.txt"

        # 4) Sonuclari klasore kaydet (.bin ASLA kopyalanmaz!)
        cp /tmp/test_ground_truth.csv "$klasor/" 2>/dev/null
        cp /tmp/centroids.csv         "$klasor/" 2>/dev/null
        cp /tmp/test_params.txt       "$klasor/" 2>/dev/null

        # Denenen parametreleri de ayrica yaz
        {
            echo "deneme      : $deneme_no"
            echo "exposure    : $EXP"
            echo "ra_rate     : $RA_RATE"
            echo "dec_rate    : $DEC_RATE"
            echo "roll_rate   : $ROLL_RATE"
            echo "k           : $K"
            echo "min_flux    : $MIN_FLUX"
            echo "max_pix     : $MAX_PIX"
            echo "radius      : $RADIUS"
        } > "$klasor/denenen_parametreler.txt"

        # 5) Compare ciktisindan metrikleri cek
        PREC=$(awk -F: '/Precision/ {gsub(/[ %]/,"",$2); print $2}' "$klasor/compare_cikti.txt")
        REC=$(awk  -F: '/Recall/    {gsub(/[ %]/,"",$2); print $2}' "$klasor/compare_cikti.txt")
        F1=$(awk   -F: '/F1 skoru/  {gsub(/[ %]/,"",$2); print $2}' "$klasor/compare_cikti.txt")
        RMS=$(awk  -F: '/RMS/       {gsub(/[ piksel]/,"",$2); print $2}' "$klasor/compare_cikti.txt")

        REC=${REC:-NA}; F1=${F1:-NA}; RMS=${RMS:-NA}
        echo "$deneme_no,$EXP,$RA_RATE,$DEC_RATE,$ROLL_RATE,${PREC:-NA},$REC,$F1,$RMS" >> "$OZET"
        echo "[otomasyon] Sonuc: precision=${PREC:-NA} recall=$REC f1=$F1 rms=$RMS"

        # 6) /tmp temizligi
        temizle_tmp
        echo "[otomasyon] /tmp temizlendi, sonuclar: $klasor"

        # Precision parse edilemediyse hedef kontrolu yapma (sahte %0 olmasin)
        if [ -z "${PREC:-}" ]; then
            echo "[otomasyon] UYARI: precision okunamadi, hedef kontrolu atlandi."
            PREC_OK=0
        else
            PREC_OK=1
        fi

        # 7) Hedef kontrolu
        if [ "$PREC_OK" -eq 1 ] && hedef_tutturuldu "$PREC"; then
            echo ""
            echo "*** HEDEFE ULASILDI! precision=$PREC (deneme $deneme_no) ***"
            echo "*** Parametreler: exp=$EXP ra_rate=$RA_RATE dec_rate=$DEC_RATE roll_rate=$ROLL_RATE ***"
            bulundu=1
            break
        fi

        # 8) Rate artirma: ra ve dec donusumlu +ADIM; her 5 artista roll +ADIM
        case $hangi in
            0) RA_RATE=$((RA_RATE + ADIM)) ;;
            1) DEC_RATE=$((DEC_RATE + ADIM)) ;;
        esac
        hangi=$(( (hangi + 1) % 2 ))
        artis_sayaci=$((artis_sayaci + 1))
        if [ $((artis_sayaci % 5)) -eq 0 ]; then
            ROLL_RATE=$((ROLL_RATE + ADIM))
        fi
    done
done

echo ""
echo "============================================================"
if [ "$bulundu" -eq 1 ]; then
    echo "Tarama basariyla tamamlandi (hedef bulundu)."
else
    echo "Tarama bitti, hedefe ulasilamadi. ozet.csv'ye bak:"
fi
echo "Tum sonuclar : $SONUC_DIR"
echo "Ozet tablo   : $OZET"
echo "============================================================"
