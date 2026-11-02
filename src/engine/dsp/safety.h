/* safety.h: the output safety chain (VS-11; ARCHITECTURE 6.5; AUDIO-2, AUDIO-3, NFR-5).
 *
 * Fixed order, last in sx_render, not patchable:
 *   DC blocker (5 Hz) -> high-pass 25 Hz (2nd-order Butterworth) -> soft clip (tanh above a
 *   -3 dBFS knee) -> look-ahead brick-wall limiter (1 ms look-ahead, 4x interpolated peak
 *   detection) at ceiling = min(staff ceiling, quiet-hours ceiling, HARD_MAX = -1 dBFS)
 *   -> visitor volume (clamped to at most 0 dB, i.e. never above the ceiling) -> mute ramp -> out
 *
 * Mute: a 5 ms linear ramp to zero. Start (device open) and unmute: a 200 ms fade-in.
 * Non-finite input is replaced by 0, the filter state is reset, and `nonfinite` counts it for the
 * supervisor (VS-16). Limiter: each sample's required gain comes from the larger of the sample
 * and the 8x windowed-sinc interpolation of both segments next to it (32 taps per phase, 16
 * samples of the look-ahead), with a 0.05 dB detection margin; a sliding minimum then a box
 * average over the other 32 samples ramp the gain down before the peak arrives, so the sample
 * peak never passes the ceiling and inter-sample peaks stay within 0.1 dB of it (DSP-11, 8x).
 *
 * The chain adds the limiter's look-ahead, SX_SAFETY_LATENCY frames, to the output (in the NFR-1
 * budget). Real-time safe, no libm. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_SAFETY_H
#define SX_SAFETY_H

#include <stdint.h>

#define SX_HARD_MAX_DBFS (-1.0)
#define SX_SAFETY_LOOKAHEAD 48u /* 1 ms at 48 kHz; fixed in frames */
#define SX_SAFETY_LATENCY (SX_SAFETY_LOOKAHEAD - 1u)
#define SX_TP_OS 8u                                     /* the peak interpolator: 8x */
#define SX_TP_TAPS 32u                                  /* taps per phase */
#define SX_TP_DELAY 16u                                 /* its delay, part of the look-ahead */
#define SX_LIM_W (SX_SAFETY_LATENCY - SX_TP_DELAY + 1u) /* hold and box windows: 32 */
#define SX_MUTE_RAMP_S 0.005
#define SX_FADE_IN_S 0.2

typedef struct sx_biquad {
    double b0, b1, b2, a1, a2;
    double x1, x2, y1, y2;
} sx_biquad;

typedef struct sx_safety {
    double fs;
    /* DC blocker */
    double dc_r, dc_x1, dc_y1;
    sx_biquad hpf;
    /* limiter */
    float delay[SX_SAFETY_LOOKAHEAD];      /* audio, L - 1 samples of look-ahead */
    double hist[SX_TP_TAPS + 1u];          /* recent samples, for the 8x peak estimate */
    double fir[SX_TP_OS - 1u][SX_TP_TAPS]; /* windowed-sinc phases 1/8 .. 7/8 */
    float hold[SX_LIM_W];                  /* required gain, sliding minimum window */
    double box[SX_LIM_W];                  /* held gain, box average window */
    uint32_t wpos;
    double gain; /* after release smoothing */
    double rel;  /* release coefficient */
    uint32_t pos;
    double ceiling; /* linear */
    double detect;  /* the limiter's threshold: ceiling - 0.05 dB */
    double staff_dbfs, quiet_dbfs;
    double volume; /* visitor volume, linear, <= 1 */
    /* mute and fade */
    double out_gain; /* 0..1 */
    double mute_step, fade_step;
    int muted;
    uint32_t nonfinite;
} sx_safety;

void sx_safety_init(sx_safety *s, double fs); /* starts silent: call sx_safety_start */
void sx_safety_start(sx_safety *s);           /* device open: 200 ms fade-in */
/* [RT] forget all audio held in the chain (HOME); the fade-in starts from silence */
void sx_safety_clear(sx_safety *s);
void sx_safety_set_ceiling(sx_safety *s, double staff_dbfs, double quiet_dbfs);
double sx_safety_ceiling_dbfs(const sx_safety *s);
void sx_safety_set_volume(sx_safety *s, double db); /* clamped to <= 0 dB */
void sx_safety_mute(sx_safety *s, int on);
void sx_safety_process(sx_safety *s, float *buf, uint32_t n); /* [RT] mono, in place */

/* The stages alone, for DSP-10's response tests. */
double sx_softclip(double x);
void sx_biquad_hpf(sx_biquad *b, double fs, double fc); /* 2nd-order Butterworth high-pass */
double sx_biquad_run(sx_biquad *b, double x);
double sx_db_to_lin(double db);

#endif
