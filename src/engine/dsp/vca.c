/* vca.c: the VCA with its 0.5 ms cv declick (VS-10; see vca.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "vca.h"

#include "sx_math.h"

void sx_vca_init(sx_vca *v, double fs)
{
    if (!(fs > 0.0))
        fs = 48000.0;
    /* exp(-1 / (tau fs)) = 2^(-1 / (tau fs ln 2)) */
    v->c = sx_exp2(-1.0 / (SX_VCA_DECLICK_S * fs) / 0.69314718055994531);
    v->expo = 0;
    sx_vca_reset(v);
}

void sx_vca_reset(sx_vca *v)
{
    v->cv = 0.0;
}

void sx_vca_render(sx_vca *v, uint32_t n, const float *in, const float *cv, float *out)
{
    double s = v->cv;
    for (uint32_t i = 0; i < n; i++) {
        double target = cv ? (double)cv[i] : 0.0;
        s = target + (s - target) * v->c;
        double g = v->expo ? (sx_exp2(s) - 1.0) / 1023.0 : s / 10.0;
        if (!(g > 0.0))
            g = 0.0;
        if (g > 1.0)
            g = 1.0;
        out[i] = (float)((double)in[i] * g);
    }
    v->cv = s;
}
