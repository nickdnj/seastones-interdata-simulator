/* test_safety.c: the output safety chain (VS-11; DSP-10, DSP-11 in its single-bus form, DSP-13).
 *
 * VS-11 AC: a full-scale square at maximum gain never exceeds the ceiling at the output; mute
 * silences the output within 8 ms. True peak is measured 8x oversampled (windowed-sinc
 * interpolation, test code with libm).
 */
#include "safety.h"

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
#define PI 3.14159265358979323846
#define LEN 96000u

static float buf[LEN];

static double db(double x)
{
    return x > 0 ? 20.0 * log10(x) : -400.0;
}

/* steady-state gain of a stage at f (sine through 2 s, measured over the last 0.5 s) */
static double response_db(int stage, double f)
{
    sx_biquad b;
    sx_biquad_hpf(&b, FS, 25.0);
    double r = exp(-2.0 * PI * 5.0 / FS), x1 = 0, y1 = 0, pk = 0;
    for (uint32_t i = 0; i < LEN; i++) {
        double x = sin(2.0 * PI * f * (double)i / FS), y;
        if (stage == 0) {
            y = x - x1 + r * y1;
            x1 = x;
            y1 = y;
        } else {
            y = sx_biquad_run(&b, x);
        }
        if (i > LEN - 24000u && fabs(y) > pk)
            pk = fabs(y);
    }
    return db(pk);
}

static void test_responses(void)
{
    double dc5 = response_db(0, 5.0), dc50 = response_db(0, 50.0);
    double h25 = response_db(1, 25.0), h12 = response_db(1, 12.5), h6 = response_db(1, 6.25);
    double h200 = response_db(1, 200.0);
    printf("DC blocker: %.2f dB at 5 Hz, %.3f dB at 50 Hz\n", dc5, dc50);
    printf("HPF 25 Hz: %.2f dB at 25 Hz, %.2f at 12.5, %.2f at 6.25, %.3f at 200\n", h25, h12, h6,
           h200);
    CHECK(fabs(dc5 + 3.0) < 1.0);
    CHECK(fabs(h25 + 3.0) < 2.0);
    CHECK(fabs((h12 - h6) - 12.0) < 1.5); /* 12 dB per octave below the corner */
    CHECK(fabs(h200) < 0.1 && fabs(dc50) < 0.1);

    /* soft clip: exact below the -3 dBFS knee, compressive above, never past 1 */
    CHECK(sx_softclip(0.5) == 0.5 && sx_softclip(-0.7) == -0.7);
    CHECK(sx_softclip(0.9) < 0.9 && sx_softclip(0.9) > 0.708);
    CHECK(sx_softclip(100.0) <= 1.0 && sx_softclip(-100.0) >= -1.0);
    double prev = 0.0;
    for (double x = 0.0; x < 4.0; x += 0.001) { /* monotonic and continuous at the knee */
        double y = sx_softclip(x);
        CHECK(y >= prev && y - prev < 0.0011);
        prev = y;
    }
}

/* 8x true peak: windowed-sinc interpolation, 32 taps each side */
static double true_peak(const float *x, uint32_t n)
{
    double pk = 0.0;
    for (uint32_t i = 32; i + 32 < n; i++)
        for (int ph = 0; ph < 8; ph++) {
            double t = (double)ph / 8.0, v = 0.0;
            for (int k = -31; k <= 32; k++) {
                double u = t - (double)k;
                double s = fabs(u) < 1e-12 ? 1.0 : sin(PI * u) / (PI * u);
                double w = 0.5 + 0.5 * cos(PI * u / 33.0);
                v += (double)x[(int)i + k] * s * w;
            }
            pk = fabs(v) > pk ? fabs(v) : pk;
        }
    return pk;
}

static void square_through(sx_safety *s, double gain_db, double f)
{
    double g = pow(10.0, gain_db / 20.0);
    for (uint32_t i = 0; i < LEN; i++)
        buf[i] = (float)(fmod((double)i * f / FS, 1.0) < 0.5 ? g : -g);
    sx_safety_process(s, buf, LEN);
}

static void test_ceiling(void)
{
    const double ceilings[] = {-1.0, -3.0, -6.0, -12.0, -20.0};
    for (int c = 0; c < 5; c++) {
        sx_safety s;
        sx_safety_init(&s, FS);
        sx_safety_set_ceiling(&s, ceilings[c], 0.0);
        sx_safety_start(&s);
        square_through(&s, 40.0, 997.0); /* full-scale square at +40 dB of gain */
        double pk = 0.0;
        for (uint32_t i = 0; i < LEN; i++)
            pk = fabs(buf[i]) > pk ? fabs(buf[i]) : pk;
        double tp = true_peak(buf + 24000, 24000);
        printf("ceiling %.0f dBFS: sample peak %.3f dBFS, true peak (8x) %.3f dBFS\n", ceilings[c],
               db(pk), db(tp));
        CHECK(db(pk) <= ceilings[c] + 1e-6);
        CHECK(db(tp) <= ceilings[c] + 0.1);
    }
    /* the hard maximum wins over a looser staff setting */
    sx_safety s;
    sx_safety_init(&s, FS);
    sx_safety_set_ceiling(&s, 0.0, 6.0);
    CHECK(sx_safety_ceiling_dbfs(&s) == SX_HARD_MAX_DBFS);
    sx_safety_set_ceiling(&s, -10.0, -14.0); /* quiet hours lower still */
    CHECK(sx_safety_ceiling_dbfs(&s) == -14.0);
    sx_safety_set_volume(&s, 6.0); /* visitor volume above the ceiling: clamped to 0 dB */
    CHECK(s.volume == 1.0);
    sx_safety_set_volume(&s, -6.0);
    CHECK(fabs(s.volume - 0.501187) < 1e-5);

    /* a sudden full-scale burst after silence: the look-ahead catches its first sample */
    sx_safety_init(&s, FS);
    sx_safety_start(&s);
    for (uint32_t i = 0; i < LEN; i++)
        buf[i] = 0.0f;
    sx_safety_process(&s, buf, 20000); /* fade-in done */
    for (uint32_t i = 0; i < 4800; i++)
        buf[i] = i < 2400 ? 0.0f : 30.0f * (float)sin(2.0 * PI * 3000.0 * i / FS);
    sx_safety_process(&s, buf, 4800);
    double pk = 0;
    for (uint32_t i = 0; i < 4800; i++)
        pk = fabs(buf[i]) > pk ? fabs(buf[i]) : pk;
    printf("burst after silence: peak %.3f dBFS\n", db(pk));
    CHECK(db(pk) <= -1.0 + 1e-6);
}

static void test_mute_and_fade(void)
{
    sx_safety s;
    sx_safety_init(&s, FS);
    for (uint32_t i = 0; i < 4800; i++)
        buf[i] = 0.5f;
    sx_safety_process(&s, buf, 4800); /* not started: silent */
    CHECK(buf[4799] == 0.0f);
    sx_safety_start(&s);
    square_through(&s, -10.0, 200.0);
    /* fade-in: about half way at 100 ms, full by 200 ms */
    double early = 0, late = 0;
    for (uint32_t i = 0; i < 480; i++)
        early = fabs(buf[i]) > early ? fabs(buf[i]) : early;
    for (uint32_t i = 12000; i < 24000; i++)
        late = fabs(buf[i]) > late ? fabs(buf[i]) : late;
    CHECK(early < 0.05 * late);

    /* mute: 5 ms ramp; silent (below -80 dBFS) within 8 ms (VS-11 AC 2, DSP-13) */
    sx_safety_mute(&s, 1);
    square_through(&s, -10.0, 200.0);
    double after = 0;
    for (uint32_t i = 384; i < LEN; i++)
        after = fabs(buf[i]) > after ? fabs(buf[i]) : after;
    printf("mute: after 8 ms peak %.1f dBFS\n", db(after));
    CHECK(db(after) < -80.0);
    CHECK(buf[240] == 0.0f); /* the ramp is over by 5 ms */
    sx_safety_mute(&s, 0);
    square_through(&s, -10.0, 200.0);
    CHECK(fabs(buf[LEN - 100]) > 0.1f);

    /* non-finite input is replaced and counted */
    float bad[4] = {NAN, INFINITY, -INFINITY, 0.25f};
    sx_safety_process(&s, bad, 4);
    CHECK(s.nonfinite == 3);
    for (int i = 0; i < 4; i++)
        CHECK(bad[i] == bad[i] && fabs(bad[i]) < 1.0f);
}

int main(void)
{
    test_responses();
    test_ceiling();
    test_mute_and_fade();
    printf("test_safety: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
