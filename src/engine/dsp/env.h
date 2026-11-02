/* env.h: the envelope generator (VS-10; ARCHITECTURE 6.2 `env`; QA DSP-05).
 *
 * ADSR, or AR (attack to full, hold while the gate is high, release). Gate high when its input
 * is above 2.5 V (2.5 V itself is low). Output 0 to 10 V.
 *
 * Curves are the RC shapes of an analog envelope, each set so its time means what a player
 * reads on the panel:
 *   attack   rises toward 1.5 x full and switches to decay at full; from 0 it crosses 90 % at
 *            exactly the attack time (time constant attack / ln 2.5)
 *   decay    falls toward the sustain level, within -60 dB of it at the decay time
 *   release  falls toward 0, at -60 dB at the release time
 * A new gate (or a retrigger) starts the attack from the current level, so nothing jumps.
 * Coefficients are computed with sx_exp2 (no libm) when a time is set.
 *
 * Real-time safe. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_ENV_H
#define SX_ENV_H

#include <stdint.h>

#define SX_ENV_GATE_V 2.5
#define SX_ENV_ATTACK_TARGET 1.5

enum sx_env_stage { SX_ENV_IDLE = 0, SX_ENV_ATTACK, SX_ENV_DECAY, SX_ENV_SUSTAIN, SX_ENV_RELEASE };

typedef struct sx_env {
    double fs;
    double attack_s, decay_s, sustain, release_s;
    int ar;            /* AR mode */
    int stage;         /* enum sx_env_stage */
    int gate;          /* the gate as last seen (after the threshold) */
    double level;      /* 0..1 */
    double ca, cd, cr; /* per-sample coefficients */
} sx_env;

void sx_env_init(sx_env *e, double fs); /* defaults: 2 ms, 200 ms, 0.7, 300 ms, ADSR */
void sx_env_set(sx_env *e, double attack_s, double decay_s, double sustain, double release_s);
void sx_env_set_ar(sx_env *e, int ar);
void sx_env_reset(sx_env *e);

/* [RT] The gate input changed to `volts` at the next sample. */
void sx_env_gate(sx_env *e, double volts);
void sx_env_retrigger(sx_env *e); /* the `retrig` input's rising edge */

/* [RT] n samples of output, volts (0..10). */
void sx_env_render(sx_env *e, uint32_t n, float *out);

#endif
