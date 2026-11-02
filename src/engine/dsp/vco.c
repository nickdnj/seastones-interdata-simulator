/* vco.c: the band-limited VCO (VS-30, ADR-010; see vco.h).
 *
 * Each output is its naive waveform plus a 32-sample ring of kernel residuals. A discontinuity
 * of height h at d samples before the current sample (0 <= d <= 1) adds
 * h x minblep[k](k + d) to the next 32 ring cells; a slope change s adds s x minblamp[k](k + d)
 * and moves the output's tail offset by s x sx_minblamp_tail. The tail is kept as
 * tail x (current slope per sample), which is the stationary value: the band-limited ramp runs
 * a constant (the kernel's centroid) behind the naive one. Overlapping edges simply add.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "vco.h"

#include "sx_math.h"

static void set_inc(sx_vco *v, double fm_hz)
{
    double f = v->f0 * sx_exp2(v->volts + v->tune) + fm_hz;
    if (f > SX_VCO_FMAX_HZ)
        f = SX_VCO_FMAX_HZ;
    if (!(f > 0.0)) /* also NaN */
        f = 0.0;
    v->inc = f / v->fs;
}

/* naive slopes per sample */
static double tri_slope(const sx_vco *v)
{
    return v->phase < 0.5 ? 4.0 * v->inc : -4.0 * v->inc;
}

static void sync_tails(sx_vco *v)
{
    v->tail[SX_VCO_TRI] = (double)sx_minblamp_tail * tri_slope(v);
    v->tail[SX_VCO_SAW] = (double)sx_minblamp_tail * 2.0 * v->inc;
    v->tail[SX_VCO_PULSE] = 0.0;
}

void sx_vco_reset(sx_vco *v)
{
    v->phase = 0.0;
    v->pulse_high = 1;
    v->pos = 0;
    for (int r = 0; r < SX_VCO_NRING; r++)
        for (int k = 0; k < SX_BLEP_SPAN; k++)
            v->ring[r][k] = 0.0f;
    set_inc(v, 0.0);
    sync_tails(v);
}

void sx_vco_init(sx_vco *v, double fs)
{
    v->fs = fs > 0.0 ? fs : 48000.0;
    v->f0 = SX_VCO_F0_HZ;
    v->tune = 0.0;
    v->volts = 0.0;
    v->fm_hz_per_v = 0.0;
    sx_vco_reset(v);
}

void sx_vco_set_tune(sx_vco *v, double volts)
{
    v->tune = volts;
    sx_vco_set_pitch(v, v->volts);
}

/* Add a residual of `amount` at d samples (0..1) before the current sample, from table `t`. */
static void add_residual(float *ring, uint32_t pos, const float t[SX_BLEP_ROWS][SX_BLEP_COLS],
                         double amount, double d)
{
    double u = d * SX_BLEP_PHASES;
    int j = (int)u;
    if (j >= SX_BLEP_PHASES)
        j = SX_BLEP_PHASES - 1;
    if (j < 0)
        j = 0;
    float fr = (float)(u - (double)j);
    float a = (float)amount;
    for (uint32_t k = 0; k < SX_BLEP_SPAN; k++) {
        float r = t[k][j] + (t[k][j + 1] - t[k][j]) * fr;
        ring[(pos + k) & (SX_BLEP_SPAN - 1)] += a * r;
    }
}

void sx_vco_set_pitch(sx_vco *v, double volts)
{
    double old = v->inc;
    v->volts = volts;
    set_inc(v, 0.0);
    double dinc = v->inc - old;
    if (dinc == 0.0)
        return;
    /* The slope changes at the boundary before the next sample: one sample back (d = 1). */
    double s_tri = v->phase < 0.5 ? 4.0 * dinc : -4.0 * dinc;
    add_residual(v->ring[SX_VCO_TRI], v->pos, sx_minblamp, s_tri, 1.0);
    add_residual(v->ring[SX_VCO_SAW], v->pos, sx_minblamp, 2.0 * dinc, 1.0);
    sync_tails(v);
}

static float out_of(sx_vco *v, int r, double naive)
{
    float *cell = &v->ring[r][v->pos];
    float y = (float)(naive + v->tail[r]) + *cell;
    *cell = 0.0f;
    return y;
}

void sx_vco_render(sx_vco *v, uint32_t n, const float *pw, const float *fm, float *sine, float *tri,
                   float *saw, float *pulse)
{
    double base_inc = v->inc;
    for (uint32_t i = 0; i < n; i++) {
        if (fm) { /* linear FM, per sample; its own aliasing is not the VCO's (ADR-010) */
            set_inc(v, v->fm_hz_per_v * (double)fm[i]);
            sync_tails(v);
        }
        double inc = v->inc;
        double old = v->phase;
        double p = old + inc;
        int wrapped = p >= 1.0;
        if (wrapped)
            p -= 1.0;
        double w = pw ? (double)pw[i] : 0.5;
        if (!(w >= 0.02))
            w = 0.02;
        if (w > 0.98)
            w = 0.98;
        double d_wrap = wrapped && inc > 0.0 ? p / inc : 0.0;

        if (saw && wrapped)
            add_residual(v->ring[SX_VCO_SAW], v->pos, sx_minblep, -2.0, d_wrap);
        if (pulse && inc > 0.0) {
            if (wrapped) {
                if (v->pulse_high && old < w) { /* fell before the wrap */
                    add_residual(v->ring[SX_VCO_PULSE], v->pos, sx_minblep, -2.0,
                                 (p + 1.0 - w) / inc);
                    v->pulse_high = 0;
                }
                if (!v->pulse_high) {
                    add_residual(v->ring[SX_VCO_PULSE], v->pos, sx_minblep, 2.0, d_wrap);
                    v->pulse_high = 1;
                }
            }
            if (v->pulse_high && p >= w && (wrapped || old < w)) {
                add_residual(v->ring[SX_VCO_PULSE], v->pos, sx_minblep, -2.0, (p - w) / inc);
                v->pulse_high = 0;
            }
        }
        if (tri && inc > 0.0) {
            if (wrapped) /* the bottom corner: slope -4 inc to +4 inc */
                add_residual(v->ring[SX_VCO_TRI], v->pos, sx_minblamp, 8.0 * inc, d_wrap);
            else if (old < 0.5 && p >= 0.5) /* the top corner */
                add_residual(v->ring[SX_VCO_TRI], v->pos, sx_minblamp, -8.0 * inc, (p - 0.5) / inc);
        }
        v->phase = p;
        if (tri)
            v->tail[SX_VCO_TRI] = (double)sx_minblamp_tail * tri_slope(v);

        if (sine)
            sine[i] = (float)sx_sin_cycles(p);
        if (tri)
            tri[i] = out_of(v, SX_VCO_TRI, p < 0.5 ? 4.0 * p - 1.0 : 3.0 - 4.0 * p);
        if (saw)
            saw[i] = out_of(v, SX_VCO_SAW, 2.0 * p - 1.0);
        if (pulse)
            pulse[i] = out_of(v, SX_VCO_PULSE, v->pulse_high ? 1.0 : -1.0);
        v->pos = (v->pos + 1u) & (SX_BLEP_SPAN - 1u);
    }
    if (fm) {
        v->inc = base_inc; /* back to the pitch input alone */
        sync_tails(v);
    }
}
