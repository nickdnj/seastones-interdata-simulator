/* test_modules.c: the module set (PM-01, PM-02, PM-03, PM-04; DSP-01, DSP-04, DSP-17, DSP-18,
 * DSP-23).
 *
 *   vcf    -3 dB point against the 1 V/oct prediction and octave tracking, the 4-pole slope,
 *          10^6 fuzzed blocks at maximum resonance, no self-oscillation from silence, HP and BP
 *   vco    1 V/oct within 3 cents across 8 octaves through the 12-bit converter (PM-01)
 *   lfo    1 Hz at 0 V and 1 V/oct; noise statistics and determinism; slew's step response
 *   only `slew` smooths a D/A step: a step through every other module's CV path lands at once
 *   echo   60 s at maximum feedback: no growth, bounded output (PM-04)
 */
#include "graph.h"
#include "id_seastones.h"
#include "mods.h"
#include "patch.h"
#include "vcf.h"
#include "vco.h"

#include <math.h>
#ifndef M_PI /* glibc hides it under -std=c17 */
#define M_PI 3.14159265358979323846
#endif
#include <stdio.h>
#include <stdlib.h>
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
#define LEN 48000u

static float in[LEN], lp[LEN], hp[LEN], bp[LEN];

/* |H(f)| of output `which` (0 lp, 1 hp, 2 bp) from a small impulse's response (the filter is
 * linear at this level), by a direct DFT at f */
static double gain(double volts, double res, double f, int which)
{
    sx_vcf v;
    sx_vcf_init(&v, FS);
    sx_vcf_set(&v, volts, res);
    for (uint32_t i = 0; i < LEN; i++)
        in[i] = i == 0 ? 0.001f : 0.0f;
    sx_vcf_render(&v, LEN, in, lp, hp, bp);
    const float *y = which == 0 ? lp : which == 1 ? hp : bp;
    double re = 0, im = 0, w = 2.0 * M_PI * f / FS;
    for (uint32_t i = 0; i < LEN; i++) {
        re += (double)y[i] * cos(w * i);
        im -= (double)y[i] * sin(w * i);
    }
    return sqrt(re * re + im * im) / 0.001;
}

static double f3db(double volts)
{
    double g0 = gain(volts, 0.0, 0.0, 0);
    double lo = 2.0, hi = 20000.0;
    for (int k = 0; k < 40; k++) {
        double mid = sqrt(lo * hi);
        if (gain(volts, 0.0, mid, 0) > g0 / sqrt(2.0))
            lo = mid;
        else
            hi = mid;
    }
    return sqrt(lo * hi);
}

/* the ladder's -3 dB point as designed: four TPT poles at fc (prewarped) */
static double predict(double volts)
{
    double fc = sx_vcf_hz(volts), fs2 = 2.0 * FS;
    return fs2 / M_PI * atan(0.43491 * tan(M_PI * fc / fs2));
}

static void test_vcf(void)
{
    double worst_abs = 0, worst_oct = 0, prev = 0, prev_v = 0;
    for (double v = 2.8; v <= 10.4 + 1e-9; v += (v < 9.7 ? 1.0 : 0.6)) {
        double f = f3db(v), p = predict(v);
        double c = 1200.0 * log2(f / p);
        worst_abs = fabs(c) > worst_abs ? fabs(c) : worst_abs;
        if (prev > 0 && v <= 7.8 + 1e-9) { /* PM-02: five octaves, 50 Hz to 1.6 kHz */
            double oc = 1200.0 * log2(f / prev) - 1200.0 * (v - prev_v);
            worst_oct = fabs(oc) > worst_oct ? fabs(oc) : worst_oct;
        }
        printf("vcf lp %.1f V: -3 dB at %8.2f Hz, predicted %8.2f (%+.1f cents)\n", v, f, p, c);
        prev = f;
        prev_v = v;
    }
    /* above about 1.6 kHz the bilinear transform bends the -3 dB point (the pole frequency stays
     * exact by prewarping): the prediction includes that, the octave check stops below it */
    printf("vcf 1 V/oct: worst %.1f cents from the prediction (50 Hz-10 kHz), %.1f cents per "
           "octave (5 octaves from 50 Hz)\n",
           worst_abs, worst_oct);
    CHECK(worst_abs <= 25.0); /* DSP-04 */
    CHECK(worst_oct <= 10.0); /* PM-02 */
    /* 4-pole slope: between 4 and 8 times the pole frequency, 24 dB/oct within 3 dB */
    double f = sx_vcf_hz(4.0);
    double s = 20.0 * log10(gain(4.0, 0.0, 4.0 * f, 0) / gain(4.0, 0.0, 8.0 * f, 0));
    printf("vcf lp slope from 4 to 8 x fc: %.1f dB/oct\n", s);
    CHECK(fabs(s - 24.0) <= 3.0);
    /* HP and BP (S): HP is down at a fifth of fc and passes 5 fc; BP peaks near fc */
    double fc = sx_vcf_hz(5.0);
    double h_lo = 20.0 * log10(gain(5.0, 0.3, fc / 8.0, 1) / gain(5.0, 0.3, fc * 8.0, 1));
    double b_mid = gain(5.0, 0.3, fc, 2), b_lo = gain(5.0, 0.3, fc / 8.0, 2);
    printf("vcf hp: %.1f dB down 3 octaves below fc; bp: %.1f dB above its value 3 octaves down\n",
           -h_lo, 20.0 * log10(b_mid / b_lo));
    CHECK(h_lo < -30.0 && b_mid > 4.0 * b_lo);
}

static uint32_t rng = 1974u;
static double urand(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return (double)rng / 2147483648.0 - 1.0;
}

static void test_vcf_fuzz_and_ring(void)
{
    const char *env = getenv("SX_VCF_BLOCKS");
    long blocks = env ? atol(env) : 1000000L;
    sx_vcf v;
    sx_vcf_init(&v, FS);
    double pk = 0;
    int finite = 1;
    float x[16], a[16], b[16], c[16];
    for (long k = 0; k < blocks; k++) {
        sx_vcf_set(&v, -4.0 + 18.0 * (urand() * 0.5 + 0.5), 1.0); /* maximum resonance */
        v.drive = 4.0;
        for (int i = 0; i < 16; i++)
            x[i] = (float)(k % 97 == 0 ? 1e9 * urand() : urand()); /* white, sometimes absurd */
        sx_vcf_render(&v, 16, x, a, b, c);
        for (int i = 0; i < 16; i++) {
            finite &= isfinite(a[i]) && isfinite(b[i]) && isfinite(c[i]);
            pk = fabs((double)a[i]) > pk ? fabs((double)a[i]) : pk;
        }
    }
    printf("vcf fuzz: %ld blocks at maximum resonance and drive (seed 1974): finite %s, lp peak "
           "%.2f\n",
           blocks, finite ? "yes" : "NO", pk);
    CHECK(finite && pk < 4.0); /* the ladder output is bounded by its saturating input */
    /* from a loud burst into silence at maximum resonance: rings down, never sustains */
    sx_vcf_init(&v, FS);
    sx_vcf_set(&v, 6.0, 1.0);
    for (uint32_t i = 0; i < LEN; i++)
        in[i] = i < 480 ? (float)urand() : 0.0f;
    sx_vcf_render(&v, LEN, in, lp, NULL, NULL);
    double tail = 0;
    for (uint32_t i = LEN - 4800; i < LEN; i++)
        tail = fabs((double)lp[i]) > tail ? fabs((double)lp[i]) : tail;
    printf("vcf at maximum resonance, 1 s after a burst: %.1f dBFS\n", 20.0 * log10(tail + 1e-30));
    CHECK(20.0 * log10(tail + 1e-30) < -60.0); /* DSP-04: no self-oscillation */
}

static double freq_of(const float *x, uint32_t n)
{
    double first = -1, last = -1;
    int count = 0;
    for (uint32_t i = 1; i < n; i++)
        if (x[i - 1] < 0.0f && x[i] >= 0.0f) {
            double t = (double)(i - 1) + (double)(-x[i - 1] / (x[i] - x[i - 1]));
            if (first < 0)
                first = t;
            last = t;
            count++;
        }
    return count > 1 ? (double)(count - 1) * FS / (last - first) : 0.0;
}

static float big[4 * LEN];

static void test_vco_12bit(void)
{
    /* each C from C1 to C8 through the 12-bit converter: the program's ideal 16-bit code,
     * truncated, to volts, to the VCO (ARCHITECTURE 6.3) */
    double worst = 0;
    for (int oct = 1; oct <= 8; oct++) {
        for (int semi = 0; semi < 12; semi += 5) {
            int note = 12 * (oct + 1) + semi; /* MIDI */
            uint32_t code = (uint32_t)lround((note - 12) / 12.0 * 65536.0 / 10.24);
            if (code > 0xFFFF)
                continue;
            double v = (double)sx_dac_volts(code, 12, 10.24f);
            sx_vco vc;
            sx_vco_init(&vc, FS);
            sx_vco_set_pitch(&vc, v);
            uint32_t n = 4u * LEN;
            sx_vco_render(&vc, n, NULL, NULL, big, NULL, NULL, NULL);
            double f = freq_of(big, n), want = 440.0 * pow(2.0, (note - 69) / 12.0);
            double c = 1200.0 * log2(f / want);
            worst = fabs(c) > worst ? fabs(c) : worst;
        }
    }
    printf("vco through the 12-bit converter, C1-C8: worst %.2f cents from equal temperament\n",
           worst);
    CHECK(worst <= 3.0); /* PM-01 */
}

static void test_lfo_noise_slew(void)
{
    sx_lfo l;
    sx_lfo_init(&l, FS, 1);
    sx_lfo_render(&l, 4u * LEN, NULL, 0.0, big, NULL, NULL, NULL);
    double f0 = freq_of(big, 4u * LEN);
    sx_lfo_init(&l, FS, 1);
    sx_lfo_render(&l, 4u * LEN, NULL, 1.0, big, NULL, NULL, NULL);
    double f1 = freq_of(big, 4u * LEN);
    printf("lfo: %.4f Hz at 0 V, %.4f Hz at 1 V\n", f0, f1);
    CHECK(fabs(f0 - 1.0) < 0.01 && fabs(f1 / f0 - 2.0) < 0.01);

    sx_noise z1, z2;
    sx_noise_init(&z1, 5);
    sx_noise_init(&z2, 5);
    sx_noise_render(&z1, LEN, in, lp);
    sx_noise_render(&z2, LEN, hp, bp);
    double m = 0, s = 0;
    for (uint32_t i = 0; i < LEN; i++) {
        m += in[i];
        s += (double)in[i] * in[i];
    }
    m /= LEN;
    s = sqrt(s / LEN);
    printf("noise: white mean %.4f, rms %.3f; same seed, same noise: %s\n", m, s,
           memcmp(in, hp, sizeof in) == 0 && memcmp(lp, bp, sizeof lp) == 0 ? "yes" : "NO");
    CHECK(fabs(m) < 0.02 && fabs(s - 0.577) < 0.02 && memcmp(in, hp, sizeof in) == 0);

    sx_slew sl;
    sx_slew_init(&sl, FS);
    sx_slew_set(&sl, 0.010, 0.010);
    for (uint32_t i = 0; i < LEN; i++)
        in[i] = 10.0f;
    sx_slew_render(&sl, LEN, in, lp);
    printf("slew 10 ms: %.3f V after 10 ms of a 10 V step (1 - 1/e = 6.321)\n", lp[479]);
    CHECK(fabs(lp[479] - 6.321f) < 0.01f);
}

/* a 1 V step on dac.0 at frame 100, through module `m`'s CV path to the out: the output's
 * first change is at frame 100 (no smoothing), except through slew */
static int step_lands_at_once(const char *patch, uint32_t *at)
{
    char err[160];
    sx_graph *g = sx_patch_build(patch, strlen(patch), FS, err, sizeof err);
    if (g == NULL) {
        fprintf(stderr, "  %s\n", err);
        return 0;
    }
    sx_graph_event(g, 0, 1.0f);
    sx_graph_render(g, 100, lp, hp);
    float before = lp[99];
    sx_graph_event(g, 0, 2.0f);
    sx_graph_render(g, 100, lp, hp);
    *at = 0;
    while (*at < 100 && lp[*at] == before)
        (*at)++;
    int ok = *at == 0 && fabsf(lp[0] - lp[99]) < 1e-6f; /* changed at once, fully */
    sx_patch_free(g);
    return ok;
}

static void test_only_slew_smooths(void)
{
    static const char *paths[] = {
        "graph 1\nmodule m mixer\nmodule o out\ncable dac.0 m.in1\ncable m.out o.l\n",
        "graph 1\nmodule m mixer\nmodule s slew\nmodule o out\nparam s rise 0\nparam s fall 0\n"
        "cable dac.0 m.in1\ncable m.out s.in\ncable s.out o.l\n",
    };
    uint32_t at;
    CHECK(step_lands_at_once(paths[0], &at));
    CHECK(step_lands_at_once(paths[1], &at)); /* slew at time 0 passes steps through */
    /* with a rise time, slew smooths the very same step */
    const char *smooth = "graph 1\nmodule s slew\nmodule o out\nparam s rise 0.01\n"
                         "cable dac.0 s.in\ncable s.out o.l\n";
    CHECK(!step_lands_at_once(smooth, &at));
    /* a VCO pitch step takes effect at its exact frame (DSP-18): the phase increment changes
     * from the first sample after the write */
    sx_vco a, b;
    sx_vco_init(&a, FS);
    sx_vco_init(&b, FS);
    sx_vco_set_pitch(&a, 4.0);
    sx_vco_set_pitch(&b, 4.0);
    sx_vco_render(&a, 1000, NULL, NULL, in, NULL, NULL, NULL);
    sx_vco_render(&b, 1000, NULL, NULL, lp, NULL, NULL, NULL);
    sx_vco_set_pitch(&b, 4.0 + 1.0 / 4096.0 * 10.24); /* one 12-bit LSB */
    double inc_before = a.inc;
    sx_vco_render(&b, 1, NULL, NULL, lp, NULL, NULL, NULL);
    printf("only slew smooths a D/A step: mixer and slew(0) pass it at once; a 1-LSB pitch step "
           "changes the VCO's increment by %.3e at the very next sample\n",
           b.inc - inc_before);
    CHECK(b.inc > inc_before);
}

static void test_echo(void)
{
    static float mem[2 * SX_ECHO_LEN];
    sx_echo e;
    sx_echo_init(&e, FS, mem);
    sx_echo_tone(&e, 12000.0);
    double pk_late = 0, pk = 0, energy_1 = 0, energy_59 = 0;
    int finite = 1;
    for (int sec = 0; sec < 60; sec++) {
        for (uint32_t i = 0; i < LEN; i++)
            in[i] = sec == 0 && i < 4800 ? (float)urand() : 0.0f;
        sx_echo_render(&e, LEN, in, NULL, 0.25, 0.9, 1.0, lp, hp);
        for (uint32_t i = 0; i < LEN; i++) {
            finite &= isfinite(lp[i]) && isfinite(hp[i]);
            double v = fabs((double)lp[i]) > fabs((double)hp[i]) ? fabs((double)lp[i])
                                                                 : fabs((double)hp[i]);
            pk = v > pk ? v : pk;
            if (sec >= 1)
                pk_late = v > pk_late ? v : pk_late;
            if (sec == 1)
                energy_1 += v * v;
            if (sec == 59)
                energy_59 += v * v;
        }
    }
    printf("echo at maximum feedback, 60 s after a 0.1 s burst: peak %.3f, energy second 59 vs "
           "second 1: %.1f dB\n",
           pk, 10.0 * log10((energy_59 + 1e-30) / (energy_1 + 1e-30)));
    CHECK(finite && pk <= 1.0 && energy_59 < energy_1); /* PM-04: stable, decaying */
}

static void test_reverb(void)
{
    static float mem[SX_REV_LINES * SX_REV_LEN];
    sx_rev r;
    sx_rev_init(&r, FS, mem);
    sx_rev_set(&r, 2.0, 1.0, 16000.0);
    /* an impulse: the 50 ms energy falls steadily and reaches -60 dB near t60 */
    static float x[4 * LEN];
    for (uint32_t i = 0; i < 4 * LEN; i++)
        x[i] = i == 0 ? 1.0f : 0.0f;
    sx_rev_render(&r, 4 * LEN, x, 1.0, big, NULL);
    double e0 = 0, t60 = 0, prev = 1e30;
    int rises = 0;
    for (uint32_t w = 4; w < 4 * LEN / 2400; w++) { /* from 200 ms, past the build-up */
        double e = 0;
        for (uint32_t i = w * 2400; i < (w + 1) * 2400; i++)
            e += (double)big[i] * big[i];
        if (w == 4)
            e0 = e;
        if (e > prev * 1.5) /* a 50 ms window may beat; growth over that is a limit cycle */
            rises++;
        prev = e;
        if (t60 == 0.0 && e < e0 * 1e-6)
            t60 = (double)w * 0.05 - 0.2;
    }
    printf("reverb, t60 2 s: -60 dB of its 200 ms energy %.2f s later; %d rising windows\n", t60,
           rises);
    CHECK(rises == 0 && t60 > 1.6 && t60 < 2.4); /* DSP-23 */
    /* 60 s at the maximum setting, a loud burst first: never grows, stays finite */
    sx_rev_set(&r, 10.0, 1.5, 16000.0);
    sx_rev_reset(&r);
    double pk_first = 0, pk_last = 0;
    int finite = 1;
    for (int sec = 0; sec < 60; sec++) {
        for (uint32_t i = 0; i < LEN; i++)
            in[i] = sec == 0 && i < 4800 ? (float)urand() : 0.0f;
        sx_rev_render(&r, LEN, in, 1.0, lp, hp);
        double pk = 0;
        for (uint32_t i = 0; i < LEN; i++) {
            finite &= isfinite(lp[i]) && isfinite(hp[i]);
            pk = fabs((double)lp[i]) > pk ? fabs((double)lp[i]) : pk;
        }
        if (sec == 1)
            pk_first = pk;
        if (sec == 59)
            pk_last = pk;
    }
    printf("reverb at maximum (t60 10 s, size 1.5), 60 s after a burst: second 1 peak %.3f, "
           "second 59 peak %.2e\n",
           pk_first, pk_last);
    CHECK(finite && pk_last < pk_first * 1e-3);
}

int main(void)
{
    test_vcf();
    test_vcf_fuzz_and_ring();
    test_vco_12bit();
    test_lfo_noise_slew();
    test_only_slew_smooths();
    test_echo();
    test_reverb();
    printf("test_modules: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
