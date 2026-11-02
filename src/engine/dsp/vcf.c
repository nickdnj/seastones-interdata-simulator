/* vcf.c: the ladder low-pass and the state-variable high- and band-pass (PM-02; see vcf.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "vcf.h"

#include "sx_math.h"

#define TINY 1e-30

/* the halfband's odd-phase taps: sinc(k + 1/2), Hann-windowed over +/-4.5, summing to 1/2 */
static const double HB[4] = {0.617130865024282, -0.15907955168026522, 0.05258227097076596,
                             -0.010633584314782795};

double sx_sat(double x)
{
    if (x >= 3.0)
        return 1.0;
    if (x <= -3.0)
        return -1.0;
    double x2 = x * x;
    return x * (27.0 + x2) / (27.0 + 9.0 * x2);
}

static double flush(double v)
{
    return (v < TINY && v > -TINY) ? 0.0 : v;
}

double sx_vcf_hz(double v)
{
    if (!(v == v))
        v = 0.0;
    if (v > 14.0)
        v = 14.0;
    if (v < -4.0)
        v = -4.0;
    double f = SX_VCF_F0_HZ * sx_exp2(v);
    if (f < SX_VCF_FMIN_HZ)
        f = SX_VCF_FMIN_HZ;
    if (f > SX_VCF_FMAX_HZ)
        f = SX_VCF_FMAX_HZ;
    return f;
}

void sx_vcf_set(sx_vcf *f, double volts, double res)
{
    if (!(res >= 0.0))
        res = 0.0;
    if (res > 1.0)
        res = 1.0;
    f->volts = volts;
    f->res = res;
    double p = sx_vcf_hz(volts) / f->fs2 / 2.0; /* pi fc / fs2, in cycles: tan = sin / cos */
    f->g = sx_sin_cycles(p) / sx_sin_cycles(p + 0.25);
    f->G = f->g / (1.0 + f->g);
    f->k = SX_VCF_KMAX * res;
    f->R2 = 2.0 - 1.9 * res;
    f->h = 1.0 / (1.0 + f->R2 * f->g + f->g * f->g);
}

void sx_vcf_reset(sx_vcf *f)
{
    for (int i = 0; i < 4; i++)
        f->s[i] = 0.0;
    f->s1 = f->s2 = 0.0;
    for (uint32_t i = 0; i < SX_VCF_HB; i++) {
        f->xh[i] = 0.0;
        for (int o = 0; o < 3; o++)
            f->yh[o][0][i] = f->yh[o][1][i] = 0.0;
    }
    f->pos = 0;
}

void sx_vcf_init(sx_vcf *f, double fs)
{
    f->fs2 = 2.0 * (fs > 0.0 ? fs : 48000.0);
    f->drive = 1.0;
    sx_vcf_reset(f);
    sx_vcf_set(f, 5.0, 0.0);
}

/* one oversampled step of the ladder: returns y4 */
static double ladder(sx_vcf *f, double x)
{
    double G = f->G, one = 1.0 - G;
    double S = one * (f->s[3] + G * (f->s[2] + G * (f->s[1] + G * f->s[0])));
    double G4 = G * G * G * G;
    double y4 = (G4 * x + S) / (1.0 + f->k * G4); /* the linear solution of the feedback loop */
    double u = sx_sat(f->drive * x - f->k * y4);  /* the input stage saturates */
    for (int i = 0; i < 4; i++) {
        double v = G * (u - f->s[i]);
        double y = v + f->s[i];
        f->s[i] = flush(y + v);
        u = y;
    }
    return u;
}

static void svf(sx_vcf *f, double x, double *hp, double *bp)
{
    double g = f->g;
    double h = (x - (f->R2 + g) * f->s1 - f->s2) * f->h;
    double b = g * h + f->s1;
    f->s1 = flush(g * h + b);
    double l = g * b + f->s2;
    f->s2 = flush(g * b + l);
    *hp = h;
    *bp = b;
}

/* the value at history age a (0 = newest) of ring r */
#define AGE(r, a) (r)[(f->pos - (a)) & (SX_VCF_HB - 1u)]

void sx_vcf_tick(sx_vcf *f, double x, int want_lp, int want_svf, float *lp, float *hp, float *bp)
{
    if (!(x - x == 0.0)) /* NaN or Inf in: the filter forgets it */
        x = 0.0;
    f->pos = (f->pos + 1u) & (SX_VCF_HB - 1u);
    f->xh[f->pos] = x;
    /* 2x up: the even phase is x[n-4]; the odd phase, half a sample later, is interpolated */
    double xe = AGE(f->xh, 4u), xo = 0.0;
    for (uint32_t k = 0; k < 4u; k++)
        xo += HB[k] * (AGE(f->xh, 4u + k) + AGE(f->xh, 3u - k));
    double y[3][2] = {{0.0, 0.0}, {0.0, 0.0}, {0.0, 0.0}};
    if (want_lp) {
        y[0][0] = ladder(f, xe);
        y[0][1] = ladder(f, xo);
    }
    if (want_svf) {
        svf(f, xe, &y[1][0], &y[2][0]);
        svf(f, xo, &y[1][1], &y[2][1]);
    }
    /* 2x down: the halfband again, centred on the even sample three steps back */
    float *out[3] = {lp, hp, bp};
    for (int o = 0; o < 3; o++) {
        if ((o == 0 && !want_lp) || (o > 0 && !want_svf))
            continue;
        f->yh[o][0][f->pos] = y[o][0];
        f->yh[o][1][f->pos] = y[o][1];
        double z = 0.0;
        for (uint32_t k = 0; k < 4u; k++)
            z += HB[k] * (AGE(f->yh[o][1], 4u + k) + AGE(f->yh[o][1], 3u - k));
        *out[o] = (float)(0.5 * (AGE(f->yh[o][0], 3u) + z)); /* the halfband / 2: unit gain */
    }
}

void sx_vcf_render(sx_vcf *f, uint32_t n, const float *in, float *lp, float *hp, float *bp)
{
    float dl, dh, db;
    for (uint32_t i = 0; i < n; i++) {
        sx_vcf_tick(f, (double)in[i], lp != 0, hp != 0 || bp != 0, lp ? lp + i : &dl,
                    hp ? hp + i : &dh, bp ? bp + i : &db);
    }
}
