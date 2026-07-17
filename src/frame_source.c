#define _POSIX_C_SOURCE 200809L
#include "frame_source.h"
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

// Yol ".bin" ile bitiyor mu?
static int ends_with_bin(const char *path) {
    size_t n = strlen(path);
    return (n >= 4 && strcmp(path + n - 4, ".bin") == 0);
}

int frame_source_open(FrameSource *src, const char *path, int width, int height, int stamped) {
    src->width  = width;
    src->height = height;
    src->next_id = 0;
    src->u8buf = NULL;
    src->stamped = stamped;

    if (ends_with_bin(path)) {
        // --- HAM .bin MODU (ffmpeg gerekmez) ---
        src->is_video = 0;
        src->fp = fopen(path, "rb");
        if (!src->fp) return 0;
    } else {
        // --- VIDEO MODU (ffmpeg popen) ---
        src->is_video = 1;
        char cmd[1024];
        snprintf(cmd, sizeof(cmd),
            "ffmpeg -nostdin -v error -i \"%s\" "
            "-vf scale=%d:%d -pix_fmt gray -f rawvideo pipe:1 2>/dev/null",
            path, width, height);
        src->fp = popen(cmd, "r");
        if (!src->fp) return 0;
        src->u8buf = malloc((size_t)width * height);
        if (!src->u8buf) { pclose(src->fp); src->fp = NULL; return 0; }
    }
    return 1;
}

int frame_source_read(FrameSource *src, Frame *out) {
    size_t N = (size_t)src->width * src->height;
    uint64_t stamp_id = 0;

    if (src->stamped) {
        // Her kareden ONCE 8 bayt kare-id damgasi (little-endian uint64).
        // FIFO'da kare dusse bile bu id ile ground truth'a birebir eslesir.
        if (fread(&stamp_id, sizeof(uint64_t), 1, src->fp) != 1) return 0;  // EOF
    }

    if (src->is_video) {
        // video: gray8 oku -> float'a cevir
        size_t got = fread(src->u8buf, 1, N, src->fp);
        if (got != N) return 0;
        for (size_t i = 0; i < N; i++)
            out->data[i] = (float)src->u8buf[i];
    } else {
        // .bin: dogrudan float32 oku
        size_t got = fread(out->data, sizeof(float), N, src->fp);
        if (got != N) return 0;
    }

    out->frame_id  = src->stamped ? stamp_id : src->next_id++;
    out->timestamp = now_sec();
    out->width  = src->width;
    out->height = src->height;
    return 1;
}

void frame_source_close(FrameSource *src) {
    if (src->fp) {
        if (src->is_video) pclose(src->fp);   // popen -> pclose
        else               fclose(src->fp);   // fopen -> fclose
    }
    if (src->u8buf) free(src->u8buf);
    src->fp = NULL;
    src->u8buf = NULL;
}
