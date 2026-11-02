/* voice.h: the slice's hard-wired single voice (VS-10): VCO saw -> VCA, envelope on the gate.
 *
 * Pitch comes from a D/A channel in volts (1 V/oct), the gate from a gate line (5 V high) or a
 * D/A channel through the envelope's 2.5 V threshold. Output is the VCA's, scaled by
 * SX_VOICE_LEVEL so a full-gain saw sits at -6 dBFS and the safety chain (VS-11) has headroom.
 * The patch graph (PM-*) replaces this wiring; the modules stay the same.
 *
 * Real-time safe. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_VOICE_H
#define SX_VOICE_H

#include "env.h"
#include "vca.h"
#include "vco.h"

#define SX_VOICE_LEVEL 0.5f
#define SX_VOICE_BLOCK 64u

typedef struct sx_voice {
    sx_vco vco;
    sx_env env;
    sx_vca vca;
} sx_voice;

void sx_voice_init(sx_voice *v, double fs);
void sx_voice_reset(sx_voice *v);
void sx_voice_pitch(sx_voice *v, double volts);            /* [RT] from the next sample */
void sx_voice_gate(sx_voice *v, double volts);             /* [RT] from the next sample */
void sx_voice_render(sx_voice *v, uint32_t n, float *out); /* [RT] adds nothing: writes out */

#endif
