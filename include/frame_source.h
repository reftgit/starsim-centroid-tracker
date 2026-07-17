#ifndef FRAME_SOURCE_H
#define FRAME_SOURCE_H
#include <stdio.h>
#include "types.h"

// Girdi kaynagini uzantiya gore otomatik secer:
//   *.bin            -> dogrudan fread (ham float32, ffmpeg GEREKMEZ)
//   *.mp4/.avi/...   -> ffmpeg alt sureci (popen) ile gray8 akisi
typedef struct {
    FILE          *fp;       // .bin icin fopen, video icin popen
    int            width, height;
    uint64_t       next_id;
    int            is_video; // 1 = ffmpeg pipe, 0 = ham .bin
    int            stamped;  // 1 = her kareden once 8 bayt kare-id damgasi var (FIFO koprusu)
    unsigned char *u8buf;    // sadece video modunda kullanilir
} FrameSource;

int  frame_source_open (FrameSource *src, const char *path, int width, int height, int stamped);
int  frame_source_read (FrameSource *src, Frame *out); // 1=ok, 0=EOF
void frame_source_close(FrameSource *src);

#endif
