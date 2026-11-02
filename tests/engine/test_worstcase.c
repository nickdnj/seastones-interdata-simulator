/* test_worstcase.c: the complete safety chain against the worst patch (PM-08; AUDIO-2, AUDIO-3,
 * STAFF-2; DSP-11, DSP-13).
 *
 * Through the engine (sx_render), with no program: a patch of eight full-scale oscillators from
 * 65 Hz to 6.6 kHz (audible pitches: at 0 V a 16 Hz saw would trip the supervisor's runaway-DC
 * check, which mutes, and is tested in test_supervisor.c), noise, every
 * mixer at its maximum gain, a filter at maximum resonance and drive and the echo at maximum
 * feedback, all into `out` at full level, for 60 s (a patch with gain round a loop latches at
 * a rail, which the supervisor mutes as runaway DC: test_supervisor.c, test_graph.c):
 *   - the sample peak never passes the ceiling, for the hard maximum and for staff ceilings
 *     down to -30 dBFS; the true peak (8x interpolated) stays within 0.1 dB of it
 *   - visitor volume above 0 dB is clamped (never above the ceiling); below it scales
 *   - mute reaches -80 dBFS within 8 ms
 */
#include "safety.h"
#include "seastones.h"

#include <math.h>
#ifndef M_PI /* glibc hides it under -std=c17 */
#define M_PI 3.14159265358979323846
#endif
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

static const char worst[] =
    "graph 1\n"
    "module a vco\nmodule b vco\nmodule c vco\nmodule d vco\nmodule e vco\nmodule f vco\n"
    "module g vco\nmodule h vco\nmodule n noise\n"
    "param a tune 3\nparam b tune 3.37\nparam c tune 4.1\nparam d tune 5.3\nparam e tune 5.9\n"
    "param f tune 6.6\nparam g tune 7.2\nparam h tune 8.7\n"
    "module m1 mixer\nmodule m2 mixer\nmodule m3 mixer\nmodule m4 mixer\n"
    "param m1 l1 2\nparam m1 l2 2\nparam m1 l3 2\nparam m1 l4 2\n"
    "param m2 l1 2\nparam m2 l2 2\nparam m2 l3 2\nparam m2 l4 2\n"
    "param m3 l1 2\nparam m3 l2 2\nparam m3 l3 2\nparam m3 l4 2\n"
    "param m4 l1 2\nparam m4 l2 2\nparam m4 l3 2\nparam m4 l4 2\n"
    "cable a.saw m1.in1\ncable b.saw m1.in2\ncable c.pulse m1.in3\ncable d.saw m1.in4\n"
    "cable e.saw m2.in1\ncable f.tri m2.in2\ncable g.saw m2.in3\ncable h.pulse m2.in4\n"
    "cable m1.out m3.in1\ncable m2.out m3.in2\ncable n.white m3.in3\n"
    "module flt vcf\nparam flt res 1\nparam flt drive 4\nparam flt cutoff 9\n"
    "cable m3.out flt.in\ncable flt.lp m4.in1\ncable m3.out m4.in2\ncable flt.bp m4.in3\n"
    "module ec echo\nparam ec feedback 0.9\nparam ec mix 0.5\nparam ec time 0.05\n"
    "cable m4.out ec.in\n"
    "module o out\nparam o level 1\ncable ec.l o.l\ncable ec.r o.r\n";

static float buf[2 * 4800];

/* true peak of one channel by 8x windowed-sinc interpolation (independent of the chain's 4x) */
static double tp_over(const float *x, uint32_t n)
{
    double pk = 0;
    for (uint32_t i = 16; i + 16 < n; i++) {
        for (int p = 0; p < 8; p++) {
            double t = (double)p / 8.0, v = 0;
            for (int k = -15; k <= 16; k++) {
                double u = t - (double)k;
                double s = fabs(u) < 1e-12 ? 1.0 : sin(M_PI * u) / (M_PI * u);
                double w = 0.5 + 0.5 * cos(M_PI * u / 16.5);
                v += (double)x[2 * (i + (uint32_t)k)] * s * w;
            }
            pk = fabs(v) > pk ? fabs(v) : pk;
        }
    }
    return pk;
}

static sx_engine *engine(void)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    sx_engine *e = sx_create(&c);
    CHECK(e && sx_patch_load(e, worst, sizeof worst - 1u, NULL, 0) == SX_OK);
    return e;
}

static void command(sx_engine *e, uint32_t kind, uint32_t a, float f)
{
    sx_cmd c = {kind, a, 0, f};
    CHECK(sx_command(e, &c) == SX_OK);
}

static void test_ceilings(void)
{
    static const float ceilings[] = {-1.0f, -6.0f, -12.0f, -30.0f};
    for (size_t k = 0; k < sizeof ceilings / sizeof ceilings[0]; k++) {
        sx_engine *e = engine();
        if (!e)
            return;
        command(e, SX_CMD_CEILING, 0, ceilings[k]);
        double lim = sx_db_to_lin((double)ceilings[k]);
        double pk = 0, tp = 0;
        int seconds = k == 0 ? 60 : 10;
        for (int s = 0; s < seconds * 10; s++) {
            sx_render(e, buf, 4800);
            for (int i = 0; i < 9600; i++)
                pk = fabs((double)buf[i]) > pk ? fabs((double)buf[i]) : pk;
            if (s % 10 == 9) {
                double t = tp_over(buf, 4800), t2 = tp_over(buf + 1, 4800);
                tp = t > tp ? t : tp;
                tp = t2 > tp ? t2 : tp;
            }
        }
        printf("worst-case patch, ceiling %+.0f dBFS, %d s: sample peak %.3f dBFS, true peak "
               "%.3f dBFS\n",
               (double)ceilings[k], seconds, 20 * log10(pk), 20 * log10(tp));
        CHECK(pk <= lim * 1.000001);
        CHECK(tp <= lim * sx_db_to_lin(0.1));
        CHECK(pk > lim * 0.5); /* the patch really is loud: the limiter is working */
        sx_destroy(e);
    }
}

static double peak_of(sx_engine *e, int periods)
{
    double pk = 0;
    for (int s = 0; s < periods; s++) {
        sx_render(e, buf, 480);
        for (int i = 0; i < 960; i++)
            pk = fabs((double)buf[i]) > pk ? fabs((double)buf[i]) : pk;
    }
    return pk;
}

static void test_volume_and_mute(void)
{
    sx_engine *e = engine();
    if (!e)
        return;
    command(e, SX_CMD_CEILING, 0, -6.0f);
    peak_of(e, 100); /* past the fade-in */
    double full = peak_of(e, 50);
    command(e, SX_CMD_VOLUME, 0, 12.0f); /* a visitor asking for more than the ceiling */
    double more = peak_of(e, 50);
    command(e, SX_CMD_VOLUME, 0, -10.0f);
    double less = peak_of(e, 50);
    printf("visitor volume: at 0 dB %.2f dBFS, asking +12 dB %.2f dBFS, at -10 dB %.2f dBFS "
           "(ceiling -6)\n",
           20 * log10(full), 20 * log10(more), 20 * log10(less));
    CHECK(more <= sx_db_to_lin(-6.0) * 1.000001);
    CHECK(fabs(20 * log10(less / full) + 10.0) < 1.0);
    command(e, SX_CMD_MUTE, 1, 0.0f);
    sx_render(e, buf, 384); /* 8 ms */
    double after = peak_of(e, 10);
    printf("mute: %.1f dBFS from 8 ms after the command\n", 20 * log10(after + 1e-30));
    CHECK(after < sx_db_to_lin(-80.0));
    command(e, SX_CMD_MUTE, 0, 0.0f);
    double back = peak_of(e, 100);
    CHECK(back > 0.1);
    sx_destroy(e);
}

int main(void)
{
    test_ceilings();
    test_volume_and_mute();
    printf("test_worstcase: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
