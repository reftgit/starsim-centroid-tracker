#include "preprocess.h"
#include <stdlib.h>
#include <math.h>

static int cmp_float(const void *a, const void *b) {
    float fa = *(const float*)a, fb = *(const float*)b;
    return (fa > fb) - (fa < fb);
}

static float median_inplace(float *v, size_t n) {
    qsort(v, n, sizeof(float), cmp_float);
    return v[n / 2];
}

PreStats preprocess_run(const Frame *f, uint8_t *mask, PreParams p) {
    size_t N = (size_t)f->width * f->height;
    int step = p.subsample < 1 ? 1 : p.subsample;

    // 1) Orneklenmis kopya -> median = arka plan (yildizlara karsi dayanikli)
    size_t m = 0;
    for (size_t i = 0; i < N; i += step) m++;
    float *tmp = malloc(m * sizeof(float));
    size_t j = 0;
    for (size_t i = 0; i < N; i += step) tmp[j++] = f->data[i];
    float bg = median_inplace(tmp, m);

    // 2) Ayni ornek kumesi uzerinde |x-bg| -> median = MAD -> sigma
    for (size_t i = 0; i < m; i++) tmp[i] = fabsf(tmp[i] - bg);
    float mad = median_inplace(tmp, m);
    free(tmp);

    float sigma = 1.4826f * mad;
    float thr;

    if (p.abs_thresh > 0.0f) {
        // (0) Manuel mutlak esik: median/MAD'i bypass et
        thr = p.abs_thresh;
    } else if (sigma < 1e-6f) {
        // (1) DEJENERE durum: median/MAD ~ 0.
        //     Bu, gorundunun >%50'sinin ayni degerde (tipik: bimodal gurultu,
        //     yani cogunluk tam sifir + geri kalan gurultu) oldugu anlamina gelir.
        //     Global median/MAD ise 0 -> thr 0 -> tum gurultu maskeye girer.
        //     Cozum: arka plan uzeri (>bg) piksellerin istatistigine dus.
        size_t nz = 0;
        for (size_t i = 0; i < N; i += step) if (f->data[i] > bg) nz++;

        if (nz > m / 20 && nz > 16) {
            // Gurultu baskin (>%5 non-zero): non-zero median+MAD = gercek gurultu seviyesi
            float *nzv = malloc(nz * sizeof(float));
            size_t t = 0;
            for (size_t i = 0; i < N && t < nz; i += step)
                if (f->data[i] > bg) nzv[t++] = f->data[i];
            float nzmed = median_inplace(nzv, t);
            for (size_t i = 0; i < t; i++) nzv[i] = fabsf(nzv[i] - nzmed);
            float nzmad = median_inplace(nzv, t);
            free(nzv);

            sigma = 1.4826f * nzmad;
            bg    = nzmed;                 // arka plan = gurultu seviyesi
            thr   = nzmed + p.k * sigma;   // esik gurultunun uzeri, yildizin alti
        } else {
            // Temiz goruntu (az non-zero): dusuk esik zaten dogru, yildizlar ayrik
            thr = bg + p.k * sigma;        // ~bg, ayrik parlak yildizlar gecer
        }
    } else {
        // (2) Normal durum: klasik median + k*sigma
        thr = bg + p.k * sigma;
    }

    // 3) Butun matrisi tara: esigi gecen 1, kalan 0
    for (size_t i = 0; i < N; i++)
        mask[i] = (f->data[i] > thr) ? 1u : 0u;

    PreStats s = { bg, sigma, thr };
    return s;
}
