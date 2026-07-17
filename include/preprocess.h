#ifndef PREPROCESS_H
#define PREPROCESS_H
#include <stdint.h>
#include "types.h"

typedef struct {
    float k;          // esik katsayisi (tipik 3-5)
    int   subsample;  // arka plan tahmininde her kac pikselden biri (1=hepsi)
    float abs_thresh; // >0 ise median/MAD yerine bu mutlak esik kullanilir (manuel)
} PreParams;

typedef struct {
    float background; // median
    float sigma;      // 1.4826 * MAD
    float threshold;  // background + k*sigma
} PreStats;

// img -> mask (1 = aday yildiz pikseli). mask onceden tahsisli (W*H byte).
PreStats preprocess_run(const Frame *f, uint8_t *mask, PreParams p);

#endif
