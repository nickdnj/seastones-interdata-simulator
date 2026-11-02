/* mods.c: LFO, noise, slew and echo (PM-03, PM-04; see mods.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "mods.h"

#include <stddef.h>

#include "sx_math.h"
#include "vcf.h"

#define LN2 0.69314718055994531
#define TINY 1e-30

uint32_t sx_xorshift32(uint32_t *s)
{
    uint32_t x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

static double uniform(uint32_t *s) /* [-1, 1) */
{
    return (double)sx_xorshift32(s) / 2147483648.0 - 1.0;
}

double sx_onepole_coeff(double tau, double fs)
{
    if (!(tau > 0.0) || !(fs > 0.0))
        return 0.0;
    return sx_exp2(-1.0 / (tau * fs) / LN2);
}

/* --- LFO ---------------------------------------------------------------------------------- */

void sx_lfo_reset(sx_lfo *l)
{
    l->phase = 0.0;
    l->sh = 0.0;
}

void sx_lfo_init(sx_lfo *l, double fs, uint32_t seed)
{
    l->fs = fs > 0.0 ? fs : 48000.0;
    l->rng = seed ? seed : 0x5EA5u;
    sx_lfo_reset(l);
}

void sx_lfo_render(sx_lfo *l, uint32_t n, const float *rate_v, double rate, float *sine, float *tri,
                   float *square, float *sh)
{
    double last_v = 1e300, inc = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        double v = rate + (rate_v ? (double)rate_v[i] : 0.0);
        if (v != last_v) {
            last_v = v;
            if (!(v == v))
                v = 0.0;
            if (v > 8.0)
                v = 8.0;
            if (v < -10.0)
                v = -10.0;
            double f = sx_exp2(v);
            if (f > 200.0)
                f = 200.0;
            inc = f / l->fs;
        }
        double p = l->phase + inc;
        if (p >= 1.0) {
            p -= 1.0;
            l->sh = uniform(&l->rng); /* a new held value each cycle */
        }
        l->phase = p;
        if (sine)
            sine[i] = (float)sx_sin_cycles(p);
        if (tri)
            tri[i] = (float)(p < 0.5 ? 4.0 * p - 1.0 : 3.0 - 4.0 * p);
        if (square)
            square[i] = p < 0.5 ? 1.0f : -1.0f;
        if (sh)
            sh[i] = (float)l->sh;
    }
}

/* --- noise -------------------------------------------------------------------------------- */

void sx_noise_init(sx_noise *z, uint32_t seed)
{
    z->rng = seed ? seed : 0x1974u;
    z->b0 = z->b1 = z->b2 = 0.0;
}

void sx_noise_render(sx_noise *z, uint32_t n, float *white, float *pink)
{
    for (uint32_t i = 0; i < n; i++) {
        double w = uniform(&z->rng);
        if (white)
            white[i] = (float)w;
        if (pink) { /* Paul Kellet's economy pink filter, about -3 dB/oct from 10 Hz up */
            z->b0 = 0.99765 * z->b0 + w * 0.0990460;
            z->b1 = 0.96300 * z->b1 + w * 0.2965164;
            z->b2 = 0.57000 * z->b2 + w * 1.0526913;
            pink[i] = (float)((z->b0 + z->b1 + z->b2 + w * 0.1848) * 0.25);
        }
    }
}

/* --- slew --------------------------------------------------------------------------------- */

void sx_slew_init(sx_slew *s, double fs)
{
    s->fs = fs > 0.0 ? fs : 48000.0;
    s->y = 0.0;
    s->cr = s->cf = 0.0;
}

void sx_slew_set(sx_slew *s, double rise, double fall)
{
    s->cr = sx_onepole_coeff(rise, s->fs);
    s->cf = sx_onepole_coeff(fall, s->fs);
}

void sx_slew_reset(sx_slew *s, double y)
{
    s->y = y;
}

void sx_slew_render(sx_slew *s, uint32_t n, const float *in, float *out)
{
    double y = s->y;
    for (uint32_t i = 0; i < n; i++) {
        double x = (double)in[i];
        double c = x > y ? s->cr : s->cf;
        y = x + (y - x) * c;
        if (y < TINY && y > -TINY)
            y = 0.0;
        out[i] = (float)y;
    }
    s->y = y;
}

/* --- echo --------------------------------------------------------------------------------- */

void sx_echo_reset(sx_echo *e)
{
    for (uint32_t i = 0; i < SX_ECHO_LEN; i++)
        e->l[i] = e->r[i] = 0.0f;
    e->pos = 0;
    e->lp = 0.0;
}

void sx_echo_tone(sx_echo *e, double hz)
{
    if (!(hz > 20.0))
        hz = 20.0;
    if (hz > 16000.0)
        hz = 16000.0;
    e->lpc = sx_exp2(-6.283185307179586 * hz / e->fs / LN2);
}

void sx_echo_init(sx_echo *e, double fs, float *mem)
{
    e->fs = fs > 0.0 ? fs : 48000.0;
    e->l = mem;
    e->r = mem + SX_ECHO_LEN;
    sx_echo_tone(e, 4000.0);
    sx_echo_reset(e);
}

static double tap(const float *line, uint32_t pos, double d)
{
    uint32_t di = (uint32_t)d;
    double fr = d - (double)di;
    double a = (double)line[(pos - di) & (SX_ECHO_LEN - 1u)];
    double b = (double)line[(pos - di - 1u) & (SX_ECHO_LEN - 1u)];
    return a + (b - a) * fr;
}

void sx_echo_render(sx_echo *e, uint32_t n, const float *in, const float *time_v, double time_s,
                    double fb, double mix, float *l, float *r)
{
    if (!(fb >= 0.0))
        fb = 0.0;
    if (fb > 0.9)
        fb = 0.9;
    if (!(mix >= 0.0))
        mix = 0.0;
    if (mix > 1.0)
        mix = 1.0;
    double maxd = SX_ECHO_MAX_S * e->fs;
    for (uint32_t i = 0; i < n; i++) {
        double t = time_s * (time_v ? sx_exp2((double)time_v[i]) : 1.0);
        double d = t * e->fs;
        if (!(d >= 1.0))
            d = 1.0;
        if (d > maxd)
            d = maxd;
        double x = (double)in[i];
        if (!(x - x == 0.0))
            x = 0.0;
        double dl = tap(e->l, e->pos, d), dr = tap(e->r, e->pos, d);
        e->lp = dr + (e->lp - dr) * e->lpc; /* the feedback path darkens each time round */
        if (e->lp < TINY && e->lp > -TINY)
            e->lp = 0.0;
        e->pos = (e->pos + 1u) & (SX_ECHO_LEN - 1u);
        e->l[e->pos] = (float)sx_sat(x + fb * e->lp); /* left: the input and the feedback */
        e->r[e->pos] = (float)dl;                     /* right: what left sends on */
        if (l)
            l[i] = (float)(x * (1.0 - mix) + dl * mix);
        if (r)
            r[i] = (float)(x * (1.0 - mix) + dr * mix);
    }
}

/* --- reverb (FDN) ------------------------------------------------------------------------- */

static const double REV_BASE[SX_REV_LINES] = {1423.0, 1777.0, 2131.0, 2557.0};

void sx_rev_reset(sx_rev *r)
{
    for (uint32_t k = 0; k < SX_REV_LINES; k++) {
        for (uint32_t i = 0; i < SX_REV_LEN; i++)
            r->line[k][i] = 0.0f;
        r->lp[k] = 0.0;
    }
    r->pos = 0;
}

void sx_rev_set(sx_rev *r, double t60, double size, double tone)
{
    if (!(t60 >= 0.1))
        t60 = 0.1;
    if (t60 > 10.0)
        t60 = 10.0;
    if (!(size >= 0.5))
        size = 0.5;
    if (size > 1.5)
        size = 1.5;
    if (!(tone >= 500.0))
        tone = 500.0;
    if (tone > 16000.0)
        tone = 16000.0;
    r->t60 = t60;
    r->size = size;
    r->tone = tone;
    double scale = r->fs / 48000.0 * size;
    for (uint32_t k = 0; k < SX_REV_LINES; k++) {
        double L = REV_BASE[k] * scale;
        if (L > (double)(SX_REV_LEN - 2u))
            L = (double)(SX_REV_LEN - 2u);
        r->len[k] = (uint32_t)L;
        /* -60 dB in t60: g = 10^(-3 L / (t60 fs)) = 2^(-3 L log2(10) / (t60 fs)) */
        r->g[k] = sx_exp2(-3.0 * (double)r->len[k] * 3.3219280948873622 / (t60 * r->fs));
    }
    r->c = sx_exp2(-6.283185307179586 * tone / r->fs / LN2);
}

void sx_rev_init(sx_rev *r, double fs, float *mem)
{
    r->fs = fs > 0.0 ? fs : 48000.0;
    for (uint32_t k = 0; k < SX_REV_LINES; k++)
        r->line[k] = mem + (size_t)k * SX_REV_LEN;
    sx_rev_set(r, 2.0, 1.0, 6000.0);
    sx_rev_reset(r);
}

void sx_rev_render(sx_rev *r, uint32_t n, const float *in, double mix, float *l, float *rr)
{
    if (!(mix >= 0.0))
        mix = 0.0;
    if (mix > 1.0)
        mix = 1.0;
    const uint32_t M = SX_REV_LEN - 1u;
    for (uint32_t i = 0; i < n; i++) {
        double x = (double)in[i];
        if (!(x - x == 0.0))
            x = 0.0;
        double y[SX_REV_LINES];
        for (uint32_t k = 0; k < SX_REV_LINES; k++) {
            double v = (double)r->line[k][(r->pos - r->len[k]) & M];
            r->lp[k] = v + (r->lp[k] - v) * r->c; /* damping: the tail darkens */
            if (r->lp[k] < TINY && r->lp[k] > -TINY)
                r->lp[k] = 0.0;
            y[k] = r->lp[k] * r->g[k];
        }
        /* orthonormal Hadamard: H4 / 2 */
        double a = y[0] + y[1], b = y[0] - y[1], c = y[2] + y[3], d = y[2] - y[3];
        double f[SX_REV_LINES] = {0.5 * (a + c), 0.5 * (b + d), 0.5 * (a - c), 0.5 * (b - d)};
        r->pos = (r->pos + 1u) & M;
        for (uint32_t k = 0; k < SX_REV_LINES; k++)
            r->line[k][r->pos] = (float)(f[k] + 0.35 * x);
        double wl = y[0] + y[2], wr = y[1] + y[3];
        if (l)
            l[i] = (float)(x * (1.0 - mix) + wl * mix);
        if (rr)
            rr[i] = (float)(x * (1.0 - mix) + wr * mix);
    }
}
