/* vca.h: the VCA (VS-10; ARCHITECTURE 6.2 `vca`; QA DSP-06).
 *
 * gain = cv / 10 V (linear) or (2^cv - 1) / 1023 (exponential: 0 at 0 V, 1 at 10 V, about
 * 6 dB per volt near the top), clamped to 0..1. The cv passes through a one-pole declick with a
 * 0.5 ms time constant first: a real VCA's finite slew, and the one deliberate exception to "no
 * smoothing" (ADR-005), so a D/A step on the cv cannot click. It is stated in the honest labels.
 *
 * Real-time safe. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_VCA_H
#define SX_VCA_H

#include <stdint.h>

#define SX_VCA_DECLICK_S 0.0005

typedef struct sx_vca {
    double c;  /* declick coefficient per sample */
    double cv; /* the smoothed cv, volts */
    int expo;  /* exponential response */
} sx_vca;

void sx_vca_init(sx_vca *v, double fs);
void sx_vca_reset(sx_vca *v);

/* [RT] out[i] = in[i] x gain(declick(cv[i])). `cv` is volts per sample; NULL means 0 V. */
void sx_vca_render(sx_vca *v, uint32_t n, const float *in, const float *cv, float *out);

#endif
