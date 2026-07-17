#include "pipeline.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Kullanim:
//   ./tracker <girdi> <cikti.csv> [W] [H] [opsiyonlar...]
//
//   girdi : .bin (ham float32) | video (mp4/avi/...) | FIFO (.bin uzantili named pipe)
//
//   Tespit esikleri (star-sim gibi gurultulu/yuksek-cozunurluklu kaynaklar icin):
//     --k <f>          MAD esik carpani (esik = bg + k*sigma).  Yuksek = az gurultu.  (vars. 5.0)
//     --min-pix <i>    bundan kucuk bloblar elenir (gurultu pihtisi).               (vars. 3)
//     --max-pix <i>    bundan buyuk bloblar elenir (birlesmis/anomali).             (vars. 500)
//     --min-flux <f>   toplam parlaklik (bg cikarilmis) alt siniri.                 (vars. 50.0)
//     --subsample <i>  arka plan tahmininde her kac pikselden biri (1=hepsi).       (vars. 4)
//     --com-half <i>   centroid penceresinin yari boyu.                             (vars. 5)
//     --max-stars <i>  kare basina maksimum tespit.                                 (vars. 1024)
//
//   Gosterim:
//     --no-window      canli SDL penceresini kapat (sadece CSV).
//     --win-size <i>   pencerenin en uzun kenari (piksel).                          (vars. 800)
//     --display-fps <i> gosterim hizi.                                              (vars. 10)
//
//   Ornek (star-sim 2048x2048, gurultu acik):
//     ./tracker /tmp/starsim.bin out.csv 2048 2048 --k 8 --min-pix 5 --min-flux 800

static int    has_opt(int argc, char **argv, const char *name) {
    for (int i = 1; i < argc; i++) if (strcmp(argv[i], name) == 0) return 1;
    return 0;
}
// --name <value> ; bulunamazsa def dondurur
static double opt_f(int argc, char **argv, const char *name, double def) {
    for (int i = 1; i < argc - 1; i++) if (strcmp(argv[i], name) == 0) return atof(argv[i + 1]);
    return def;
}
static int    opt_i(int argc, char **argv, const char *name, int def) {
    for (int i = 1; i < argc - 1; i++) if (strcmp(argv[i], name) == 0) return atoi(argv[i + 1]);
    return def;
}

int main(int argc, char **argv) {
    PipelineConfig cfg;

    // --- pozisyonel argumanlari topla ('--' ile baslamayanlar) ---
    const char *pos[4] = { NULL, NULL, NULL, NULL };
    int np = 0;
    for (int i = 1; i < argc && np < 4; i++) {
        if (argv[i][0] == '-' && argv[i][1] == '-') {
            // deger alan opsiyonsa bir sonrakini de atla
            if (strcmp(argv[i], "--no-window") != 0) i++;
            continue;
        }
        pos[np++] = argv[i];
    }

    cfg.in_path  = pos[0] ? pos[0] : "frames.bin";
    cfg.out_path = pos[1] ? pos[1] : "centroids.csv";
    cfg.width    = pos[2] ? atoi(pos[2]) : 512;
    cfg.height   = pos[3] ? atoi(pos[3]) : 512;

    cfg.pool_size = 8;
    cfg.queue_cap = 16;
    cfg.max_stars = opt_i(argc, argv, "--max-stars", 1024);
    cfg.com_half  = opt_i(argc, argv, "--com-half", 5);

    // --- tespit esikleri (CLI ile ayarlanabilir) ---
    cfg.pre.k          = (float)opt_f(argc, argv, "--k", 5.0);
    cfg.pre.subsample  = opt_i(argc, argv, "--subsample", 4);
    cfg.pre.abs_thresh = (float)opt_f(argc, argv, "--abs-thresh", 0.0);
    cfg.det.min_pixels = opt_i(argc, argv, "--min-pix", 3);
    cfg.det.max_pixels = opt_i(argc, argv, "--max-pix", 500);
    cfg.det.min_flux   = (float)opt_f(argc, argv, "--min-flux", 50.0);
    cfg.det.background = 0.0f;  // pipeline runtime'da preprocess median'i ile gunceller

    // --- gosterim ---
    cfg.show_window = has_opt(argc, argv, "--no-window") ? 0 : 1;
    cfg.win_size    = opt_i(argc, argv, "--win-size", 800);
    cfg.display_fps = opt_i(argc, argv, "--display-fps", 10);
    cfg.stamped     = has_opt(argc, argv, "--stamped") ? 1 : 0;

    printf("Giris: %s | Cikis: %s | Boyut: %dx%d | Pencere: %s%s\n",
           cfg.in_path, cfg.out_path, cfg.width, cfg.height,
           cfg.show_window ? "ACIK" : "kapali",
           cfg.stamped ? " | DAMGALI (senkron)" : "");
    printf("Esikler: k=%.2f min_pix=%d max_pix=%d min_flux=%.1f subsample=%d abs_thresh=%.1f\n",
           cfg.pre.k, cfg.det.min_pixels, cfg.det.max_pixels,
           cfg.det.min_flux, cfg.pre.subsample, cfg.pre.abs_thresh);
    return pipeline_run(cfg);
}
