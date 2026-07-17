#define _POSIX_C_SOURCE 199309L
#include "pipeline.h"
#include "frame_source.h"
#include "csv_logger.h"
#include "centroid.h"
#include "display.h"
#include "queue.h"
#include <pthread.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>

// Thread'lerin paylastigi baglam
typedef struct {
    PipelineConfig cfg;
    Queue free_q;     // Frame*  (bos havuz) -> backpressure
    Queue frame_q;    // Frame*  (dolu kareler)
    Queue result_q;   // ResultBatch* (CSV logger'a)
    Queue display_q;  // DisplayItem* (gorsel pencereye) -- sadece show_window ise
    FrameSource src;
    volatile int stop; // pencere kapatilinca uretimi durdur
} Ctx;

// 1) ACQUISITION (uretici)
static void *acq_thread(void *arg) {
    Ctx *ctx = (Ctx*)arg;
    for (;;) {
        if (ctx->stop) break;                       // pencere kapatildi
        Frame *f = (Frame*)queue_pop(&ctx->free_q);
        if (!f) break;
        if (!frame_source_read(&ctx->src, f)) {     // EOF
            queue_push(&ctx->free_q, f);
            break;
        }
        queue_push(&ctx->frame_q, f);
    }
    queue_close(&ctx->frame_q);
    return NULL;
}

// İşleme thread'i, gosterim acikken o karenin gri+centroid paketini uretir
static DisplayItem *make_display_item(const Frame *f, const ResultBatch *b) {
    size_t N = (size_t)f->width * f->height;
    DisplayItem *it = malloc(sizeof(DisplayItem));
    it->width = f->width; it->height = f->height;
    it->gray = malloc(N);

    // float -> 0-255: kare icindeki max'a gore olcekle (girdi olceginden bagimsiz)
    float vmax = 1.0f;
    for (size_t i = 0; i < N; i++) if (f->data[i] > vmax) vmax = f->data[i];
    for (size_t i = 0; i < N; i++) {
        float g = f->data[i] / vmax * 255.0f;
        it->gray[i] = (unsigned char)(g < 0 ? 0 : (g > 255 ? 255 : g));
    }

    it->count = b->count;
    it->cx = malloc((b->count > 0 ? b->count : 1) * sizeof(float));
    it->cy = malloc((b->count > 0 ? b->count : 1) * sizeof(float));
    for (int i = 0; i < b->count; i++) {
        it->cx[i] = (float)b->items[i].cx;
        it->cy[i] = (float)b->items[i].cy;
    }
    return it;
}

// 2) PROCESSING (tuketici)
static void *proc_thread(void *arg) {
    Ctx *ctx = (Ctx*)arg;
    int W = ctx->cfg.width, H = ctx->cfg.height;
    size_t N = (size_t)W * H;

    uint8_t      *mask    = malloc(N);
    int          *scratch = malloc(N * sizeof(int));
    DetectedStar *stars   = malloc(ctx->cfg.max_stars * sizeof(DetectedStar));

    for (;;) {
        Frame *f = (Frame*)queue_pop(&ctx->frame_q);
        if (!f) break;

        PreStats ps = preprocess_run(f, mask, ctx->cfg.pre);
        DetParams dp = ctx->cfg.det;
        dp.background = ps.background;

        // --- TANI: ilk 10 kare + sonra her 60 karede bir (zamanla tespit profili) ---
        static int diag = 0;
        int show = (diag < 10) || (f->frame_id % 60 == 0);
        size_t over = 0;
        if (show)
            for (size_t i = 0; i < N; i++) over += mask[i];   // esigi gecen piksel (detector'dan ONCE)

        int n = detector_run(f, mask, dp, stars, ctx->cfg.max_stars, scratch);

        if (show) {
            float fmax = f->data[0];
            for (size_t i = 1; i < N; i++) if (f->data[i] > fmax) fmax = f->data[i];
            // tespit edilen bloblarin flux dagilimi -> dogru min_flux'u secmek icin
            float blob_max = 0.0f;
            int c1k = 0, c5k = 0, c20k = 0, c50k = 0;
            for (int i = 0; i < n; i++) {
                float fl = stars[i].flux;
                if (fl > blob_max) blob_max = fl;
                if (fl > 1000)  c1k++;
                if (fl > 5000)  c5k++;
                if (fl > 20000) c20k++;
                if (fl > 50000) c50k++;
            }
            fprintf(stderr,
                "[tani] frame=%llu bg=%.1f sigma=%.1f thr=%.1f kare_max=%.0f "
                "esik_gecen_px=%zu -> tespit=%d | blob_flux_max=%.0f "
                "(>1k=%d >5k=%d >20k=%d >50k=%d)\n",
                (unsigned long long)f->frame_id, ps.background, ps.sigma,
                ps.threshold, fmax, over, n, blob_max, c1k, c5k, c20k, c50k);
            if (diag < 10) diag++;
        }

        ResultBatch *b = malloc(sizeof(ResultBatch));
        b->frame_id  = f->frame_id;
        b->timestamp = f->timestamp;
        b->count     = n;
        b->items     = malloc((n > 0 ? n : 1) * sizeof(Centroid));
        // COM artik detector'da, blob pikselleri uzerinde hesaplaniyor.
        // Pencere tabanli centroid_com() kullanilmiyor -> gurultu kaidesi yok.
        for (int i = 0; i < n; i++) {
            b->items[i].cx   = stars[i].cx;
            b->items[i].cy   = stars[i].cy;
            b->items[i].flux = stars[i].flux;
            b->items[i].npix = stars[i].npix;
        }
        // Gosterim acikken: gri kare + centroid paketini gorsel kuyruga at
        if (ctx->cfg.show_window) {
            DisplayItem *it = make_display_item(f, b);
            queue_push(&ctx->display_q, it);   // kuyruk doluysa burada beklenir (pacing)
        }

        queue_push(&ctx->result_q, b);
        queue_push(&ctx->free_q, f);
    }
    queue_close(&ctx->result_q);
    if (ctx->cfg.show_window) queue_close(&ctx->display_q);

    free(mask); free(scratch); free(stars);
    return NULL;
}

int pipeline_run(PipelineConfig cfg) {
    Ctx ctx;
    ctx.cfg = cfg;
    ctx.stop = 0;

    if (!frame_source_open(&ctx.src, cfg.in_path, cfg.width, cfg.height, cfg.stamped)) {
        fprintf(stderr, "Giris acilamadi: %s\n", cfg.in_path);
        return 1;
    }

    queue_init(&ctx.free_q,   cfg.pool_size + 1);
    queue_init(&ctx.frame_q,  cfg.queue_cap);
    queue_init(&ctx.result_q, cfg.queue_cap);
    if (cfg.show_window) queue_init(&ctx.display_q, cfg.queue_cap);

    size_t N = (size_t)cfg.width * cfg.height;
    Frame *pool = malloc(cfg.pool_size * sizeof(Frame));
    for (int i = 0; i < cfg.pool_size; i++) {
        pool[i].data = malloc(N * sizeof(float));
        queue_push(&ctx.free_q, &pool[i]);
    }

    CsvLogger lg;
    if (!csv_logger_open(&lg, cfg.out_path, &ctx.result_q)) {
        fprintf(stderr, "Cikis acilamadi: %s\n", cfg.out_path);
        return 1;
    }

    // Pencere istendiyse SDL'i THREAD'LER BASLAMADAN once kur.
    // Sebep: SDL/X11 acilisi bazi sistemlerde LC_NUMERIC'i yerel dile ceviriyor
    // (ondalik virgul); display_create icindeki setlocale bunu geri aliyor ama
    // thread'ler once baslarsa aradaki pencerede virgullu satir yazabiliyorlar.
    // Once kurup sonra thread baslatinca bu yaris tamamen kapaniyor.
    DisplayCtx *disp = NULL;
    if (cfg.show_window) {
        disp = display_create(cfg.width, cfg.height, cfg.win_size, cfg.display_fps);
        if (!disp) fprintf(stderr, "Pencere acilamadi (SDL). Sadece CSV yazilacak.\n");
    }

    pthread_t t_acq, t_proc, t_log;
    pthread_create(&t_log,  NULL, csv_logger_thread, &lg);
    pthread_create(&t_proc, NULL, proc_thread, &ctx);
    pthread_create(&t_acq,  NULL, acq_thread,  &ctx);

    // GORSEL DONGU ana thread'de calisir (SDL GUI ana thread'i ister).
    // Bloklamayan: kare yoksa olay pompalar -> pencere donmuyor; akis bitince temiz cikar.
    if (cfg.show_window) {
        int running = (disp != NULL);
        int done = 0;
        struct timespec nap = { 0, 5L*1000*1000 };   // 5 ms
        while (!done) {
            int closed_empty = 0;
            DisplayItem *it = (DisplayItem*)queue_trypop(&ctx.display_q, &closed_empty);
            if (it) {
                if (running && !display_show(disp, it)) { running = 0; ctx.stop = 1; }
                display_item_free(it);            // durduysak da kuyrugu bosalt
            } else if (closed_empty) {
                done = 1;                          // akis bitti + kuyruk bos -> cik
            } else {
                if (running && !display_pump(disp)) { running = 0; ctx.stop = 1; }
                nanosleep(&nap, NULL);             // kare bekle, pencere yanitli kalsin
            }
        }
        if (disp) display_destroy(disp);
    }

    pthread_join(t_acq,  NULL);
    pthread_join(t_proc, NULL);
    pthread_join(t_log,  NULL);

    printf("Bitti. Atlanan kare (id boslugu): %llu\n",
           (unsigned long long)lg.dropped);

    for (int i = 0; i < cfg.pool_size; i++) free(pool[i].data);
    free(pool);
    csv_logger_close(&lg);
    frame_source_close(&ctx.src);
    queue_destroy(&ctx.free_q);
    queue_destroy(&ctx.frame_q);
    queue_destroy(&ctx.result_q);
    if (cfg.show_window) queue_destroy(&ctx.display_q);
    return 0;
}
