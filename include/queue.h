#ifndef QUEUE_H
#define QUEUE_H
#include <pthread.h>
#include <stddef.h>

// Genel amaçlı, sınırlı (bounded), bloklayan void* kuyruğu.
// Üretici/tüketici arasındaki tutkal: doluysa üretici bekler,
// boşsa tüketici bekler. "closed" olunca bekleyenler uyanır.
typedef struct {
    void  **buf;
    size_t  cap, head, tail, size;
    int     closed;
    pthread_mutex_t m;
    pthread_cond_t  not_empty;
    pthread_cond_t  not_full;
} Queue;

void  queue_init(Queue *q, size_t cap);
void  queue_destroy(Queue *q);
int   queue_push(Queue *q, void *item); // 1=ok, 0=kapalı
void *queue_pop(Queue *q);              // NULL = kapalı ve boş
void *queue_trypop(Queue *q, int *closed_empty); // bloklamaz: bos ise NULL
void  queue_close(Queue *q);

#endif
