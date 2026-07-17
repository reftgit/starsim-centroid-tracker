#ifndef PIPELINE_H
#define PIPELINE_H
#include "types.h"
#include "preprocess.h"
#include "detector.h"

typedef struct {
    int    width, height;
    int    pool_size;    // onceden tahsisli frame tamponu sayisi
    int    queue_cap;    // kuyruk kapasitesi
    int    max_stars;    // kare basina maksimum yildiz
    int    com_half;     // COM pencere yaricapi (half=5 -> 11x11)
    PreParams pre;
    DetParams det;       // background calisma aninda doldurulur
    const char *in_path; // frame .bin dosyasi
    const char *out_path;// cikti CSV
    int    show_window;  // 1 = canli SDL penceresi ac, 0 = sadece CSV
    int    win_size;     // pencerenin en uzun kenari (orn 800)
    int    display_fps;  // gosterim hizi (izlenebilirlik icin)
    int    stamped;      // 1 = FIFO'da her kare 8-bayt id damgali (senkron dogrulama)
} PipelineConfig;

int pipeline_run(PipelineConfig cfg);

#endif
