#include "csv_logger.h"
#include "types.h"
#include <stdlib.h>

int csv_logger_open(CsvLogger *lg, const char *path, Queue *in) {
    lg->fp = fopen(path, "w");
    if (!lg->fp) return 0;
    lg->in = in;
    lg->expected_id = 0;
    lg->dropped = 0;
    fprintf(lg->fp, "frame_id,timestamp,star_id,cx,cy,flux,npix\n");
    return 1;
}

void *csv_logger_thread(void *arg) {
    CsvLogger *lg = (CsvLogger*)arg;
    for (;;) {
        ResultBatch *b = (ResultBatch*)queue_pop(lg->in);
        if (!b) break;                       // kuyruk kapali ve bos -> bitti

        // Frame surekliligi: beklenen id ile gelen arasinda bosluk var mi?
        if (b->frame_id > lg->expected_id)
            lg->dropped += (b->frame_id - lg->expected_id);
        lg->expected_id = b->frame_id + 1;

        for (int i = 0; i < b->count; i++) {
            Centroid *c = &b->items[i];
            fprintf(lg->fp, "%llu,%.6f,%d,%.4f,%.4f,%.2f,%d\n",
                    (unsigned long long)b->frame_id, b->timestamp, i,
                    c->cx, c->cy, c->flux, c->npix);
        }
        free(b->items);
        free(b);
    }
    fflush(lg->fp);
    return NULL;
}

void csv_logger_close(CsvLogger *lg) {
    if (lg->fp) { fflush(lg->fp); fclose(lg->fp); }
    lg->fp = NULL;
}
