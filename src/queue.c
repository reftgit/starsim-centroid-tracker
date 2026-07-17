#include "queue.h"
#include <stdlib.h>

void queue_init(Queue *q, size_t cap) {
    q->buf = malloc(cap * sizeof(void*));
    q->cap = cap; q->head = q->tail = q->size = 0; q->closed = 0;
    pthread_mutex_init(&q->m, NULL);
    pthread_cond_init(&q->not_empty, NULL);
    pthread_cond_init(&q->not_full, NULL);
}

void queue_destroy(Queue *q) {
    free(q->buf);
    pthread_mutex_destroy(&q->m);
    pthread_cond_destroy(&q->not_empty);
    pthread_cond_destroy(&q->not_full);
}

int queue_push(Queue *q, void *item) {
    pthread_mutex_lock(&q->m);
    while (q->size == q->cap && !q->closed)
        pthread_cond_wait(&q->not_full, &q->m);     // dolu -> bekle
    if (q->closed) { pthread_mutex_unlock(&q->m); return 0; }
    q->buf[q->tail] = item;
    q->tail = (q->tail + 1) % q->cap;
    q->size++;
    pthread_cond_signal(&q->not_empty);
    pthread_mutex_unlock(&q->m);
    return 1;
}

void *queue_pop(Queue *q) {
    pthread_mutex_lock(&q->m);
    while (q->size == 0 && !q->closed)
        pthread_cond_wait(&q->not_empty, &q->m);    // boş -> bekle
    if (q->size == 0 && q->closed) {                // kapalı ve boş -> bitti
        pthread_mutex_unlock(&q->m);
        return NULL;
    }
    void *item = q->buf[q->head];
    q->head = (q->head + 1) % q->cap;
    q->size--;
    pthread_cond_signal(&q->not_full);
    pthread_mutex_unlock(&q->m);
    return item;
}


void *queue_trypop(Queue *q, int *closed_empty) {
    pthread_mutex_lock(&q->m);
    if (q->size == 0) {                       // bos -> hemen don
        if (closed_empty) *closed_empty = q->closed ? 1 : 0;
        pthread_mutex_unlock(&q->m);
        return NULL;
    }
    void *item = q->buf[q->head];
    q->head = (q->head + 1) % q->cap;
    q->size--;
    if (closed_empty) *closed_empty = 0;
    pthread_cond_signal(&q->not_full);
    pthread_mutex_unlock(&q->m);
    return item;
}

void queue_close(Queue *q) {
    pthread_mutex_lock(&q->m);
    q->closed = 1;
    pthread_cond_broadcast(&q->not_empty);
    pthread_cond_broadcast(&q->not_full);
    pthread_mutex_unlock(&q->m);
}
