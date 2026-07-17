#ifndef CSV_LOGGER_H
#define CSV_LOGGER_H
#include <stdio.h>
#include <stdint.h>
#include "queue.h"

// Ayri thread'de calisir: result_q'dan ResultBatch ceker, CSV'ye yazar.
// Disk I/O'yu capture'dan ayirir -> capture yavaslamaz.
typedef struct {
    FILE    *fp;
    Queue   *in;          // ResultBatch* kuyrugu
    uint64_t expected_id; // frame surekliligi kontrolu
    uint64_t dropped;     // atlanan kare sayisi (id bosluklari)
} CsvLogger;

int   csv_logger_open(CsvLogger *lg, const char *path, Queue *in);
void *csv_logger_thread(void *arg);  // pthread giris noktasi
void  csv_logger_close(CsvLogger *lg);

#endif
