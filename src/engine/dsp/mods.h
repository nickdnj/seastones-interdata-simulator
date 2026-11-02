/* mods.h: the small modules (PM-03, PM-04; ARCHITECTURE 6.2): LFO, noise, slew and echo.
 *
 *   lfo    rate 1 V/oct around 1 Hz (rate input + rate parameter), outputs sine, triangle,
 *          square and sample-and-hold, each +/-1 (the graph scales them by `level` volts). A
 *          control-rate source: its square and S&H are not band-limited, and are not meant to be
 *          heard directly.
 *   noise  white (uniform, deterministic xorshift32 seeded per module) and pink (Kellet's
 *          economy filter on the white), about +/-1
 *   slew   a one-pole lag with separate rise and fall times: the ONLY deliberate smoothing of a
 *          D/A step anywhere in the patch (NFR-2, DSP-18); time 0 passes the input through
 *   echo   our addition (PATCH-3): a ping-pong delay, left into right into left, with feedback
 *          through a one-pole low-pass (`tone`) and the fixed rational tanh, so it can never grow
 *          without bound; delay time per sample (fractional, linear interpolation)
 *
 * All real-time safe, no libm (sx_math). The echo's delay lines are caller-owned memory
 * (the graph builder allocates them off the audio thread).
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_MODS_H
#define SX_MODS_H

#include <stdint.h>

/* --- LFO --------------------------------------------------------------------------------- */

typedef struct sx_lfo {
    double fs, phase, sh;
    uint32_t rng;
} sx_lfo;

void sx_lfo_init(sx_lfo *l, double fs, uint32_t seed);
void sx_lfo_reset(sx_lfo *l);
/* [RT] rate_v per sample (NULL: 0 V) plus `rate` volts; f = 1 Hz x 2^V, clamped to 0.001-200 Hz */
void sx_lfo_render(sx_lfo *l, uint32_t n, const float *rate_v, double rate, float *sine, float *tri,
                   float *square, float *sh);

/* --- noise -------------------------------------------------------------------------------- */

typedef struct sx_noise {
    uint32_t rng;
    double b0, b1, b2;
} sx_noise;

void sx_noise_init(sx_noise *z, uint32_t seed);
void sx_noise_render(sx_noise *z, uint32_t n, float *white, float *pink); /* [RT] */

/* --- slew --------------------------------------------------------------------------------- */

typedef struct sx_slew {
    double fs, y, cr, cf; /* rise and fall coefficients (0: no lag) */
} sx_slew;

void sx_slew_init(sx_slew *s, double fs);
void sx_slew_set(sx_slew *s, double rise_s, double fall_s);
void sx_slew_reset(sx_slew *s, double y);
void sx_slew_render(sx_slew *s, uint32_t n, const float *in, float *out); /* [RT] */

/* --- echo --------------------------------------------------------------------------------- */

#define SX_ECHO_MAX_S 1.0
#define SX_ECHO_LEN 65536u /* per line, a power of two: 1.36 s at 48 kHz */

typedef struct sx_echo {
    double fs;
    float *l, *r; /* SX_ECHO_LEN each, caller-owned */
    uint32_t pos;
    double lp, lpc; /* feedback low-pass state and coefficient */
} sx_echo;

void sx_echo_init(sx_echo *e, double fs, float *mem /* 2 x SX_ECHO_LEN */);
void sx_echo_reset(sx_echo *e);
void sx_echo_tone(sx_echo *e, double hz);
/* [RT] time_s and the time input (volts, 1 V doubles the time) per sample */
void sx_echo_render(sx_echo *e, uint32_t n, const float *in, const float *time_v, double time_s,
                    double feedback, double mix, float *l, float *r);

/* --- reverb (FDN) ------------------------------------------------------------------------ */

/* Our addition (PATCH-3, PM-04): a 4-line feedback delay network. Prime line lengths 1423, 1777,
 * 2131, 2557 samples at 48 kHz (scaled by `size`), mixed by an orthonormal 4x4 Hadamard matrix,
 * each line's gain set so the tail falls 60 dB in `t60` seconds, a one-pole damping low-pass in
 * each loop (`tone`). Energy-preserving mixing and gains below one: it can only decay. */
#define SX_REV_LINES 4u
#define SX_REV_LEN 4096u /* per line, a power of two: room for size 1.5 */

typedef struct sx_rev {
    double fs;
    float *line[SX_REV_LINES]; /* SX_REV_LEN each, caller-owned */
    uint32_t len[SX_REV_LINES], pos;
    double g[SX_REV_LINES], lp[SX_REV_LINES], c;
    double t60, size, tone;
} sx_rev;

void sx_rev_init(sx_rev *r, double fs, float *mem /* 4 x SX_REV_LEN */);
void sx_rev_reset(sx_rev *r);
void sx_rev_set(sx_rev *r, double t60, double size, double tone_hz); /* recomputes the gains */
void sx_rev_render(sx_rev *r, uint32_t n, const float *in, double mix, float *l,
                   float *rr); /* [RT] */

/* --- shared -------------------------------------------------------------------------------- */

uint32_t sx_xorshift32(uint32_t *s);
double sx_onepole_coeff(double tau_s, double fs); /* exp(-1 / (tau fs)); 0 for tau 0 */

#endif
