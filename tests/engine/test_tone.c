/* test_tone.c: the staff test tone (SX_CMD_TEST_TONE; staff.test_tone, KP-08). A diagnostic,
 * off by default: the only sound the engine makes that does not come from the program's D/A
 * writes, so it is reachable only through a command, ramps in and out over 10 ms, sits far below
 * the limiter (-60 to -12 dBFS) and passes through the same safety chain and mute.
 */
#include "seastones.h"

#include <math.h>
#ifndef M_PI /* glibc hides it under -std=c17 */
#define M_PI 3.14159265358979323846
#endif
#include <stdio.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

static float out[2 * 48000];

static double peak(uint32_t from, uint32_t n)
{
    double p = 0;
    for (uint32_t i = from; i < from + n; i++)
        p = fabs((double)out[2 * i]) > p ? fabs((double)out[2 * i]) : p;
    return p;
}

/* frequency by zero crossings over the buffer's second half */
static double freq(uint32_t n)
{
    double first = -1, last = -1;
    int c = 0;
    for (uint32_t i = n / 2 + 1; i < n; i++)
        if (out[2 * (i - 1)] < 0.0f && out[2 * i] >= 0.0f) {
            double t =
                (double)(i - 1) + (double)(-out[2 * (i - 1)] / (out[2 * i] - out[2 * (i - 1)]));
            first = first < 0 ? t : first;
            last = t;
            c++;
        }
    return c > 1 ? (c - 1) * 48000.0 / (last - first) : 0.0;
}

static void tone(sx_engine *e, uint32_t on, uint32_t hz, float db)
{
    sx_cmd c = {SX_CMD_TEST_TONE, on, hz, db};
    CHECK(sx_command(e, &c) == SX_OK);
}

int main(void)
{
    sx_config cfg = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    sx_engine *e = sx_create(&cfg);
    sx_render(e, out, 24000); /* past the 200 ms fade-in */
    sx_render(e, out, 48000);
    CHECK(peak(0, 48000) == 0.0); /* off by default: silence */

    tone(e, 1, 0, 0.0f); /* defaults: 1 kHz at -20 dBFS */
    sx_render(e, out, 48000);
    double lvl = 20.0 * log10(peak(24000, 24000)), f = freq(48000);
    double step = 0;
    for (uint32_t i = 1; i < 960; i++) /* the 10 ms ramp: no step bigger than the sine's own */
        step = fabs((double)out[2 * i] - (double)out[2 * i - 2]) > step
                   ? fabs((double)out[2 * i] - (double)out[2 * i - 2])
                   : step;
    printf("test tone on: %.2f Hz at %.2f dBFS (L = R: %s); ramp's largest step %.4f\n", f, lvl,
           out[48000] == out[48001] ? "yes" : "NO", step);
    CHECK(fabs(f - 1000.0) < 0.05 && fabs(lvl + 20.0) < 0.1 && out[48000] == out[48001]);
    CHECK(step <= 2.0 * M_PI * 1000.0 / 48000.0 * 0.1 * 1.01);

    tone(e, 1, 440, 0.0f);
    sx_render(e, out, 48000);
    CHECK(fabs(freq(48000) - 440.0) < 0.05);
    tone(e, 1, 9000, -3.0f); /* asked for more: clamped to 4 kHz and -12 dBFS */
    sx_render(e, out, 48000);
    double clamp = 20.0 * log10(peak(24000, 24000));
    printf("asked for 9 kHz at -3 dBFS: %.1f Hz at %.2f dBFS\n", freq(48000), clamp);
    CHECK(fabs(freq(48000) - 4000.0) < 0.5 && fabs(clamp + 12.0) < 0.1);

    sx_cmd mute = {SX_CMD_MUTE, 1, 0, 0.0f}, unmute = {SX_CMD_MUTE, 0, 0, 0.0f};
    sx_command(e, &mute);
    sx_render(e, out, 4800);
    CHECK(peak(480, 4320) == 0.0); /* the tone goes through the mute */
    sx_command(e, &unmute);
    tone(e, 0, 0, 0.0f);
    sx_render(e, out, 48000);
    printf("after off: %.1f dBFS from 20 ms, %.1f from 100 ms\n",
           20 * log10(peak(960, 47000) + 1e-30), 20 * log10(peak(4800, 43000) + 1e-30));
    CHECK(peak(960, 47000) < 1e-4 && peak(4800, 43000) < 3e-6);
    /* below -80, then -110 */ /* off within 10 ms (the chain's high-pass rings down) */
    sx_destroy(e);
    printf("test_tone: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
