/* vco.h: the band-limited VCO (VS-30, ADR-010; ARCHITECTURE 6.2).
 *
 * Saw and pulse by table-driven minBLEP, triangle by minBLAMP, sine by a fixed polynomial, all
 * at the output rate with no oversampling. Pitch is 1 V/oct: f = f0 x 2^(V + tune + fine), with
 * f0 = 16.352 Hz (C0) at 0 V by default, computed by sx_exp2 (no libm), and clamped to 20 kHz.
 * A pitch change (a D/A step) takes effect at an exact sample: the first sample rendered after
 * sx_vco_set_pitch advances by the new increment, and the slope change it makes in the saw and
 * triangle is itself band-limited (a minBLAMP at that instant).
 *
 * Outputs are normalised to +/-1 (the patch graph scales them to volts). Outputs passed as NULL
 * are not computed (ADR-010: unconnected outputs cost nothing).
 *
 * Real-time safe: no allocation, locks, syscalls or libm. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_VCO_H
#define SX_VCO_H

#include <stdint.h>

#include "minblep.h"

#define SX_VCO_F0_HZ 16.351597831287414 /* C0 at 0 V */
#define SX_VCO_FMAX_HZ 20000.0

enum { SX_VCO_TRI = 0, SX_VCO_SAW, SX_VCO_PULSE, SX_VCO_NRING };

typedef struct sx_vco {
    double fs;          /* output rate */
    double f0;          /* Hz at 0 V */
    double tune;        /* volts added to the pitch input (the `tune` and `fine` knobs) */
    double volts;       /* the pitch input */
    double inc;         /* phase increment per sample, f / fs */
    double phase;       /* [0, 1) */
    double fm_hz_per_v; /* linear FM depth */
    int pulse_high;     /* the pulse's naive state */
    uint32_t pos;       /* ring read position */
    float ring[SX_VCO_NRING][SX_BLEP_SPAN];
    double tail[SX_VCO_NRING]; /* minBLAMP final-value offset: tail x current slope */
} sx_vco;

void sx_vco_init(sx_vco *v, double fs);
void sx_vco_reset(sx_vco *v); /* phase 0, residuals cleared (the supervisor's module reset) */
void sx_vco_set_tune(sx_vco *v, double volts);
void sx_vco_set_pitch(sx_vco *v, double volts); /* [RT] at the next sample */

/* [RT] Render n samples. `pw` (pulse width per sample, clamped to [0.02, 0.98]) may be NULL for
 * a fixed 0.5; `fm` (volts per sample, scaled by fm_hz_per_v) may be NULL (unconnected). Any
 * output pointer may be NULL. */
void sx_vco_render(sx_vco *v, uint32_t n, const float *pw, const float *fm, float *sine, float *tri,
                   float *saw, float *pulse);

#endif
