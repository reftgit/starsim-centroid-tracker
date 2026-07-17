# starsim-integration — star-sim-tu köprü yaması

Bu klasör, **starsim-centroid-tracker** uygulamasının [star-sim-tu]
simülatörüyle birlikte çalışabilmesi için gereken tüm değişiklikleri içerir.

> **Neden patch tabanlı?** star-sim-tu bize ait değil; kodunu yeniden dağıtmamak
> için değiştirilen dosyaların tam kopyası yerine yalnızca **fark (patch)**
> tutulur. Tamamen bizim yazdığımız yeni dosyalar ise `new-files/` altında tam
> haliyle durur.

## Klasör yapısı

```
starsim-integration/
├── README.md                       <- bu dosya (tutorial)
├── apply.sh                        <- tek komutla kurulum / geri alma
├── patches/
│   └── starsim-changes.patch       <- 3 upstream dosyanın birleşik farkı
└── new-files/                      <- tamamen bize ait yeni dosyalar
    ├── gen_ground_truth.py         -> <star-sim-kök>/gen_ground_truth.py
    ├── otomasyon.sh                -> <star-sim-kök>/otomasyon.sh
    ├── random_pointing_runs.py     -> <star-sim-kök>/random_pointing_runs.py
    └── src/starsim/gui/fifo_tap.py -> <star-sim-kök>/src/starsim/gui/fifo_tap.py
```

## Neler değişiyor ve neden?

### Patch ile değiştirilen 3 dosya

| Dosya | Değişiklik | Neden gerekli |
|---|---|---|
| `src/starsim/render/renderer.py` | `render()` fonksiyonuna `return_truth: bool` parametresi eklendi. Her görünür yıldız için `(x, y, mag, star_id)` demeti içeren bir ground truth listesi de döndürülür. Streak (motion blur) durumunda GT merkezi, SmearedPSF'in gerçekte çizdiği simetrik izin merkezi olan **poz başı konumu** alınır (önceki yarım-iz kayma düzeltildi). Yalnızca görüntü sınırları içindeki yıldızlar kaydedilir. | Tracker'ın bulduğu centroid'leri karşılaştıracak birebir doğru referans (ground truth) yalnızca render aşamasında, piksel projeksiyonu yapılırken biliniyor. |
| `src/starsim/render/realtime.py` | (a) Frame cache `(id, frame)` yerine `(id, frame, truth)` tutar; (b) pointing hesabı `time.time()` yerine **`frame_counter / target_fps`** ile yapılır (deterministik); (c) `_render_frame_internal` truth'u da döndürür ve frame metadata'sına `"truth"` anahtarı eklenir. | Determinizm kritik: aynı `frame_id` her zaman aynı pointing'i → aynı ground truth'u üretmeli. Kare düşse veya geç işlense bile starsim-centroid-tracker'nin gördüğü kare ile GT birebir eşleşir. Monte Carlo doğrulamasının istatistiksel geçerliliği buna dayanır. |
| `src/starsim/gui/main_window.py` | `STARSIM_FIFO` ortam değişkeni varsa real-time başlarken bir `FifoFrameWriter` (musluk) açılır; her karede frame + truth + gerçek frame_id musluğa gönderilir. Musluk yalnızca kullanıcı real-time'ı tamamen kapatınca kapanır (FOV/çözünürlük değişimindeki iç restart'ta kapanmaz). | GUI'nin ekrana bastığı karelerin AYNISINI starsim-centroid-tracker'ye canlı aktarmak için. starsim-centroid-tracker tarafında hiçbir kod değişikliği gerekmez — FIFO sıradan bir `.bin` girdisi gibi okunur. |

### Yeni eklenen 4 dosya (tamamı bize ait)

| Dosya | Görev |
|---|---|
| `src/starsim/gui/fifo_tap.py` | GUI karelerini **ayrı bir thread'de** named pipe'a (FIFO) ham float32 olarak yazan köprü. Tracker yavaşsa eski kareler düşürülür (GUI asla bloklanmaz), her kare tek `write` ile atomik gider, çözünürlük değişimi algılanıp uyarı basılır. `STARSIM_GT` verilirse ground truth CSV'sini de yazar. |
| `gen_ground_truth.py` | Offline üretici: RealTimeRenderer'ı GUI/thread OLMADAN, real-time köprüsüyle **birebir aynı kod yolunda** (`_render_frame_internal`) çalıştırır. Çıktı: `.bin` kareler + `*_ground_truth.csv` + `*_params.txt` + isteğe bağlı PNG. Aynı parametre + aynı seed → real-time ile bit-bit aynı sonuç. |
| `otomasyon.sh` | exposure/aperture parametre tarama scripti (gen → tracker → compare zinciri). |
| `random_pointing_runs.py` | N kez, rastgele ama **izotropik** pointing (RA: U(0,360), Dec: arcsin(U(-1,1)), Roll: U(0,360)) ile uçtan uca koşu; `ozet.csv` + örnek başına klasör üretir. Yansız attitude doğruluk ölçümü için. |

## Ön koşul: star-sim-tu kaynak kodu

Bu depo star-sim-tu'nun kodunu **içermez** (bize ait olmadığı için yeniden
dağıtılmaz). Entegrasyonu kullanmadan önce star-sim-tu'yu kendi kaynağından
edinip bir klasöre çıkarmış olman gerekir, örn. `~/projeler/star-sim-tu-main`.
Aşağıdaki tüm komutlar bu klasörün var olduğunu varsayar.

## Ön koşul: star-sim venv kurulumu

Hem `apply.sh` sonrası doğrulama hem de günlük kullanım, star-sim'in kendi
sanal ortamı (venv) içinde çalışır. star-sim'i yeni indirdiysen önce bir kez:

```bash
cd ~/projeler/star-sim-tu-main
python3 -m venv .venv               # özerk Python alanı oluştur (bir kez)
source .venv/bin/activate           # ortamı aç (her yeni terminalde)
pip install -e ".[dev]"             # star-sim'i geliştirme modunda kur
pip install pyqt6 pytest-qt         # GUI + GUI testleri (pyproject'te eksikler)
```

`source .venv/bin/activate` çalıştırınca satır başında `(.venv)` görünür.
`bash: .venv/bin/activate: No such file or directory` hatası alıyorsan venv
henüz oluşturulmamış demektir — yukarıdaki ilk komutu çalıştır.

> Geliştirme modu (`-e`) sayesinde yamanın değiştirdiği `.py` dosyaları ekstra
> kurulum gerektirmeden anında geçerli olur.

## Kurulum

### Yol A — otomatik (önerilen)

```bash
cd ~/projeler/starsim-centroid-tracker/starsim-integration
./apply.sh ~/projeler/star-sim-tu-main
```

> Yol varsayımı: bu depo `~/projeler/starsim-centroid-tracker`, star-sim ise
> `~/projeler/star-sim-tu-main` altında kabul edilir. Başka yere açtıysan iki
> yolu da kendi konumuna göre değiştir (`otomasyon.sh` ve
> `random_pointing_runs.py` içindeki varsayılan yollar da aynı varsayımı
> kullanır; gerekirse `--tracker` / `--compare` argümanlarıyla ezilebilir).
> Deponun yerini unuttuysan: `find ~ -maxdepth 3 -name apply.sh 2>/dev/null`

Script sırasıyla: `.bak` yedeği alır → patch'i uygular → yeni dosyaları kopyalar.

Geri almak için:

```bash
./apply.sh ~/projeler/star-sim-tu-main --revert
```

### Yol B — elle

```bash
cd ~/projeler/star-sim-tu-main

# 1) Yedek al
cp src/starsim/render/renderer.py    src/starsim/render/renderer.py.bak
cp src/starsim/render/realtime.py    src/starsim/render/realtime.py.bak
cp src/starsim/gui/main_window.py    src/starsim/gui/main_window.py.bak

# 2) Patch'i uygula
patch -p1 < /path/to/starsim-centroid-tracker/starsim-integration/patches/starsim-changes.patch

# 3) Yeni dosyaları kopyala
NF=/path/to/starsim-centroid-tracker/starsim-integration/new-files
cp "$NF/src/starsim/gui/fifo_tap.py"  src/starsim/gui/fifo_tap.py
cp "$NF/gen_ground_truth.py"          gen_ground_truth.py
cp "$NF/otomasyon.sh"                 otomasyon.sh
cp "$NF/random_pointing_runs.py"      random_pointing_runs.py
chmod +x otomasyon.sh
```

> venv henüz kurulu değilse önce yukarıdaki **Ön koşul** bölümünü uygula.

## Doğrulama

```bash
cd ~/projeler/star-sim-tu-main
source .venv/bin/activate

python3 gen_ground_truth.py --frames 1 \
    --ra 120 --dec 10 --roll 0 \
    --ra-rate 1 --dec-rate 1 --roll-rate 2 \
    --fov 10 --exposure 0.05 --seed 42 \
    --aperture 0.025 \
    --width 1024 --height 1024 \
    --out /tmp/test.bin --png /tmp/test.png

head -3 /tmp/test_ground_truth.csv
```

Beklenen başlık ve örnek satırlar:

```
frame_id,star_x,star_y,mag,star_id
0,512.3401,488.1120,4.212,24436
0,301.8877,655.4013,5.980,25336
```

(star_id çıplak katalog numarasıdır; "HIP" gibi önekler yazım sırasında soyulur.)

Ardından tam zincir testi:

```bash
~/projeler/starsim-centroid-tracker/tracker /tmp/test.bin /tmp/centroids.csv 1024 1024 \
    --k 3 --min-flux 100 --max-pix 20000 --com-half 8 --no-window

python3 ~/projeler/starsim-centroid-tracker/compare.py /tmp/test_ground_truth.csv /tmp/centroids.csv --radius 1.0
```

Aynı parametre + aynı seed ile tekrar koşulduğunda compare çıktısı **birebir
aynı** olmalıdır. Sayılar değişiyorsa determinizm bozulmuş demektir (patch'in
`realtime.py` kısmının uygulandığını kontrol et).

## Uyumluluk notları

- `compare.py` sütunlara `csv.DictReader` ile İSİMLE eriştiği için yeni
  `star_id` kolonu geriye dönük uyumludur; eski GT dosyaları da çalışmaya
  devam eder.
- Patch, bu klasörün oluşturulduğu upstream sürüme göre üretilmiştir. Upstream
  güncellenirse `patch` komutu "hunk failed" verebilir; bu durumda `.rej`
  dosyalarındaki parçaları elle uygulamak gerekir.
- starsim-centroid-tracker tarafında **hiçbir değişiklik gerekmez** — köprünün tüm yükü star-sim
  tarafındadır, FIFO starsim-centroid-tracker'ye sıradan bir `.bin` girdisi gibi görünür.
