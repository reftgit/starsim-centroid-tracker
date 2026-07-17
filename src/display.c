#include "display.h"
#include <SDL2/SDL.h>
#include <locale.h>
#include <stdlib.h>

struct DisplayCtx {
    SDL_Window   *win;
    SDL_Renderer *ren;
    SDL_Texture  *tex;
    unsigned char *rgb;
    int width, height, win_w, win_h, fps;
    // --- zoom/pan viewport (goruntu-piksel cinsinden gorunur bolge) ---
    double view_x, view_y;   // gorunur bolgenin sol-ust kosesi (goruntu pikseli)
    double view_w, view_h;   // gorunur bolgenin genisligi/yuksekligi (goruntu pikseli)
    double zoom;             // 1.0 = tam kare; >1 yakinlastirilmis
};

void display_item_free(DisplayItem *it) {
    if (!it) return;
    free(it->gray); free(it->cx); free(it->cy); free(it);
}

// view_w/h ve view_x/y'yi gecerli sinirlar icine kelepceler.
static void clamp_view(DisplayCtx *d) {
    if (d->zoom < 1.0) d->zoom = 1.0;
    // maksimum zoom: gorunur bolge en az ~8 piksel kalsin
    double min_w = 8.0, min_h = 8.0;
    if (d->view_w < min_w) d->view_w = min_w;
    if (d->view_h < min_h) d->view_h = min_h;
    if (d->view_w > d->width)  d->view_w = d->width;
    if (d->view_h > d->height) d->view_h = d->height;
    if (d->view_x < 0) d->view_x = 0;
    if (d->view_y < 0) d->view_y = 0;
    if (d->view_x + d->view_w > d->width)  d->view_x = d->width  - d->view_w;
    if (d->view_y + d->view_h > d->height) d->view_y = d->height - d->view_h;
}

// Olaylari isle; kapatma istegi varsa 0 don. Fare tekerlegi = zoom, sag-tik surukle = pan.
static int pump_once(DisplayCtx *d) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_QUIT) return 0;
        if (e.type == SDL_KEYDOWN) {
            SDL_Keycode k = e.key.keysym.sym;
            if (k == SDLK_ESCAPE) return 0;
            // '0' ya da 'r' = zoom sifirla (tam kareye don)
            if (k == SDLK_0 || k == SDLK_r) {
                d->zoom = 1.0;
                d->view_x = 0; d->view_y = 0;
                d->view_w = d->width; d->view_h = d->height;
            }
        }
        if (e.type == SDL_MOUSEWHEEL) {
            // Fare konumundaki goruntu-pikselini sabit tutarak yakinlas/uzaklas.
            int mx, my; SDL_GetMouseState(&mx, &my);
            // pencere -> goruntu piksel donusumu (mevcut viewport uzerinden)
            double gx = d->view_x + (double)mx / d->win_w * d->view_w;
            double gy = d->view_y + (double)my / d->win_h * d->view_h;
            double factor = (e.wheel.y > 0) ? (1.0 / 1.2) : 1.2; // yukari=yakinlas
            double new_w = d->view_w * factor;
            double new_h = d->view_h * factor;
            // fare altindaki nokta ayni ekran orani uzerinde kalsin
            d->view_x = gx - (double)mx / d->win_w * new_w;
            d->view_y = gy - (double)my / d->win_h * new_h;
            d->view_w = new_w;
            d->view_h = new_h;
            d->zoom = (double)d->width / d->view_w;
            clamp_view(d);
        }
        // sol tus basili surukleme = pan (kaydirma)
        if (e.type == SDL_MOUSEMOTION && (e.motion.state & SDL_BUTTON_LMASK)) {
            d->view_x -= (double)e.motion.xrel / d->win_w * d->view_w;
            d->view_y -= (double)e.motion.yrel / d->win_h * d->view_h;
            clamp_view(d);
        }
    }
    return 1;
}

DisplayCtx *display_create(int width, int height, int win_size, int fps) {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) return NULL;
    /* SDL/X11 acilisi bazi sistemlerde LC_NUMERIC'i yerel dile cevirebiliyor
       (Turkce masaustunde ondalik ayraci virgul olur, CSV/printf bozulur).
       Sigorta: sayisal locale'i C'ye sabitle. */
    setlocale(LC_NUMERIC, "C");
    DisplayCtx *d = calloc(1, sizeof(DisplayCtx));
    d->width = width; d->height = height; d->fps = fps < 1 ? 1 : fps;
    if (width >= height) { d->win_w = win_size; d->win_h = (int)((long)win_size*height/width); }
    else                 { d->win_h = win_size; d->win_w = (int)((long)win_size*width/height); }
    d->win = SDL_CreateWindow("Yildiz Tracker - centroidler",
                SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
                d->win_w, d->win_h, SDL_WINDOW_SHOWN);
    d->ren = SDL_CreateRenderer(d->win, -1, SDL_RENDERER_ACCELERATED);
    d->tex = SDL_CreateTexture(d->ren, SDL_PIXELFORMAT_RGB24,
                SDL_TEXTUREACCESS_STREAMING, width, height);
    d->rgb = malloc((size_t)width * height * 3);
    // viewport basta tam kare
    d->view_x = 0; d->view_y = 0;
    d->view_w = width; d->view_h = height;
    d->zoom = 1.0;
    return d;
}

int display_pump(DisplayCtx *d) { return pump_once(d); }

int display_show(DisplayCtx *d, const DisplayItem *it) {
    int N = d->width * d->height;
    for (int i = 0; i < N; i++) {
        unsigned char g = it->gray[i];
        d->rgb[3*i] = g; d->rgb[3*i+1] = g; d->rgb[3*i+2] = g;
    }
    SDL_UpdateTexture(d->tex, NULL, d->rgb, d->width * 3);
    SDL_RenderClear(d->ren);

    // Sadece gorunur bolgeyi (viewport) tum pencereye yay -> zoom etkisi
    SDL_Rect src;
    src.x = (int)(d->view_x + 0.5);
    src.y = (int)(d->view_y + 0.5);
    src.w = (int)(d->view_w + 0.5);
    src.h = (int)(d->view_h + 0.5);
    if (src.w < 1) src.w = 1;
    if (src.h < 1) src.h = 1;
    SDL_RenderCopy(d->ren, d->tex, &src, NULL);

    SDL_SetRenderDrawColor(d->ren, 255, 0, 0, 255);
    // goruntu-piksel -> pencere donusumu artik viewport uzerinden
    double sx = (double)d->win_w / d->view_w;
    double sy = (double)d->win_h / d->view_h;
    for (int k = 0; k < it->count; k++) {
        // viewport disindaki centroidleri atla
        double vx = it->cx[k] - d->view_x;
        double vy = it->cy[k] - d->view_y;
        if (vx < 0 || vy < 0 || vx > d->view_w || vy > d->view_h) continue;
        int X = (int)(vx * sx), Y = (int)(vy * sy), r = 4;
        SDL_RenderDrawLine(d->ren, X-r, Y, X+r, Y);
        SDL_RenderDrawLine(d->ren, X, Y-r, X, Y+r);
    }
    SDL_RenderPresent(d->ren);

    // fps'e gore beklerken pencereyi YANITLI tut (olaylari pompala)
    Uint32 target = 1000 / d->fps, start = SDL_GetTicks();
    while (SDL_GetTicks() - start < target) {
        if (!pump_once(d)) return 0;
        SDL_Delay(2);
    }
    return 1;
}

void display_destroy(DisplayCtx *d) {
    if (!d) return;
    if (d->tex) SDL_DestroyTexture(d->tex);
    if (d->ren) SDL_DestroyRenderer(d->ren);
    if (d->win) SDL_DestroyWindow(d->win);
    free(d->rgb);
    SDL_Quit();
    free(d);
}
