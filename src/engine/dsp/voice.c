/* voice.c: the slice's hard-wired single voice (VS-10; see voice.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "voice.h"

#include <stddef.h>

void sx_voice_init(sx_voice *v, double fs)
{
    sx_vco_init(&v->vco, fs);
    sx_env_init(&v->env, fs);
    sx_vca_init(&v->vca, fs);
}

void sx_voice_reset(sx_voice *v)
{
    sx_vco_reset(&v->vco);
    sx_env_reset(&v->env);
    sx_vca_reset(&v->vca);
}

void sx_voice_pitch(sx_voice *v, double volts)
{
    sx_vco_set_pitch(&v->vco, volts);
}

void sx_voice_gate(sx_voice *v, double volts)
{
    sx_env_gate(&v->env, volts);
}

void sx_voice_render(sx_voice *v, uint32_t n, float *out)
{
    float saw[SX_VOICE_BLOCK], cv[SX_VOICE_BLOCK];
    while (n) {
        uint32_t k = n < SX_VOICE_BLOCK ? n : SX_VOICE_BLOCK;
        sx_vco_render(&v->vco, k, NULL, NULL, NULL, NULL, saw, NULL);
        sx_env_render(&v->env, k, cv);
        sx_vca_render(&v->vca, k, saw, cv, out);
        for (uint32_t i = 0; i < k; i++)
            out[i] *= SX_VOICE_LEVEL;
        out += k;
        n -= k;
    }
}
