// Test icin: hareketli yildizlar (dinamik) + arka plan gurultusu uretir.
// Cikti: frames.bin (cok kareli float32) + ground_truth.csv (gercek konumlar)
#include <stdio.h>
#include <stdlib.h>
#include <math.h>

int main(int argc, char **argv) {
    int W = 512, H = 512, nframes = 30, nstars = 12;
    const char *out = (argc > 1) ? argv[1] : "frames.bin";
    const char *gt  = (argc > 2) ? argv[2] : "ground_truth.csv";

    FILE *fb = fopen(out, "wb");
    FILE *fg = fopen(gt, "w");
    fprintf(fg, "frame_id,star_x,star_y,star_id\n");

    float *img = malloc((size_t)W * H * sizeof(float));
    srand(42);

    float px[64], py[64], vx[64], vy[64], amp[64];
    for (int s = 0; s < nstars; s++) {
        px[s] = 50 + rand() % (W - 100);
        py[s] = 50 + rand() % (H - 100);
        vx[s] = ((rand() % 200) - 100) / 100.0f;  // -1..1 px/kare
        vy[s] = ((rand() % 200) - 100) / 100.0f;
        amp[s] = 300 + rand() % 500;
    }

    float sigma = 1.5f;
    for (int fr = 0; fr < nframes; fr++) {
        for (int i = 0; i < W * H; i++)
            img[i] = 5.0f + ((rand() % 1000) / 1000.0f - 0.5f) * 4.0f; // ~5 +/- 2

        for (int s = 0; s < nstars; s++) {
            float cx = px[s] + vx[s] * fr;
            float cy = py[s] + vy[s] * fr;
            fprintf(fg, "%d,%.4f,%.4f,%d\n", fr, cx, cy, s);
            int r = 6;
            for (int dy = -r; dy <= r; dy++)
                for (int dx = -r; dx <= r; dx++) {
                    int x = (int)cx + dx, y = (int)cy + dy;
                    if (x < 0 || x >= W || y < 0 || y >= H) continue;
                    float ddx = x - cx, ddy = y - cy;
                    img[y*W+x] += amp[s] * expf(-(ddx*ddx+ddy*ddy)/(2*sigma*sigma));
                }
        }
        fwrite(img, sizeof(float), (size_t)W * H, fb);
    }
    fclose(fb); fclose(fg); free(img);
    printf("Uretildi: %d kare, %dx%d, %d yildiz -> %s\n", nframes, W, H, nstars, out);
    return 0;
}
