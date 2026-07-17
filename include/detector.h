#ifndef DETECTOR_H
#define DETECTOR_H
#include <stdint.h>
#include "types.h"

typedef struct {
    int   min_pixels; // bundan kucuk bloblar elenir (gurultu/cosmic ray)
    int   max_pixels; // bundan buyuk bloblar elenir (birlesmis/anomali)
    float min_flux;   // toplam parlaklik alt siniri
    float background; // preprocess'ten gelen bg (flux icin cikarilir)
} DetParams;

// mask (BOZULUR: ziyaret edilen pikseller sifirlanir) -> stars dizisi.
// 8-komsuluk flood fill ile connected components. scratch = W*H kapasiteli yigin.
// Donus: bulunan yildiz sayisi.
int detector_run(const Frame *f, uint8_t *mask, DetParams p,
                 DetectedStar *stars, int max_stars, int *scratch);

#endif
