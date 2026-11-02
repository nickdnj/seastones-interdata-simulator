/* env.c: the envelope generator (VS-10; see env.h). Copyright (c) 2026 Nick D. MIT licence. */
#include "env.h"

#include "sx_math.h"

#define LN2 0.69314718055994531
#define LN_2_5 0.91629073187415511 /* ln 2.5 */
#define LN_1000 6.9077552789821371 /* ln 1000: -60 dB */
#define FLOOR 1e-6                 /* below this the stage is over */

/* exp(-1 / (tau * fs)), or 0 for tau 0 (an instant stage) */
static double coeff(double tau, double fs)
{
    if (!(tau > 0.0))
        return 0.0;
    return sx_exp2(-1.0 / (tau * fs) / LN2);
}

static void update(sx_env *e)
{
    e->ca = coeff(e->attack_s / LN_2_5, e->fs);
    e->cd = coeff(e->decay_s / LN_1000, e->fs);
    e->cr = coeff(e->release_s / LN_1000, e->fs);
}

void sx_env_reset(sx_env *e)
{
    e->stage = SX_ENV_IDLE;
    e->gate = 0;
    e->level = 0.0;
}

void sx_env_init(sx_env *e, double fs)
{
    e->fs = fs > 0.0 ? fs : 48000.0;
    e->ar = 0;
    sx_env_set(e, 0.002, 0.2, 0.7, 0.3);
    sx_env_reset(e);
}

static double clamp(double x, double lo, double hi)
{
    return !(x >= lo) ? lo : (x > hi ? hi : x);
}

void sx_env_set(sx_env *e, double attack_s, double decay_s, double sustain, double release_s)
{
    e->attack_s = clamp(attack_s, 0.0, 30.0);
    e->decay_s = clamp(decay_s, 0.0, 30.0);
    e->sustain = clamp(sustain, 0.0, 1.0);
    e->release_s = clamp(release_s, 0.0, 30.0);
    update(e);
}

void sx_env_set_ar(sx_env *e, int ar)
{
    e->ar = ar != 0;
}

void sx_env_retrigger(sx_env *e)
{
    if (e->gate)
        e->stage = SX_ENV_ATTACK;
}

void sx_env_gate(sx_env *e, double volts)
{
    int high = volts > SX_ENV_GATE_V;
    if (high && !e->gate)
        e->stage = SX_ENV_ATTACK;
    else if (!high && e->gate && e->stage != SX_ENV_IDLE)
        e->stage = SX_ENV_RELEASE;
    e->gate = high;
}

void sx_env_render(sx_env *e, uint32_t n, float *out)
{
    double lv = e->level;
    for (uint32_t i = 0; i < n; i++) {
        switch (e->stage) {
        case SX_ENV_ATTACK:
            lv = SX_ENV_ATTACK_TARGET + (lv - SX_ENV_ATTACK_TARGET) * e->ca;
            if (lv >= 1.0) {
                lv = 1.0;
                e->stage = e->ar ? SX_ENV_SUSTAIN : SX_ENV_DECAY;
            }
            break;
        case SX_ENV_DECAY:
            lv = e->sustain + (lv - e->sustain) * e->cd;
            if (lv - e->sustain < FLOOR) {
                lv = e->sustain;
                e->stage = SX_ENV_SUSTAIN;
            }
            break;
        case SX_ENV_SUSTAIN:
            lv = e->ar ? 1.0 : e->sustain; /* follows a sustain change while held */
            break;
        case SX_ENV_RELEASE:
            lv *= e->cr;
            if (lv < FLOOR) {
                lv = 0.0;
                e->stage = SX_ENV_IDLE;
            }
            break;
        default:
            lv = 0.0;
            break;
        }
        out[i] = (float)(lv * 10.0);
    }
    e->level = lv;
}
