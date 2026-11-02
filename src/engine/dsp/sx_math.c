/* sx_math.c: deterministic elementary functions (see sx_math.h). No libm.
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "sx_math.h"

#include <stdint.h>
#include <string.h>

/* ln(2)^k / k!, k = 0..11: the Taylor series of 2^r = e^(r ln 2), fixed. */
static const double exp2_c[12] = {
    1.0,
    0.6931471805599453,
    0.2402265069591007,
    0.055504108664821576,
    0.009618129107628477,
    0.0013333558146428441,
    0.00015403530393381606,
    1.5252733804059838e-05,
    1.3215486790144305e-06,
    1.0178086009239696e-07,
    7.054911620801121e-09,
    4.44553827187081e-10,
};

/* (-1)^k / (2k+1)!, k = 0..9: sin x = x (c0 + c1 x^2 + ...), fixed. */
static const double sin_c[10] = {
    1.0,
    -0.16666666666666666,
    0.008333333333333333,
    -0.0001984126984126984,
    2.7557319223985893e-06,
    -2.505210838544172e-08,
    1.6059043836821613e-10,
    -7.647163731819816e-13,
    2.8114572543455206e-15,
    -8.22063524662433e-18,
};

static int64_t nearest(double x)
{
    return (int64_t)(x >= 0.0 ? x + 0.5 : x - 0.5);
}

double sx_exp2(double x)
{
    if (!(x == x)) /* NaN in: NaN out (the supervisor catches it) */
        return x;
    if (x > 1000.0)
        x = 1000.0;
    if (x < -1000.0)
        x = -1000.0;
    int64_t n = nearest(x);
    double r = x - (double)n; /* [-0.5, 0.5] */
    double p = exp2_c[11];
    for (int k = 10; k >= 0; k--)
        p = p * r + exp2_c[k];
    if (n < -1022)
        n = -1022; /* far below anything audible; avoids subnormal construction */
    uint64_t bits = (uint64_t)(n + 1023) << 52;
    double scale;
    memcpy(&scale, &bits, sizeof scale);
    return p * scale;
}

double sx_sin_cycles(double p)
{
    double q = p - (double)nearest(p); /* [-0.5, 0.5] cycles */
    if (q > 0.25)
        q = 0.5 - q;
    else if (q < -0.25)
        q = -0.5 - q;
    double x = q * 6.283185307179586; /* [-pi/2, pi/2] */
    double x2 = x * x;
    double s = sin_c[9];
    for (int k = 8; k >= 0; k--)
        s = s * x2 + sin_c[k];
    return s * x;
}
