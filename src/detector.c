#include "detector.h"

int detector_run(const Frame *f, uint8_t *mask, DetParams p,
                 DetectedStar *stars, int max_stars, int *scratch) {
    int W = f->width, H = f->height;
    int found = 0;

    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            int idx = y * W + x;
            if (!mask[idx]) continue;

            // Yeni blob: BFS/DFS flood fill (acik yigin -> rekursiyon yok)
            int top = 0;
            scratch[top++] = idx;
            mask[idx] = 0;                 // ziyaret edildi

            long  sx = 0, sy = 0;
            double flux = 0.0;
            int   npix = 0;
            // Akı-ağırlıklı toplamlar: COM doğrudan blob piksellerinden.
            // Pencere YOK -> izole gürültü pikselleri giremez -> kaide YOK.
            double wsum = 0.0, wx = 0.0, wy = 0.0;

            while (top > 0) {
                int cur = scratch[--top];
                int cx = cur % W, cy = cur / W;
                npix++;
                sx += cx; sy += cy;
                float v = f->data[cur] - p.background;
                if (v > 0) {
                    flux += v;
                    wsum += v;
                    wx   += (double)v * cx;
                    wy   += (double)v * cy;
                }

                for (int dy = -1; dy <= 1; dy++) {
                    for (int dx = -1; dx <= 1; dx++) {
                        if (dx == 0 && dy == 0) continue;
                        int nx = cx + dx, ny = cy + dy;
                        if (nx < 0 || nx >= W || ny < 0 || ny >= H) continue;
                        int nidx = ny * W + nx;
                        if (mask[nidx]) {
                            mask[nidx] = 0;
                            scratch[top++] = nidx;
                        }
                    }
                }
            }

            // Filtre: cop elemesi
            if (npix < p.min_pixels || npix > p.max_pixels) continue;
            if (flux < p.min_flux) continue;
            if (found >= max_stars) return found;  // kapasite doldu

            // (int) cast'i TRUNCATE eder (asagi kirpar), yuvarlamaz.
            // Bu, COM penceresini sistematik olarak 0.5 px sol-alta kaydiriyordu.
            stars[found].x    = (int)(sx / npix + 0.5);   // truncate degil, YUVARLA
            stars[found].y    = (int)(sy / npix + 0.5);
            stars[found].cx   = (wsum > 0.0) ? (wx / wsum) : (double)stars[found].x;
            stars[found].cy   = (wsum > 0.0) ? (wy / wsum) : (double)stars[found].y;
            stars[found].npix = npix;
            stars[found].flux = (float)flux;
            found++;
        }
    }
    return found;
}
