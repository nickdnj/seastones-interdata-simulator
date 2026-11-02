/* test_voice.c: envelope, VCA and the slice's single voice (VS-10; DSP-05, DSP-06).
 *
 * The click metric is QA-STRATEGY 3.6's: for a note on or off, subtract the ideal tone shaped
 * by the patch's own envelope (here an independent double-precision model of the envelope and
 * VCA formulas, with libm, driving an identical oscillator) and take the peak residual in a
 * 5 ms window; a click is a residual above -50 dBFS. The test also shows the metric catches a
 * real click (an oscillator phase reset at note on).
 */
#include "env.h"
#include "vca.h"
#include "voice.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

#define FS 48000.0
#define LEN 96000u

static float out[LEN], ideal[LEN], envb[LEN];

/* first sample index at which x crosses `level` (upward if up) */
static long first_cross(const float *x, uint32_t n, float level, int up)
{
    for (uint32_t i = 0; i < n; i++)
        if (up ? x[i] >= level : x[i] <= level)
            return (long)i;
    return -1;
}

static void test_envelope(void)
{
    sx_env e;
    sx_env_init(&e, FS);
    sx_env_set(&e, 0.010, 0.100, 0.5, 0.200);
    sx_env_gate(&e, 5.0);
    sx_env_render(&e, LEN, envb);
    long t90 = first_cross(envb, LEN, 9.0f, 1);
    printf("attack 10 ms: 90 %% at sample %ld (%.3f ms)\n", t90, (double)t90 / 48.0);
    CHECK(fabs((double)(t90 + 1) - 480.0) <= 0.05 * 480.0 + 1.0); /* within 5 % and one sample */
    CHECK(fabs(envb[LEN - 1] - 5.0f) < 1e-3f);                    /* decayed to sustain */
    long tpk = first_cross(envb, LEN, 10.0f, 1);
    long ts = first_cross(envb + tpk, LEN - (uint32_t)tpk, 5.0f + 5.0f * 0.001f, 0);
    printf("decay 100 ms: within -60 dB of sustain after %.2f ms\n", (double)ts / 48.0);
    CHECK(fabs((double)ts - 4800.0) <= 0.05 * 4800.0 + 1.0);

    sx_env_gate(&e, 0.0); /* release from 5 V to -60 dB (5 mV) at 200 ms */
    sx_env_render(&e, LEN, envb);
    long tr = first_cross(envb, LEN, 5.0f * 0.001f, 0);
    printf("release 200 ms: -60 dB after %.2f ms\n", (double)tr / 48.0);
    CHECK(fabs((double)tr - 9600.0) <= 0.05 * 9600.0 + 1.0);
    CHECK(envb[LEN - 1] == 0.0f && e.stage == SX_ENV_IDLE);

    /* retrigger from a non-zero level: no jump down */
    sx_env_gate(&e, 5.0);
    sx_env_render(&e, 200, envb);
    float before = envb[199];
    sx_env_gate(&e, 0.0);
    sx_env_render(&e, 100, envb);
    before = envb[99];
    sx_env_gate(&e, 5.0);
    sx_env_render(&e, 10, envb);
    CHECK(before > 1.0f && envb[0] >= before);

    /* the threshold: 2.5 V exactly and 2.49 V are low, 2.51 V is high */
    sx_env_reset(&e);
    sx_env_gate(&e, 2.49);
    CHECK(e.gate == 0);
    sx_env_gate(&e, 2.5);
    CHECK(e.gate == 0);
    sx_env_gate(&e, 2.51);
    CHECK(e.gate == 1 && e.stage == SX_ENV_ATTACK);

    /* AR: attack to full, hold, release */
    sx_env_reset(&e);
    sx_env_set_ar(&e, 1);
    sx_env_gate(&e, 5.0);
    sx_env_render(&e, 48000, envb);
    CHECK(envb[47999] == 10.0f);
    sx_env_gate(&e, 0.0);
    sx_env_render(&e, 48000, envb);
    CHECK(envb[47999] == 0.0f);
}

static void test_vca_declick(void)
{
    static float one[4800], cv[4800], g[4800];
    for (int i = 0; i < 4800; i++) {
        one[i] = 1.0f;
        cv[i] = 10.0f;
    }
    sx_vca v;
    sx_vca_init(&v, FS);
    sx_vca_render(&v, 4800, one, cv, g);
    /* after 0.5 ms (24 samples): 1 - 1/e of the step */
    printf("VCA 0-10 V step: %.4f after 0.5 ms (1 - 1/e = %.4f)\n", g[23], 1.0 - exp(-1.0));
    CHECK(fabs(g[23] - (1.0 - exp(-1.0))) < 0.01);
    CHECK(g[0] > 0.0f && g[0] < 0.05f); /* no step through */
    CHECK(fabs(g[4799] - 1.0f) < 1e-6f);
}

/* The ideal model: envelope and declick by their formulas in double, libm exp. */
typedef struct {
    double lv, cv, ca, cd, cr, cdecl, sus;
    int stage;
} model;

static void model_init(model *m, const sx_env *e)
{
    m->lv = m->cv = 0.0;
    m->stage = 0;
    m->sus = e->sustain;
    m->ca = exp(-1.0 / (e->attack_s / log(2.5) * FS));
    m->cd = exp(-1.0 / (e->decay_s / log(1000.0) * FS));
    m->cr = exp(-1.0 / (e->release_s / log(1000.0) * FS));
    m->cdecl = exp(-1.0 / (SX_VCA_DECLICK_S * FS));
}

static double model_gain(model *m)
{
    if (m->stage == 1) {
        m->lv = 1.5 + (m->lv - 1.5) * m->ca;
        if (m->lv >= 1.0) {
            m->lv = 1.0;
            m->stage = 2;
        }
    } else if (m->stage == 2) {
        m->lv = m->sus + (m->lv - m->sus) * m->cd;
        if (m->lv - m->sus < 1e-6) {
            m->lv = m->sus;
            m->stage = 3;
        }
    } else if (m->stage == 4) {
        m->lv *= m->cr;
        if (m->lv < 1e-6) {
            m->lv = 0.0;
            m->stage = 0;
        }
    }
    double target = m->lv * 10.0;
    m->cv = target + (m->cv - target) * m->cdecl;
    return m->cv / 10.0;
}

static double peak_dbfs(const float *a, const float *b, uint32_t from, uint32_t n)
{
    double p = 0.0;
    for (uint32_t i = from; i < from + n; i++) {
        double d = fabs((double)a[i] - (double)b[i]);
        p = d > p ? d : p;
    }
    return p > 0.0 ? 20.0 * log10(p) : -400.0;
}

/* Render one note (on at `on`, off at `off`) through the voice and through the ideal model.
 * With `bug`, the oscillator's phase is reset at note on: a real click the metric must catch. */
static void note(double volts, uint32_t on, uint32_t off, int bug)
{
    sx_voice v;
    sx_vco tone;
    model m;
    sx_voice_init(&v, FS);
    sx_vco_init(&tone, FS);
    sx_voice_pitch(&v, volts);
    sx_vco_set_pitch(&tone, volts);
    model_init(&m, &v.env);
    sx_voice_render(&v, on, out);
    sx_vco_render(&tone, on, NULL, NULL, NULL, NULL, ideal, NULL);
    for (uint32_t i = 0; i < on; i++)
        ideal[i] *= (float)model_gain(&m) * SX_VOICE_LEVEL;
    sx_voice_gate(&v, 5.0);
    if (bug)
        v.vco.phase = 0.0;
    m.stage = 1;
    sx_voice_render(&v, off - on, out + on);
    sx_vco_render(&tone, off - on, NULL, NULL, NULL, NULL, ideal + on, NULL);
    for (uint32_t i = on; i < off; i++)
        ideal[i] = (float)((double)ideal[i] * model_gain(&m) * SX_VOICE_LEVEL);
    sx_voice_gate(&v, 0.0);
    m.stage = 4;
    sx_voice_render(&v, LEN - off, out + off);
    sx_vco_render(&tone, LEN - off, NULL, NULL, NULL, NULL, ideal + off, NULL);
    for (uint32_t i = off; i < LEN; i++)
        ideal[i] = (float)((double)ideal[i] * model_gain(&m) * SX_VOICE_LEVEL);
}

static double volts_of_note(int n)
{
    double c = floor((n - 12) / 12.0 * 65536.0 / 10.24 + 0.5);
    uint32_t code = (uint32_t)(c < 0 ? 0 : c) & 0xFFF0u;
    return (double)(code >> 4) * 10.24 / 4096.0;
}

static void test_clicks(void)
{
    const uint32_t on = 2400, off = 26400, win = 240; /* 5 ms */
    double worst_on = -400, worst_off = -400;
    for (int key = 0; key < 37; key++) {
        note(volts_of_note(48 + key), on + (uint32_t)key * 7u, off + (uint32_t)key * 11u, 0);
        double a = peak_dbfs(out, ideal, on + (uint32_t)key * 7u, win);
        double b = peak_dbfs(out, ideal, off + (uint32_t)key * 11u, win);
        worst_on = a > worst_on ? a : worst_on;
        worst_off = b > worst_off ? b : worst_off;
        CHECK(a <= -50.0 && b <= -50.0);
    }
    printf("click metric, 37 keys: note on worst %.1f dBFS, note off worst %.1f dBFS\n", worst_on,
           worst_off);
    note(volts_of_note(60), on, off, 1);
    double bug = peak_dbfs(out, ideal, on, win);
    printf("click metric with a planted phase reset at note on: %.1f dBFS\n", bug);
    CHECK(bug > -50.0);
}

int main(void)
{
    test_envelope();
    test_vca_declick();
    test_clicks();
    printf("test_voice: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
