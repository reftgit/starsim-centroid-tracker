#ifndef CENTROID_H
#define CENTROID_H
#include "types.h"

// star etrafinda (2*half+1)x(2*half+1) pencerede, bg cikarilmis COM.
// Iterasyonsuz, deterministik, sinirli sure -> "frame kacirmama" garantisi.


// threshold: piksel SECIMI icin (gurultu kaidesini disarida birakir)
// background: agirlik hesabinda cikarilan taban
Centroid centroid_com(const Frame *f, const DetectedStar *star,
                      int half, float background, float threshold);

#endif
