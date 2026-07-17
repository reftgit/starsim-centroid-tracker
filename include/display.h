#ifndef DISPLAY_H
#define DISPLAY_H

typedef struct {
    int   width, height;
    unsigned char *gray;
    int   count;
    float *cx, *cy;
} DisplayItem;

void display_item_free(DisplayItem *it);

typedef struct DisplayCtx DisplayCtx;

DisplayCtx *display_create(int width, int height, int win_size, int fps);
// Bir kareyi ciz + isaretle, fps'e gore beklerken olaylari pompala.
// 1=devam, 0=kullanici pencereyi/ESC ile kapatti.
int  display_show(DisplayCtx *d, const DisplayItem *it);
// Sadece olaylari pompala (kare beklerken pencere yanit versin). 1=devam, 0=kapat.
int  display_pump(DisplayCtx *d);
void display_destroy(DisplayCtx *d);

#endif
