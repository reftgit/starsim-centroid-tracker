#include "centroid.h"

Centroid centroid_com(const Frame *f, const DetectedStar *star,
                      int half, float background, float threshold) {
    int W = f->width, H = f->height;
    int x0 = star->x - half, x1 = star->x + half;
    int y0 = star->y - half, y1 = star->y + half;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 >= W) x1 = W - 1;
    if (y1 >= H) y1 = H - 1;

    double sumI = 0.0, sumX = 0.0, sumY = 0.0;
    int npix = 0;
    for (int y = y0; y <= y1; y++) {
        for (int x = x0; x <= x1; x++) {
            float v = f->data[y * W + x];
            // Piksel SECIMI esikle yapilir, bg ile DEGIL.
            // Eski hal (I <= 0) arka plan gurultusunun POZITIF yarisini kabul,
            // negatif yarisini reddediyordu -> pencereye yayilmis pozitif bir
            // "gurultu kaidesi" olusuyordu. O kaidenin agirlik merkezi pencere
            // ortasidir; COM'u oraya cekiyordu. Esikle secince kaide yok olur.
            if (v <= threshold) continue;
            double I = (double)v - background;
            if (I <= 0) continue;
            sumI += I;
            sumX += I * x;
            sumY += I * y;
            npix++;
        }
    }

    Centroid c;
    if (sumI > 0) { c.cx = sumX / sumI; c.cy = sumY / sumI; }
    else          { c.cx = star->x;     c.cy = star->y;     }
    c.flux = (float)sumI;
    c.npix = npix;
    return c;
}
