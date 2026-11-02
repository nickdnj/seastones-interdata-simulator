/* test_adversarial.c: the engine against hostile input (round 5 QA). Run under ASan and UBSan by
 * `make sanitize`.
 *
 *   - NaN, Inf and absurd parameters, in a patch's text and through SX_CMD_PATCH
 *   - the largest graph (64 modules, every input cabled, one output fanned out to all) and the
 *     65th module; a megabyte of comments; a NUL in the text; a line too long
 *   - the command ring flooded: refused cleanly past its 256, nothing lost of what it took
 *   - a patch load attempted every period for 10 s, and HOME every period
 *   - denormals: a resonant filter ringing down for 60 s keeps its speed (states are flushed)
 *   - snapshots read from another thread while rendering: never torn, always in order
 */
#include "graph.h"
#include "patch.h"
#include "seastones.h"
#include "sha256.h"

#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

static float out[2 * 4096];

static int finite_out(uint32_t n)
{
    for (uint32_t i = 0; i < 2 * n; i++)
        if (!isfinite(out[i]) || fabsf(out[i]) > 0.8913f)
            return 0;
    return 1;
}

static sx_engine *engine(void)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    return sx_create(&c);
}

static const char tone[] = "graph 1\nmodule osc vco\nmodule f vcf\nmodule amp vca\nmodule o out\n"
                           "param osc tune 4\nparam amp bias 10\nparam f res 1\n"
                           "cable osc.saw f.in\ncable f.lp amp.in\ncable amp.out o.l\n";

static void test_hostile_parameters(void)
{
    static const char *vals[] = {"nan",   "-nan",   "inf",    "-inf",
                                 "1e309", "-1e309", "0x1p99", "1e-320"};
    for (size_t k = 0; k < sizeof vals / sizeof vals[0]; k++) {
        char text[512], err[160];
        snprintf(text, sizeof text,
                 "%sparam osc tune %s\nparam f cutoff %s\nparam f res %s\nparam amp bias %s\n",
                 tone, vals[k], vals[k], vals[k], vals[k]);
        sx_graph *g = sx_patch_build(text, strlen(text), 48000.0, err, sizeof err);
        if (g == NULL) { /* refused by line: fine */
            CHECK(strstr(err, "not a number") != NULL);
            continue;
        }
        float l[512], r[512];
        int ok = 1;
        for (int i = 0; i < 100; i++) {
            sx_graph_render(g, 512, l, r);
            for (int j = 0; j < 512; j++)
                ok &= isfinite(l[j]) && fabsf(l[j]) <= 12.0f;
        }
        CHECK(ok);
        sx_patch_free(g);
    }
    /* the same through the command ring, at run time */
    sx_engine *e = engine();
    CHECK(sx_patch_load(e, tone, sizeof tone - 1u, NULL, 0) == SX_OK);
    static const float bad[] = {NAN, INFINITY, -INFINITY, 1e30f, -1e30f};
    int ok = 1;
    for (size_t k = 0; k < sizeof bad / sizeof bad[0]; k++) {
        for (uint32_t m = 0; m < 6; m++)
            for (uint32_t p = 0; p < 8; p++) { /* every module, every parameter, and past both */
                sx_cmd c = {SX_CMD_PATCH, m, p, bad[k]};
                sx_command(e, &c);
            }
        for (int i = 0; i < 20; i++) {
            sx_render(e, out, 1024);
            ok &= finite_out(1024);
        }
    }
    printf("hostile parameters: nan, inf, 1e309, hex and subnormal, in text and by command: "
           "output finite, within the ceiling: %s\n",
           ok ? "yes" : "NO");
    CHECK(ok);
    sx_destroy(e);
}

static void test_huge_and_strange_texts(void)
{
    static char text[1 << 21];
    char err[160];
    /* 64 modules, every input cabled from one LFO output (fan-out to 250 inputs) */
    size_t n = (size_t)snprintf(text, sizeof text, "graph 1\nmodule src lfo\n");
    static const char *types[] = {"vco", "vcf", "mixer", "echo", "slew", "vca", "env"};
    for (int k = 1; k < 63; k++)
        n += (size_t)snprintf(text + n, sizeof text - n, "module m%d %s\n", k,
                              types[k % 7 == 3 && k > 10 ? 0 : k % 7]);
    n += (size_t)snprintf(text + n, sizeof text - n, "module o out\n");
    int cables = 0;
    for (int k = 1; k < 63; k++) {
        int t = sx_module_type(types[k % 7 == 3 && k > 10 ? 0 : k % 7]);
        for (int i = 0; i < sx_modules[t].nin; i++, cables++)
            n += (size_t)snprintf(text + n, sizeof text - n, "cable src.sine m%d.%s\n", k,
                                  sx_modules[t].in[i]);
    }
    n += (size_t)snprintf(text + n, sizeof text - n, "cable m7.saw o.l\ncable m1.lp o.r\n");
    sx_graph *g = sx_patch_build(text, n, 48000.0, err, sizeof err);
    if (g == NULL)
        fprintf(stderr, "  the largest graph: %s\n", err);
    CHECK(g != NULL);
    if (g) {
        float l[256], r[256];
        clock_t t0 = clock();
        int ok = 1;
        for (int i = 0; i < 375; i++) {
            sx_graph_render(g, 128, l, r);
            for (int j = 0; j < 128; j++)
                ok &= isfinite(l[j]) && isfinite(r[j]);
        }
        double us = (double)(clock() - t0) / CLOCKS_PER_SEC * 1e6 / 375.0;
        printf("the largest graph: 64 modules, %d cables from one output: %.1f us per period\n",
               cables, us);
        CHECK(ok);
        sx_patch_free(g);
    }
    n += (size_t)snprintf(text + n, sizeof text - n, "module extra mixer\n");
    g = sx_patch_build(text, n, 48000.0, err, sizeof err);
    CHECK(g == NULL && strstr(err, "too many modules"));
    /* a megabyte of comments, then a working patch */
    n = (size_t)snprintf(text, sizeof text, "graph 1\n");
    while (n < (1u << 20))
        n += (size_t)snprintf(text + n, sizeof text - n, "# %d comment line, of no use\n", (int)n);
    n += (size_t)snprintf(text + n, sizeof text - n, "module o out\n");
    clock_t t0 = clock();
    g = sx_patch_build(text, n, 48000.0, err, sizeof err);
    double ms = (double)(clock() - t0) / CLOCKS_PER_SEC * 1e3;
    printf("a megabyte of comments: built in %.1f ms\n", ms);
    CHECK(g != NULL);
    sx_patch_free(g);
    /* a NUL inside, and a line longer than the parser takes */
    static const char nul[] = "graph 1\nmodule a\0vco\nmodule o out\n";
    g = sx_patch_build(nul, sizeof nul - 1u, 48000.0, err, sizeof err);
    sx_patch_free(g); /* refused or not, no crash: ASan watches */
    memset(text, 'x', 600);
    memcpy(text, "graph 1\nmodule ", 15);
    g = sx_patch_build(text, 600, 48000.0, err, sizeof err);
    CHECK(g == NULL && strstr(err, "line too long"));
}

static void test_command_flood(void)
{
    sx_engine *e = engine();
    int taken = 0, refused = 0;
    for (int i = 0; i < 10000; i++) {
        sx_cmd c = {SX_CMD_SR_SET, (uint32_t)i & 0xFFFFu, 0, 0.0f};
        int rc = sx_command(e, &c);
        taken += rc == SX_OK;
        refused += rc == SX_E_AGAIN;
    }
    sx_render(e, out, 128);
    sx_snapshot s;
    sx_snapshot_read(e, &s);
    printf("command flood: %d taken, %d refused with SX_E_AGAIN; the last taken applied (SR "
           "%04X)\n",
           taken, refused, s.sr);
    CHECK(taken == 256 && refused == 10000 - 256 && s.sr == 255);
    sx_cmd c = {SX_CMD_SR_SET, 0x1234, 0, 0.0f};
    CHECK(sx_command(e, &c) == SX_OK); /* room again after a period */
    sx_destroy(e);
}

/* the AUDIO-1 control program: a gate and C4 while row 0 is not zero */
static const uint16_t plays[] = {0xC8A0, 0x0020, 0xC8B0, 0x0021, 0xC8C0, 0x0022,
                                 0xC830, 0x8000, 0xC820, 0x6400, 0x9BA4, 0x0844,
                                 0x4330, 0x0114, 0x98B2, 0x98C3, 0x4300, 0x0114};

static void load(sx_engine *e)
{
    uint16_t n = sizeof plays / 2;
    sx_segment seg = {0x100, n, plays};
    sx_image img = {&seg, 1, 0x100, 0, {0}};
    sx_sha256 h;
    sx_sha256_init(&h);
    uint8_t hd[4] = {0x01, 0x00, 0x00, (uint8_t)n};
    sx_sha256_update(&h, hd, 4);
    for (uint16_t i = 0; i < n; i++) {
        uint8_t w[2] = {(uint8_t)(plays[i] >> 8), (uint8_t)plays[i]};
        sx_sha256_update(&h, w, 2);
    }
    sx_sha256_final(&h, img.sha256);
    CHECK(sx_load_image(e, &img) == SX_OK);
}

static void test_storms(void)
{
    static const char latch[] = "graph 1\nmodule osc vco\nmodule eg env\nmodule amp vca\n"
                                "module ec echo\nmodule o out\ncable dac.0 osc.pitch\n"
                                "cable gate.0 eg.gate\ncable osc.saw amp.in\ncable eg.out amp.cv\n"
                                "cable amp.out ec.in\ncable ec.l o.l\ncable ec.r o.r\n";
    sx_engine *e = engine();
    load(e);
    sx_keys_set(e, SX_KEYS_MIDI, 1u);
    int loaded = 0, again = 0, ok = 1;
    for (int p = 0; p < 3750; p++) { /* 10 s */
        int rc = sx_patch_load(e, p % 2 ? latch : tone, (p % 2 ? sizeof latch : sizeof tone) - 1u,
                               NULL, 0);
        loaded += rc == SX_OK;
        again += rc == SX_E_AGAIN;
        sx_render(e, out, 128);
        ok &= finite_out(128);
    }
    sx_snapshot s;
    sx_snapshot_read(e, &s);
    printf("patch storm: %d loads queued, %d told to wait, %u applied, output finite: %s\n", loaded,
           again, s.patch_seq - 1u, ok ? "yes" : "NO");
    CHECK(ok && loaded > 500 && loaded + again == 3750 && s.patch_seq > 500u);
    int homes = 0;
    for (int p = 0; p < 3750; p++) {
        sx_cmd c = {SX_CMD_RESET_HOME, 0, 0, 0.0f};
        homes += sx_command(e, &c) == SX_OK;
        sx_render(e, out, 128);
        ok &= finite_out(128);
    }
    sx_snapshot_read(e, &s);
    printf("HOME storm: %d HOMEs in 10 s, output finite: %s, faults %X\n", homes, ok ? "yes" : "NO",
           s.faults);
    CHECK(ok && (s.faults & SX_FAULT_PROGRAM_STALLED) == 0);
    sx_destroy(e);
}

static void test_denormals(void)
{
    static const char ring[] =
        "graph 1\nmodule n noise\nmodule f vcf\nmodule ec echo\nmodule o out\n"
        "param f res 1\nparam ec feedback 0.9\nparam ec mix 1\n"
        "cable n.white f.in\ncable f.lp ec.in\ncable ec.l o.l\n";
    char err[160];
    sx_graph *g = sx_patch_build(ring, sizeof ring - 1u, 48000.0, err, sizeof err);
    CHECK(g != NULL);
    if (!g)
        return;
    float l[480], r[480];
    for (int i = 0; i < 10; i++)
        sx_graph_render(g, 480, l, r);
    sx_graph_param(g, 0, 0, 0.0); /* the noise stops: everything rings down toward zero */
    double first = 0, last = 0;
    for (int s = 0; s < 60; s++) {
        clock_t t0 = clock();
        for (int i = 0; i < 100; i++)
            sx_graph_render(g, 480, l, r);
        double t = (double)(clock() - t0);
        if (s == 1)
            first = t;
        if (s == 59)
            last = t;
    }
    printf("ringing down to nothing for 60 s: the last second took %.2f x the second\n",
           last / (first > 0 ? first : 1));
    CHECK(last < 3.0 * first + 1000.0); /* no denormal slow-down */
    sx_patch_free(g);
}

static atomic_int stop;
static atomic_int torn;

static void *reader(void *arg)
{
    sx_engine *e = arg;
    uint64_t last_seq = 0;
    while (!atomic_load(&stop)) {
        sx_snapshot s;
        if (sx_snapshot_read(e, &s) != SX_OK)
            continue;
        if (s.seq < last_seq || (s.seq && s.frames != s.seq * 128u))
            atomic_fetch_add(&torn, 1);
        last_seq = s.seq;
    }
    return NULL;
}

static void test_snapshot_under_load(void)
{
    sx_engine *e = engine();
    load(e);
    pthread_t t;
    pthread_create(&t, NULL, reader, e);
    for (int p = 0; p < 3750; p++) {
        if (p % 100 == 0)
            sx_keys_set(e, SX_KEYS_TOUCH, (uint64_t)(p / 100) & 1u);
        sx_render(e, out, 128);
    }
    atomic_store(&stop, 1);
    pthread_join(t, NULL);
    printf("snapshots read from another thread through 3,750 periods: %d torn or out of order\n",
           atomic_load(&torn));
    CHECK(atomic_load(&torn) == 0);
    sx_destroy(e);
}

int main(void)
{
    test_hostile_parameters();
    test_huge_and_strange_texts();
    test_command_flood();
    test_storms();
    test_denormals();
    test_snapshot_under_load();
    printf("test_adversarial: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
