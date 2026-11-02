/* test_vco.c: the band-limited VCO (VS-30, ADR-010; DSP-08, DSP-01).
 *
 *   DSP-08 as ADR-010 specifies it: sine, triangle, saw, pulse 0.5 and 0.1 at keys 0 to 48,
 *   frequencies from the program's 12-bit D/A codes, 0.1 s discarded, 65,536 samples at 48 kHz,
 *   Blackman-Harris, DC and harmonics masked +/- 8 bins, the highest bin between 20 Hz and
 *   20 kHz at or below -60 dBc (above -70 dBc is a warning); a 4 s glissando key 0 to key 48 in
 *   1-cent steps, every STFT frame at or below -60 dBc; and the self-check that the same
 *   analysis sees PolyBLEP (-33 to -37 dBc) and naive (above -30 dBc) aliasing at C6.
 *   Also: the sx_exp2 and sine accuracy, C4 pitch within 3 cents at 12 bits, a pitch step at an
 *   exact frame, determinism of the 37 saw renders (SHA-256 pinned in tests/engine/golden/),
 *   and the measured cost per 128-frame period at 8 voices.
 *
 * Re-bless the pinned hash (a deliberate change to the VCO or its tables) with
 *   SX_REBLESS=1 build/engine/tests/test_vco
 * and give the reason in the commit (DEV-PLAN 7.2).
 */
#include "sha256.h"
#include "spectrum.h"
#include "sx_math.h"
#include "vco.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures, checks, warnings;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

#define FS 48000.0
#define N 65536u
#define SKIP 4800u
#define BASENOTE 48
#define GOLDEN "tests/engine/golden/vco-saw-37.sha256"

static float buf[SKIP + N];
static float scratch[SKIP + N];

/* the program's pitch table code for a note (ARCHITECTURE 6.3), truncated to 12 bits */
static double volts_of_note(int note)
{
    double c = floor((note - 12) / 12.0 * 65536.0 / 10.24 + 0.5);
    uint32_t code = c < 0 ? 0u : (c > 65535 ? 65535u : (uint32_t)c);
    code &= 0xFFF0u;
    return (double)(code >> 4) * 10.24 / 4096.0;
}

static double freq_of_volts(double v)
{
    return SX_VCO_F0_HZ * pow(2.0, v);
}

enum wave { W_SINE, W_TRI, W_SAW, W_PULSE50, W_PULSE10, W_NWAVES };
static const char *wave_name[W_NWAVES] = {"sine", "tri", "saw", "pulse0.5", "pulse0.1"};

static void render(enum wave w, double volts, float *out, uint32_t n)
{
    static float pwbuf[SKIP + N];
    sx_vco v;
    sx_vco_init(&v, FS);
    sx_vco_set_pitch(&v, volts);
    float width = w == W_PULSE10 ? 0.1f : 0.5f;
    for (uint32_t i = 0; i < n; i++)
        pwbuf[i] = width;
    sx_vco_render(&v, n, pwbuf, NULL, w == W_SINE ? out : NULL, w == W_TRI ? out : NULL,
                  w == W_SAW ? out : NULL, (w == W_PULSE50 || w == W_PULSE10) ? out : NULL);
}

static double dbc_of(const float *x, double f)
{
    spec_mag_of(x, N);
    return spec_residual_dbc(N, FS, f, f);
}

static void test_math(void)
{
    double worst = 0.0;
    for (double x = -12.0; x <= 12.0; x += 0.001953125 + 1e-7) {
        double e = fabs(sx_exp2(x) / pow(2.0, x) - 1.0);
        worst = e > worst ? e : worst;
    }
    printf("sx_exp2: worst relative error %.2e (%.2e cent)\n", worst, worst * 1731.234);
    CHECK(worst < 1e-12); /* ADR-010 asks for 0.01 cent = 5.8e-6 */
    CHECK(sx_exp2(0.0) == 1.0 && sx_exp2(4.0) == 16.0 && sx_exp2(-3.0) == 0.125);
    double s_worst = 0.0;
    for (double p = -2.0; p <= 2.0; p += 0.0001234) {
        double e = fabs(sx_sin_cycles(p) - sin(2.0 * 3.14159265358979323846 * p));
        s_worst = e > s_worst ? e : s_worst;
    }
    printf("sx_sin_cycles: worst absolute error %.2e\n", s_worst);
    CHECK(s_worst < 1e-12);
}

/* DSP-01 part (VS-30 AC): C4 within 3 cents at 12 bits; a pitch step at its exact frame. */
static void test_pitch(void)
{
    double v = volts_of_note(60);
    CHECK(fabs(v - 4.0) < 1e-12); /* X'6400' is 4 V on the default converter */
    sx_vco o;
    sx_vco_init(&o, FS);
    sx_vco_set_pitch(&o, v);
    sx_vco_render(&o, 48000, NULL, NULL, buf, NULL, NULL, NULL);
    /* rising zero crossings, linearly interpolated, over 1 s */
    double first = -1, last = -1;
    int count = 0;
    for (uint32_t i = 1; i < 48000; i++)
        if (buf[i - 1] < 0.0f && buf[i] >= 0.0f) {
            double t = (double)(i - 1) + (double)(-buf[i - 1] / (buf[i] - buf[i - 1]));
            if (first < 0)
                first = t;
            last = t;
            count++;
        }
    double f = (double)(count - 1) * FS / (last - first);
    double cents = 1200.0 * log2(f / 261.63);
    printf("C4: %.4f Hz, %+.3f cents from 261.63\n", f, cents);
    CHECK(fabs(cents) < 3.0);

    /* the step: the first 1000 samples are untouched; sample 1000 advances by the new step */
    sx_vco a, b;
    sx_vco_init(&a, FS);
    sx_vco_init(&b, FS);
    sx_vco_set_pitch(&a, 3.0);
    sx_vco_set_pitch(&b, 3.0);
    sx_vco_render(&a, 2000, NULL, NULL, NULL, NULL, buf, NULL);
    sx_vco_render(&b, 1000, NULL, NULL, NULL, NULL, scratch, NULL);
    double ph = b.phase;
    sx_vco_set_pitch(&b, 4.0);
    sx_vco_render(&b, 1, NULL, NULL, NULL, NULL, scratch + 1000, NULL);
    CHECK(memcmp(buf, scratch, 1000 * sizeof(float)) == 0);
    double want = ph + freq_of_volts(4.0) / FS;
    CHECK(fabs(b.phase - (want >= 1.0 ? want - 1.0 : want)) < 1e-9);
    CHECK(scratch[1000] != buf[1000]);
}

/* DSP-08: every waveform at keys 0 to 48. */
static void test_aliasing(void)
{
    double worst[W_NWAVES], worst_top[W_NWAVES];
    int worst_key[W_NWAVES];
    for (int w = 0; w < W_NWAVES; w++) {
        worst[w] = worst_top[w] = -400.0;
        worst_key[w] = -1;
        for (int key = 0; key <= 48; key++) {
            double volts = volts_of_note(BASENOTE + key);
            render((enum wave)w, volts, buf, SKIP + N);
            double f = freq_of_volts(volts);
            double d = dbc_of(buf + SKIP, f);
            double top = spec_residual_band(N, FS, f, f, 20000.0, FS / 2.0); /* reported only */
            if (top > worst_top[w])
                worst_top[w] = top;
            if (d > worst[w]) {
                worst[w] = d;
                worst_key[w] = key;
            }
            if (d > -70.0 && d <= -60.0) {
                warnings++;
                printf("WARNING DSP-08 %s key %d: %.1f dBc (above -70)\n", wave_name[w], key, d);
            }
            if (d > -60.0)
                fprintf(stderr, "DSP-08 FAIL %s key %d: %.1f dBc\n", wave_name[w], key, d);
            CHECK(d <= -60.0);
        }
        printf("DSP-08 %-8s keys 0-48: worst %.1f dBc at key %d (20-24 kHz, not counted: %.1f)\n",
               wave_name[w], worst[w], worst_key[w], worst_top[w]);
    }
}

/* The self-check: the metric sees aliasing. PolyBLEP and naive saws, C6 = key 36. */
static double polyblep(double t, double dt)
{
    if (t < dt) {
        t /= dt;
        return t + t - t * t - 1.0;
    }
    if (t > 1.0 - dt) {
        t = (t - 1.0) / dt;
        return t * t + t + t + 1.0;
    }
    return 0.0;
}

static void test_metric_sees_aliasing(void)
{
    double f = freq_of_volts(volts_of_note(BASENOTE + 36));
    double dt = f / FS, ph = 0.0;
    for (uint32_t i = 0; i < SKIP + N; i++) {
        ph += dt;
        if (ph >= 1.0)
            ph -= 1.0;
        buf[i] = (float)(2.0 * ph - 1.0 - polyblep(ph, dt));
        scratch[i] = (float)(2.0 * ph - 1.0);
    }
    /* ADR-010 states the range as "reproducing the lane's measurement", and the lane measured
     * over the whole band to fs/2 (-35.1 and -27.2 dBc). Over the DSP-08 band, 20 Hz to 20 kHz,
     * the same signals measure about -40 and -29 dBc: still 20 dB above the limit, so the metric
     * sees aliasing in either band. Both are asserted; the mismatch is reported to the
     * architecture owner (docs/qa/results/M2/VS-30.md). */
    spec_mag_of(buf + SKIP, N);
    double pb_full = spec_residual_band(N, FS, f, f, 0.0, FS / 2.0);
    double pb = spec_residual_dbc(N, FS, f, f);
    spec_mag_of(scratch + SKIP, N);
    double nv_full = spec_residual_band(N, FS, f, f, 0.0, FS / 2.0);
    double nv = spec_residual_dbc(N, FS, f, f);
    printf("self-check at C6 (%.2f Hz), 0-24 kHz: PolyBLEP saw %.1f dBc, naive saw %.1f dBc\n", f,
           pb_full, nv_full);
    printf("self-check at C6, 20 Hz-20 kHz (DSP-08 band): PolyBLEP %.1f dBc, naive %.1f dBc\n", pb,
           nv);
    CHECK(pb_full >= -37.0 && pb_full <= -33.0); /* ADR-010's range, in the lane's band */
    CHECK(nv_full > -30.0);
    CHECK(pb > -50.0 && nv > -30.0); /* the DSP-08 band also sees both, far above -60 */
}

/* DSP-08 glissando: key 0 to key 48 over 4 s in 1-cent steps (pitch steps at exact frames). */
static float gl[48000u * 5u];

static void test_glissando(void)
{
    const uint32_t lead = 4800, total = 4800u + 192000u, frame = 4096, hop = 1024;
    double v0 = volts_of_note(BASENOTE), cents = 4800.0, per_step = total - lead;
    per_step /= cents; /* 40 samples per cent */
    for (int w = W_TRI; w <= W_PULSE50; w++) {
        sx_vco v;
        sx_vco_init(&v, FS);
        sx_vco_set_pitch(&v, v0);
        sx_vco_render(&v, lead, NULL, NULL, NULL, w == W_TRI ? gl : NULL, w == W_SAW ? gl : NULL,
                      w == W_PULSE50 ? gl : NULL);
        uint32_t at = lead;
        for (int c = 1; c <= 4800; c++) {
            uint32_t next = lead + (uint32_t)((double)c * per_step);
            sx_vco_render(&v, next - at, NULL, NULL, NULL, w == W_TRI ? gl + at : NULL,
                          w == W_SAW ? gl + at : NULL, w == W_PULSE50 ? gl + at : NULL);
            at = next;
            sx_vco_set_pitch(&v, v0 + (double)c / 1200.0);
        }
        double worst = -400.0;
        uint32_t frames = 0;
        for (uint32_t s = lead; s + frame <= total; s += hop, frames++) {
            double c_lo = (double)(s - lead) / per_step,
                   c_hi = (double)(s + frame - lead) / per_step;
            double f_lo = freq_of_volts(v0 + c_lo / 1200.0),
                   f_hi = freq_of_volts(v0 + c_hi / 1200.0);
            spec_mag_of(gl + s, frame);
            double d = spec_residual_dbc(frame, FS, f_lo, f_hi);
            worst = d > worst ? d : worst;
        }
        printf("DSP-08 glissando %-8s %u frames: worst %.1f dBc\n", wave_name[w], frames, worst);
        CHECK(worst <= -60.0);
    }
}

/* Determinism: the 37 saw renders, hashed (identical on every machine: PO-10). */
static void test_saw_hashes(void)
{
    sx_sha256 h;
    sx_sha256_init(&h);
    for (int key = 0; key <= 36; key++) {
        render(W_SAW, volts_of_note(BASENOTE + key), buf, SKIP + N);
        for (uint32_t i = 0; i < SKIP + N; i++) { /* little-endian float32 bytes */
            uint32_t u;
            memcpy(&u, &buf[i], 4);
            uint8_t b[4] = {(uint8_t)u, (uint8_t)(u >> 8), (uint8_t)(u >> 16), (uint8_t)(u >> 24)};
            sx_sha256_update(&h, b, 4);
        }
    }
    uint8_t d[32];
    char hex[65], pinned[80] = "";
    sx_sha256_final(&h, d);
    sx_sha256_hex(d, hex);
    printf("37 saw renders: sha256 %s\n", hex);
    if (getenv("SX_REBLESS")) {
        FILE *f = fopen(GOLDEN, "w");
        CHECK(f != NULL);
        if (f) {
            fprintf(f, "%s\n", hex);
            fclose(f);
        }
        printf("re-blessed %s\n", GOLDEN);
        return;
    }
    FILE *f = fopen(GOLDEN, "r");
    CHECK(f != NULL);
    if (f) {
        CHECK(fgets(pinned, sizeof pinned, f) != NULL);
        fclose(f);
    }
    CHECK(strncmp(pinned, hex, 64) == 0);
}

/* Cost: 8 voices, all four outputs, 128-frame periods (recorded, not asserted). */
static void test_cost(void)
{
    static sx_vco v[8];
    static float o[4][128];
    for (int i = 0; i < 8; i++) {
        sx_vco_init(&v[i], FS);
        sx_vco_set_pitch(&v[i], volts_of_note(BASENOTE + 29 + i)); /* up to G6 with transpose */
    }
    const int periods = 3750; /* 10 s of audio */
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int p = 0; p < periods; p++)
        for (int i = 0; i < 8; i++)
            sx_vco_render(&v[i], 128, NULL, NULL, o[0], o[1], o[2], o[3]);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double us =
        ((double)(t1.tv_sec - t0.tv_sec) * 1e6 + (double)(t1.tv_nsec - t0.tv_nsec) / 1e3) / periods;
    printf("VCO cost: %.2f us per 128-frame period, 8 voices, 4 outputs (period is 2667 us)\n", us);
    CHECK(us > 0.0);
}

int main(void)
{
    test_math();
    test_pitch();
    test_metric_sees_aliasing();
    test_aliasing();
    test_glissando();
    test_saw_hashes();
    test_cost();
    printf("test_vco: %d checks, %d failures, %d warnings\n", checks, failures, warnings);
    return failures != 0;
}
