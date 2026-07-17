#ifndef TYPES_H
#define TYPES_H
#include <stdint.h>
#include <stddef.h>

// Tek bir kare: row-major float tampon + meta veri
typedef struct {
    uint64_t frame_id;   // kaçıncı kare (frame sürekliliği için)
    double   timestamp;  // CLOCK_MONOTONIC, saniye
    int      width;
    int      height;
    float   *data;       // width*height float, önceden tahsisli
} Frame;

// Detection çıktısı: bir yıldızın kaba (tamsayı) konumu
typedef struct {
    int   x, y;        // blob'un tamsayi merkezi (geriye uyumluluk)
    float cx, cy;      // aki-agirlikli COM (alt-piksel) -- YENI
    int   npix;
    float flux;
} DetectedStar;

// Centroiding çıktısı: alt-piksel merkez
typedef struct {
    double cx, cy;       // alt-piksel konum (COM)
    float  flux;
    int    npix;
} Centroid;

// Bir kareye ait tüm sonuçlar (logger'a giden paket)
typedef struct {
    uint64_t  frame_id;
    double    timestamp;
    int       count;
    Centroid *items;     // malloc'lu dizi; logger free eder
} ResultBatch;

#endif
