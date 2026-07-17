# starsim-centroid-tracker

Gerçek zamanlı yıldız centroid tespiti yapan, saf C ile yazılmış çok iş parçacıklı
(pthread) bir görüntü işleme hattı. Ham kare akışını okur, arka planı istatistiksel
olarak kestirir, eşikler, connected components ile yıldız lekelerini gruplar,
ağırlık merkezi (COM) ile alt-piksel hassasiyetinde merkez bulur ve sonuçları
kare kaçırmadan CSV'ye yazar.

Doğrulama tarafında, [star-sim-tu] yıldız alanı simülatörünü veri kaynağı olarak
kullanan bir Python değerlendirme katmanı (`compare.py`, `mc_driver.py`) bulunur.
star-sim ile köprü kurmak için gereken yama ve dosyalar `starsim-integration/`
klasöründedir (aşağıya bakınız).

---

## 1. Mimari

3 thread + 3 bounded kuyruk, producer-consumer deseni:

```
[acquisition] --frame_q--> [processing] --result_q--> [logger]
     ^                                                    |
     +------------------ free_q (tampon havuzu) ----------+
```

- **acquisition**: `free_q`'dan boş tampon alır, kaynaktan kareyi okur, `frame_q`'ya iter.
- **processing**: preprocess + tespit + COM yapar, sonucu `result_q`'ya iter, tamponu havuza iade eder.
- **logger**: `result_q`'dan çeker, CSV'ye yazar, frame sürekliliğini denetler.

Tampon havuzu sıcak döngüye girmeden **bir kez** tahsis edilir (hot loop'ta
`malloc` yok). Kuyruklar bounded olduğu için doğal backpressure oluşur: bir
aşama yavaşlarsa diğerleri otomatik bekler, kare düşmez.

### Dosyalar

| Dosya | Görev |
|---|---|
| `include/types.h` | Frame, DetectedStar, Centroid, ResultBatch yapıları |
| `src/queue.c` | Bounded bloklayan kuyruk (mutex + condition variable) |
| `src/frame_source.c` | Ham float32 akışından / videodan / FIFO'dan kare okuma |
| `src/preprocess.c` | median/MAD arka plan kestirimi + eşikleme → maske |
| `src/detector.c` | Connected components + boyut/parlaklık filtreleri |
| `src/centroid.c` | COM ile alt-piksel merkez hesabı |
| `src/csv_logger.c` | Ayrı thread'de CSV yazımı |
| `src/pipeline.c` | Thread'leri ve kuyrukları bağlayan tutkal |
| `src/display.c` | İsteğe bağlı canlı SDL2 penceresi |
| `src/main.c` | Komut satırı ayrıştırma + çalıştırma |
| `src/gen_frames.c` | Test için sentetik hareketli yıldız üreteci (ayrı binary) |
| `compare.py` | Ground truth ↔ centroid eşleştirme ve metrik hesabı |
| `mc_driver.py` | Monte Carlo doğrulama sürücüsü |
| `starsim-integration/` | star-sim-tu köprü yaması ve yeni dosyalar |

---

## 2. Derleme

Bağımlılıklar: `gcc`, `make`, `libsdl2-dev` (canlı pencere için), video girişi
kullanılacaksa `ffmpeg`.

```bash
sudo apt install build-essential libsdl2-dev ffmpeg
make                # tracker + gen_frames üretir
```

C kodunda değişiklik yaptıktan sonra:

```bash
make clean
make
```

---

## 3. Kullanım

```
./tracker <girdi> <cikti.csv> [W] [H] [opsiyonlar...]
```

`girdi`: ham float32 `.bin` | video (mp4/avi/…) | named pipe (FIFO)

### Tespit eşikleri

| Opsiyon | Anlam | Varsayılan |
|---|---|---|
| `--k <f>` | MAD eşik çarpanı (eşik = bg + k·σ). Yüksek = az gürültü | 5.0 |
| `--min-pix <i>` | Bundan küçük bloblar elenir (gürültü pıhtısı) | 3 |
| `--max-pix <i>` | Bundan büyük bloblar elenir (birleşmiş/anomali) | 500 |
| `--min-flux <f>` | Toplam parlaklık (bg çıkarılmış) alt sınırı | 50.0 |
| `--subsample <i>` | Arka plan tahmininde örnekleme adımı (1 = tüm pikseller) | 4 |
| `--com-half <i>` | Centroid penceresinin yarı boyu | 5 |
| `--max-stars <i>` | Kare başına maksimum tespit | 1024 |
| `--stamped` | Damgalı akış modu (real-time FIFO senkronu için) | kapalı |

### Gösterim

| Opsiyon | Anlam | Varsayılan |
|---|---|---|
| `--no-window` | Canlı SDL penceresini kapat (sadece CSV) | pencere açık |
| `--win-size <i>` | Pencerenin en uzun kenarı (piksel) | 800 |
| `--display-fps <i>` | Gösterim hızı | 10 |

### Çıktı formatı

`centroids.csv` → `frame_id,timestamp,star_id,cx,cy,flux,npix`

### Girdi formatı

Ham binary, header yok: ardışık kareler, her biri W·H adet float32, row-major.
Boyut komut satırından verilir. Video girişinde `frame_source` içeride `ffmpeg`'i
alt süreç olarak çalıştırır; ek kütüphane linklenmez, sistemde `ffmpeg` binary'si
yeterlidir. (MP4 kayıplıdır; hassas ölçüm için kaynağı ham `.bin` tut.)

---

## 4. Üç ana çalışma senaryosu

### 4.1 Hızlı yerel test (star-sim'siz)

```bash
./gen_frames frames.bin ground_truth.csv     # 512x512, 30 kare, 12 sentetik yıldız
./tracker frames.bin centroids.csv 512 512
python3 compare.py ground_truth.csv centroids.csv --radius 1.0
```

### 4.2 Statik mod — star-sim'den offline üretim + işleme

star-sim tarafında (venv aktifken) deterministik `.bin` + ground truth üret:

```bash
python3 gen_ground_truth.py --frames 100 \
    --ra 120 --dec 10 --roll 0 \
    --ra-rate 1 --dec-rate 1 --roll-rate 2 \
    --fov 10 --exposure 0.05 --seed 42 \
    --aperture 0.025 \
    --width 1024 --height 1024 --out /tmp/tmp_ornek/test.bin
```

(`--frames 1` + `--png /tmp/tmp_ornek/test.png` ile tek kare + görüntülenebilir PNG de üretilebilir.)

Üretilen kareleri işle:

```bash
./tracker /tmp/tmp_ornek/test.bin /tmp/tmp_ornek/centroids.csv 1024 1024 \
    --k 3 --min-flux 100 --max-pix 20000 --com-half 8 --no-window
```

Karşılaştır:

```bash
python3 compare.py /tmp/tmp_ornek/test_ground_truth.csv /tmp/tmp_ornek/centroids.csv --radius 1.0
```

> Offline üretilen `.bin` **damgasızdır** (frame_id 0'dan sıralı) → tracker'ı
> `--stamped` OLMADAN çalıştır.

### 4.3 Real-time mod — star-sim GUI canlı yayınında centroid

star-sim GUI'sini FIFO köprüsüyle başlat:

```bash
STARSIM_FIFO=/tmp/starsim.bin STARSIM_GT=/tmp/ground_truth.csv python -m starsim.gui
```

Tracker'ı FIFO'ya bağla (**damgalı mod** zorunlu — kare düşmelerinde senkron korunur):

```bash
./tracker /tmp/starsim.bin /tmp/centroids.csv 1024 1024 \
    --stamped --k 3 --min-flux 1000 --max-pix 40000
```

Canlı doğrulama:

```bash
head -2 /tmp/ground_truth.csv
head -2 /tmp/centroids.csv
python3 compare.py /tmp/ground_truth.csv /tmp/centroids.csv --radius 1.0
```

### Test öncesi temizlik

Önceki koşuların artıkları yeni ölçümü kirletmesin diye:

```bash
rm -f /tmp/tmp_ornek/ground_truth.csv /tmp/tmp_ornek/centroids.csv \
      /tmp/tmp_ornek/starsim.bin /tmp/tmp_ornek/test.bin \
      /tmp/tmp_ornek/test_ground_truth.csv /tmp/tmp_ornek/test.png \
      /tmp/tmp_ornek/test_params.txt

rm -f /tmp/ground_truth.csv /tmp/centroids.csv /tmp/starsim.bin
```

---

## 5. Monte Carlo doğrulama (`mc_driver.py`)

Sabit bir senaryoda yalnızca **sensör gürültüsünü** rastgeleleyip (N farklı seed)
tracker metriklerinin hangi değerlere yakınsadığını ölçer:

- recall / precision / F1 (run bazında, %95 güven aralığıyla)
- P_det(mag): magnitude'a göre tespit olasılığı eğrisi
- limiting magnitude: P_det'in %50'yi kestiği nokta
- centroid konum hatası: RMS, magnitude binleri halinde

Örnek koşular:

```bash
# A) Büyük açıklık, nominal hız — modern yüksek doğruluk trackerı
python3 mc_driver.py --runs 20 --frames 60 \
    --ra 120 --dec 10 --roll 0 \
    --ra-rate 1 --dec-rate 1 --roll-rate 2 \
    --fov 8 --width 2048 --height 2048 \
    --exposure 0.05 --aperture 0.050 \
    --min-flux 100 --max-pix 20000 \
    --radius 2.0 --edge-margin auto

# B) Orta açıklık, yavaş dönüş — fine-pointing modu
python3 mc_driver.py --runs 20 --frames 60 \
    --ra 120 --dec 10 --roll 0 \
    --ra-rate 0.5 --dec-rate 0.5 --roll-rate 0.5 \
    --fov 8 --width 2048 --height 2048 \
    --exposure 0.05 --aperture 0.035 \
    --min-flux 100 --max-pix 20000 \
    --radius 2.0 --edge-margin auto
```

`--dump-failures` bayrağı kaçan tespitleri KENAR / BLEND / KACIRMA / DIGER
sınıflarına ayırarak döker.

### İstatistiksel geçerliliğin dayandığı üç nokta

1. **Determinizm**: starsim-integration yaması pointing'i `time.time()` yerine
   `frame_counter / target_fps`'e bağlar → geometri frame_id'ye deterministik
   bağlıdır, tek stokastik girdi sensör gürültüsüdür.
2. **Kare başına ayrı seed** türetilir (`seed·P + frame_id`); tek seed tüm
   karelerde aynı gürültü desenini üretir, kareler bağımsız olmazdı.
3. **Örnekleme birimi = 1 run (1 seed)**. Bir run'ın tüm kareleri o run'ın TEK
   istatistiğidir; "100 kare = 100 örnek" saymak yanlış olur çünkü kareler aynı
   yörüngede aynı yıldızları tekrar görür.

Ayrıca `fast_sensor_mode=False` kullanılır: fast modda seed yok sayıldığı için
yalnızca tam simülasyon yolunda seed etkilidir (PRNU/DSNU/dark current dahil).

### MC parametrelerinin anlamları

| Parametre | Anlam |
|---|---|
| `--runs` | Monte Carlo örnek sayısı; N farklı gürültü tohumuyla senaryo tekrarlanır, sonuç ortalama ± güven aralığı |
| `--frames` | Koşu başına üretilen kare sayısı |
| `--ra`, `--dec` | Başlangıç bakış yönü (derece); gökyüzünde hangi noktaya bakıldığı |
| `--roll` | Kamera ekseni etrafında başlangıç dönüklüğü (derece) |
| `--ra-rate`, `--dec-rate`, `--roll-rate` | Eksen dönüş hızları (derece/s); birlikte streak uzunluğunu belirler |
| `--fov` | Görüş açısı (derece) |
| `--exposure` | Poz süresi (s); toplanan ışık ve streak uzunluğu |
| `--aperture` | Açıklık çapı (m); toplanan ışığı belirleyen en güçlü parametre (alan ∝ çap²) |
| `--min-flux` | Tracker'ın bir lekeyi yıldız sayması için minimum toplam ışık |
| `--max-pix` | Kabul edilebilir maksimum blob piksel sayısı |
| `--radius` | Eşleştirme kapısı (piksel); GT yıldızına bu mesafedeki tespit "doğru" sayılır (tracker'a ulaşmaz, sadece puanlama) |
| `--edge-margin auto` | Kenara streak yarısı kadar yakın yıldızları hem GT hem tespit listesinden çıkarır (ışığı kadraj dışına taşan yıldızın merkezi zaten bulunamaz; bunu tracker hatası saymamak için) |

Not: `--com-half` MC'de verilmez; driver streak uzunluğundan otomatik hesaplar.

### Rastgele pointing otomasyonu

`random_pointing_runs.py` (star-sim tarafında), aynı zinciri N kez, izotropik
rastgele pointing ile koşar ve `ozet.csv` + örnek başına klasör üretir — yansız,
gökyüzü genelinde attitude doğruluk ölçümü için.

---

## 6. star-sim entegrasyonu

Bu tracker'ın star-sim ile birlikte çalışması, star-sim tarafına uygulanan
küçük bir yamaya dayanır (ground truth üretimi, deterministik pointing, FIFO
köprüsü). Yamanın kendisi, yeni dosyalar ve adım adım kurulum:

**→ [`starsim-integration/README.md`](starsim-integration/README.md)**

Önemli: bu depo star-sim-tu'nun kodunu **içermez** (üçüncü taraf kod yeniden
dağıtılmaz); star-sim-tu'yu kendi kaynağından ayrıca edinmen gerekir. Özet:
star-sim-tu'yu `~/projeler/star-sim-tu-main` gibi bir klasöre çıkar, sonra
`starsim-integration/apply.sh ~/projeler/star-sim-tu-main` tek komutla kurar.
starsim-centroid-tracker tarafında hiçbir değişiklik gerekmez.

---

## 7. Doğruluk ve bilinen düzeltmeler

- Sentetik test setinde COM RMS hatası ~0.01 piksel (alt-piksel doğruluk).
- Düzeltilen sistematik hatalar: integer cast kaynaklı 0.5 px COM kayması ve
  pencere tabanlı COM'un arka plan gürültü pedestalını kabul etmesi. İkisinin
  düzeltilmesi attitude hatasını ~9″ → ~4″ seviyesine indirdi.
- Streak GT tanımı: SmearedPSF izi simetrik çizdiği için ground truth poz başı
  konumudur (yarım-iz kayma yaması, bkz. starsim-integration).

## 8. Sonraki adım (Faz 2): Gaussian fitting

COM "garantili süre" verir. Daha yüksek doğruluk için COM merkezini başlangıç
tahmini alıp 2B Gaussian (streak modeli) oturtan bir Levenberg-Marquardt fit'i
AYRI bir worker thread'de çalıştırılabilir (süresi belirsiz olduğu için capture
döngüsüne konmaz).
