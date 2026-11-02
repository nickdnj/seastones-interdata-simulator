/* test_auth.c: authenticity modes (PM-07; DSP-17, DSP-21; ARCHITECTURE 6.4).
 *
 *   strobed  D/A writes move to the next strobe frame (the first at or after them), only the last
 *            write per channel survives, gate writes pass through; the schedule does not depend
 *            on the period size
 *   analog   equals authentic followed by a one-pole low-pass at output_hz, to -90 dB; the two
 *            differ before that filter (DSP-17)
 *   jitter   research only: delays stay within 0 .. 6 sigma, each channel keeps its order, and
 *            the same seed gives the same delays (the production build has no such code:
 *            tests/engine/test_profiles_replay.py)
 */
#include "auth.h"
#include "graph.h"
#include "patch.h"

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

static void test_strobed(void)
{
    sx_authst a;
    sx_auth_init(&a, 48000, 1000.0, 1.0);
    sx_auth_set_mode(&a, SX_AUTH_STROBED, 0);
    /* strobes every 48 frames: 0, 48, 96 ... */
    sx_dev_ev in[] = {{0, 0x21, 0, 0x1000},  {10, 0x21, 3, 0x2000}, {20, 0x22, 0, 0x8000},
                      {30, 0x21, 3, 0x3000}, {48, 0x21, 5, 0x4000}, {100, 0x21, 0, 0x5000}};
    sx_dev_ev out[32];
    uint32_t n = sx_auth_process(&a, in, 6, 0, 128, out, 32);
    /* expected: ch0 at 0; gate at 20; ch3 (last: 3000) and ch5 at 48; ch0 (5000) held for 144 */
    CHECK(n == 4);
    CHECK(out[0].frame == 0 && out[0].ch == 0 && out[0].val == 0x1000);
    CHECK(out[1].frame == 20 && out[1].dev == 0x22);
    CHECK(out[2].frame == 48 && out[2].ch == 3 && out[2].val == 0x3000);
    CHECK(out[3].frame == 48 && out[3].ch == 5);
    n = sx_auth_process(&a, NULL, 0, 128, 128, out, 32);
    CHECK(n == 1 && out[0].frame == 144 - 128 && out[0].ch == 0 && out[0].val == 0x5000);
    /* the schedule is the same in periods of 7 frames */
    sx_authst b;
    sx_auth_init(&b, 48000, 1000.0, 1.0);
    sx_auth_set_mode(&b, SX_AUTH_STROBED, 0);
    uint32_t got = 0;
    uint64_t frames[8];
    for (uint64_t f0 = 0; f0 < 256; f0 += 7) {
        sx_dev_ev part[8];
        uint32_t np = 0;
        for (int i = 0; i < 6; i++)
            if (in[i].frame >= f0 && in[i].frame < f0 + 7)
                part[np++] =
                    (sx_dev_ev){(uint32_t)(in[i].frame - f0), in[i].dev, in[i].ch, in[i].val};
        uint32_t k = sx_auth_process(&b, part, np, f0, 7, out, 32);
        for (uint32_t i = 0; i < k && got < 8; i++)
            frames[got++] = f0 + out[i].frame;
    }
    CHECK(got == 5 && frames[0] == 0 && frames[1] == 20 && frames[2] == 48 && frames[3] == 48 &&
          frames[4] == 144);
    printf("strobed at 1 kHz: writes move to the next strobe frame, the last one per channel "
           "wins, gates pass; same schedule in 7-frame periods\n");
}

static float ax[4800], ay[4800], bx[4800], by[4800];

static void test_analog(void)
{
    static const char *p = "graph 1\nmodule m mixer\nmodule o out\nparam o level 0.1\n"
                           "cable dac.0 m.in1\ncable m.out o.l\n";
    sx_graph *a = sx_patch_build(p, strlen(p), 48000.0, NULL, 0);
    sx_graph *b = sx_patch_build(p, strlen(p), 48000.0, NULL, 0);
    if (!a || !b)
        return;
    sx_graph_set_analog(b, 1, 2000.0);
    sx_graph_render(a, 100, ax, ay);
    sx_graph_render(b, 100, bx, by);
    sx_graph_event(a, 0, 10.0f);
    sx_graph_event(b, 0, 10.0f);
    sx_graph_render(a, 4700, ax + 100, ay + 100);
    sx_graph_render(b, 4700, bx + 100, by + 100);
    /* the authentic step, through an independent one-pole at 2 kHz */
    double c = exp(-2.0 * M_PI * 2000.0 / 48000.0), s = 0, worst = 0, before = 0;
    for (int i = 0; i < 4800; i++) {
        s = (double)ax[i] + (s - (double)ax[i]) * c;
        double d = fabs(s - (double)bx[i]);
        worst = d > worst ? d : worst;
        double e = fabs((double)ax[i] - (double)bx[i]);
        before = e > before ? e : before;
    }
    printf("analog = authentic through a 2 kHz one-pole: residual %.1f dB (before the filter they "
           "differ by %.1f dB)\n",
           20.0 * log10(worst + 1e-30), 20.0 * log10(before + 1e-30));
    CHECK(20.0 * log10(worst + 1e-30) < -90.0 && before > 0.1);
    sx_patch_free(a);
    sx_patch_free(b);
}

static void test_jitter(void)
{
    sx_authst a, b;
    sx_auth_init(&a, 48000, 1000.0, 2.0); /* sigma 2 ms = 96 frames */
    sx_auth_init(&b, 48000, 1000.0, 2.0);
    sx_auth_set_mode(&a, SX_AUTH_JITTER, 0);
    sx_auth_set_mode(&b, SX_AUTH_JITTER, 0);
    sx_dev_ev in[64], out[256], outb[256];
    uint64_t last[16] = {0};
    uint16_t lastv[16] = {0};
    int order_ok = 1, range_ok = 1, same = 1;
    uint32_t total = 0;
    for (uint64_t f0 = 0; f0 < 48000; f0 += 128) {
        uint32_t nin = 0;
        for (uint32_t k = 0; k < 4; k++) {
            uint16_t ch = (uint16_t)((f0 / 128 + k) % 16);
            in[nin++] = (sx_dev_ev){k * 30, 0x21, (uint8_t)ch, (uint16_t)(f0 + k)};
        }
        uint32_t n = sx_auth_process(&a, in, nin, f0, 128, out, 256);
        uint32_t nb = sx_auth_process(&b, in, nin, f0, 128, outb, 256);
        same &= n == nb && memcmp(out, outb, n * sizeof out[0]) == 0;
        for (uint32_t i = 0; i < n; i++) {
            uint64_t f = f0 + out[i].frame;
            uint32_t ch = out[i].ch;
            order_ok &= f >= last[ch] && out[i].val >= lastv[ch];
            last[ch] = f;
            lastv[ch] = out[i].val;
            /* written at (val & ~3) - ... : the write's frame is val's f0 + k x 30 */
            uint64_t wrote = (uint64_t)(out[i].val & ~3u) + (out[i].val & 3u) * 30u;
            range_ok &= f >= wrote && f <= wrote + 6u * 96u + 1u;
        }
        total += n;
    }
    printf("jitter (research only), sigma 2 ms: %u writes delayed within 0-12 ms: %s; order per "
           "channel kept: %s; same seed, same delays: %s\n",
           total, range_ok ? "yes" : "NO", order_ok ? "yes" : "NO", same ? "yes" : "NO");
    CHECK(total > 1400 && range_ok && order_ok && same);
}

int main(void)
{
    test_strobed();
    test_analog();
    test_jitter();
    printf("test_auth: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
