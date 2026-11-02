/* test_graph.c: the patch graph runtime and its text loader (PM-05, PM-06; DSP-12, DSP-17,
 * DSP-22, PRG-04's retrigger).
 *
 *   - a one-voice graph renders bit-identically to VS-10's hand-wired voice (the refactor
 *     changed nothing it did not mean to)
 *   - loader errors name the line; 10^6 mutated texts never crash, leak or hang (run under ASan
 *     and UBSan by `make sanitize`; SX_FUZZ sets the count)
 *   - a cable loop renders finite; path_to_out is right with and without a path
 *   - a gate that drops and rises within one frame restarts the envelope
 *   - DSP-12: seeded random graphs with extreme CV stay finite, and the safety chain holds the
 *     ceiling on them
 *   - a patch change in the engine crossfades: no step at the swap
 *   - 20 cables of a voice patch fit the audio budget (CPU time per period recorded)
 */
#include "graph.h"
#include "patch.h"
#include "safety.h"
#include "seastones.h"
#include "voice.h"

#include <math.h>
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

#define FS 48000.0
#define N 48000u

static float a[N], l[N], r[N];

static const char voice1[] = "graph 1\n"
                             "module osc vco\nmodule eg env\nmodule amp vca\nmodule o out\n"
                             "cable dac.0 osc.pitch\ncable gate.0 eg.gate\n"
                             "cable osc.saw amp.in\ncable eg.out amp.cv\ncable amp.out o.l\n";

static sx_graph *build(const char *t, char *err)
{
    return sx_patch_build(t, strlen(t), FS, err, 160);
}

/* events: (frame, source, volts), applied at their frames to both renderers */
typedef struct {
    uint32_t frame, src;
    float v;
} ev;

static void test_equivalence(void)
{
    static const ev evs[] = {{100, 0, 4.0f},    {100, 16, 5.0f},   {9000, 0, 4.25f},
                             {12000, 16, 0.0f}, {12000, 16, 5.0f}, {20000, 0, 2.0f},
                             {30000, 16, 0.0f}, {41000, 0, 7.5f},  {41010, 16, 5.0f}};
    char err[160];
    sx_graph *g = build(voice1, err);
    CHECK(g != NULL);
    if (!g)
        return;
    sx_voice v;
    sx_voice_init(&v, FS);
    uint32_t pos = 0;
    for (size_t i = 0; i <= sizeof evs / sizeof evs[0]; i++) {
        uint32_t f = i < sizeof evs / sizeof evs[0] ? evs[i].frame : N;
        if (f > pos) {
            sx_voice_render(&v, f - pos, a + pos);
            sx_graph_render(g, f - pos, l + pos, r + pos);
            pos = f;
        }
        if (i == sizeof evs / sizeof evs[0])
            break;
        if (evs[i].src == 0)
            sx_voice_pitch(&v, (double)evs[i].v);
        else
            sx_voice_gate(&v, (double)evs[i].v);
        sx_graph_event(g, evs[i].src, evs[i].v);
    }
    /* equal as values: the graph's sum into the bus turns a -0.0 into +0.0, nothing else */
    int same = 1;
    for (uint32_t i = 0; i < N; i++)
        same &= a[i] == l[i] && l[i] == r[i];
    for (uint32_t i = 0; i < N && !same; i++)
        if (a[i] != l[i]) {
            fprintf(stderr, "  first difference at frame %u: voice %.9g graph %.9g\n", i,
                    (double)a[i], (double)l[i]);
            break;
        }
    double pk = 0;
    for (uint32_t i = 0; i < N; i++)
        pk = fabs((double)a[i]) > pk ? fabs((double)a[i]) : pk;
    printf("one-voice graph vs the VS-10 voice: %s (peak %.3f)\n",
           same ? "identical (as values)" : "DIFFERENT", pk);
    CHECK(same && pk > 0.2);
    sx_patch_free(g);
}

static void test_errors(void)
{
    static const struct {
        const char *text, *want;
    } cases[] = {
        {"module a vco\n", "line 1: the first line must be 'graph 1'"},
        {"graph 1\nmodule a vco\nmodule a vcf\n", "line 3: two modules have the same name: a"},
        {"graph 1\nmodule a moog\n", "line 2: no such module type: moog"},
        {"graph 1\nmodule a vco\nparam a tune x\n", "line 3: not a number: x"},
        {"graph 1\nmodule a vco\nparam a tone 1\n", "line 3: no such parameter: tone"},
        {"graph 1\nmodule a vco\ncable dac.16 a.pitch\n", "line 3: no such output: dac.16"},
        {"graph 1\nmodule a vco\ncable dac.0 a.pitch\ncable dac.1 a.pitch\n",
         "line 4: that input already has a cable: a.pitch"},
        {"graph 1\nmodule a vco\ncable a.saw a.saw\n", "line 3: no such input: a.saw"},
        {"graph 1\nend\nmodule a vco\n", "line 3: nothing may follow 'end'"},
        {"graph 1\nmodule A vco\n", "line 2: a module name is 1-23 of a-z, 0-9 and _: A"},
        {"", "empty: the first line must be 'graph 1'"},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        char err[160];
        sx_graph *g = build(cases[i].text, err);
        int ok = g == NULL && strstr(err, cases[i].want) != NULL;
        if (!ok)
            fprintf(stderr, "  case %zu: got '%s', want '%s'\n", i, err, cases[i].want);
        CHECK(ok);
        sx_patch_free(g);
    }
    char err[160];
    sx_graph *g = build("graph 1\nmodule a vco\nparam a tune 99\n# fine\nend\n", err);
    CHECK(g && g->m[0].par[0] == 5.0); /* clamped to the declared range */
    sx_patch_free(g);
    char big[8192] = "graph 1\n";
    for (int k = 0; k < 65; k++)
        snprintf(big + strlen(big), sizeof big - strlen(big), "module m%d mixer\n", k);
    g = build(big, err);
    CHECK(g == NULL && strstr(err, "too many modules"));
    printf("loader errors: %zu cases name their line\n", sizeof cases / sizeof cases[0]);
}

static uint32_t rng = 1974u;
static uint32_t rnd(void)
{
    rng ^= rng << 13;
    rng ^= rng >> 17;
    rng ^= rng << 5;
    return rng;
}

static void test_fuzz(void)
{
    const char *env = getenv("SX_FUZZ");
    long count = env ? atol(env) : 1000000L;
    static const char alphabet[] = "abcdgmoprtuelvfnixs.0123456789 \n#-_";
    char buf[512];
    size_t base = strlen(voice1);
    long built = 0;
    clock_t t0 = clock();
    for (long i = 0; i < count; i++) {
        memcpy(buf, voice1, base);
        size_t n = base;
        int edits = 1 + (int)(rnd() % 6);
        for (int k = 0; k < edits; k++) {
            size_t at = rnd() % (n + 1);
            uint32_t op = rnd() % 3;
            char ch = alphabet[rnd() % (sizeof alphabet - 1)];
            if (op == 0 && at < n)
                buf[at] = ch;
            else if (op == 1 && at < n) {
                memmove(buf + at, buf + at + 1, n - at - 1);
                n--;
            } else if (n + 1 < sizeof buf) {
                memmove(buf + at + 1, buf + at, n - at);
                buf[at] = ch;
                n++;
            }
        }
        if (rnd() % 64 == 0) /* sometimes binary junk */
            for (size_t k = 0; k < n; k++)
                buf[k] = (char)(rnd() & 0xFF);
        char err[160];
        sx_graph *g = sx_patch_build(buf, n, FS, err, sizeof err);
        if (g) {
            built++;
            float o1[64], o2[64];
            sx_graph_event(g, rnd() % SX_G_NSRC, (float)((int)(rnd() % 40) - 10));
            sx_graph_render(g, 64, o1, o2);
            for (int k = 0; k < 64; k++)
                CHECK(isfinite(o1[k]) && isfinite(o2[k]));
        }
        sx_patch_free(g);
    }
    printf("loader fuzz: %ld mutated texts (seed 1974), %ld built and rendered, %.1f s\n", count,
           built, (double)(clock() - t0) / CLOCKS_PER_SEC);
}

static void test_loop_and_path(void)
{
    char err[160];
    /* a feedback loop: the mixer feeds a filter that feeds the mixer */
    sx_graph *g = build("graph 1\nmodule n noise\nmodule m mixer\nmodule f vcf\nmodule o out\n"
                        "param f res 1\nparam m l2 2\n"
                        "cable n.white m.in1\ncable f.lp m.in2\ncable m.out f.in\ncable f.lp o.l\n",
                        err);
    CHECK(g && g->feedback);
    if (g) {
        int finite = 1;
        for (int k = 0; k < 200; k++) {
            sx_graph_render(g, 240, l, r);
            for (int i = 0; i < 240; i++)
                finite &= isfinite(l[i]) && fabsf(l[i]) < 100.0f;
        }
        CHECK(finite);
        CHECK(!g->path_to_out); /* noise is not a D/A or gate line */
        sx_patch_free(g);
    }
    g = build(voice1, err);
    CHECK(g && g->path_to_out);
    sx_patch_free(g);
    g = build("graph 1\nmodule osc vco\nmodule o out\ncable dac.0 osc.pitch\n", err);
    CHECK(g && !g->path_to_out); /* nothing reaches the out */
    sx_patch_free(g);
    printf("a cable loop renders finite; path_to_out true and false as it should be\n");
}

static void test_retrigger_in_one_frame(void)
{
    char err[160];
    sx_graph *g = build(voice1, err);
    if (!g)
        return;
    sx_graph_event(g, 0, 4.0f);
    sx_graph_event(g, 16, 5.0f);
    sx_graph_render(g, 9600, l, r); /* 200 ms: past the 2 ms attack, into sustain */
    sx_gmod *eg = &g->m[1];
    uint32_t rises = g->rises;
    sx_graph_event(g, 16, 0.0f); /* a stolen voice: down and up at the same frame */
    sx_graph_event(g, 0, 5.0f);
    sx_graph_event(g, 16, 5.0f);
    CHECK(g->rises == rises + 1 && eg->u.env.stage == SX_ENV_ATTACK);
    printf("a gate down and up within one frame restarts the envelope (stage %d)\n",
           eg->u.env.stage);
    sx_patch_free(g);
}

static const char *const types[] = {"vco",   "vcf",  "vca",   "env",  "lfo",
                                    "noise", "slew", "mixer", "echo", "out"};

static void test_property(void)
{
    const char *env = getenv("SX_GRAPHS");
    long count = env ? atol(env) : 1000L;
    sx_safety s;
    double worst = 0, worst_tp = 0;
    int finite = 1;
    for (long gi = 0; gi < count; gi++) {
        char text[4096] = "graph 1\n";
        int nm = 3 + (int)(rnd() % 14), echoes = 0;
        int ty[20];
        for (int k = 0; k < nm; k++) {
            ty[k] = k == nm - 1 ? SX_M_OUT : (int)(rnd() % (SX_M_NTYPES - 1));
            if (ty[k] == SX_M_ECHO && (rnd() % 2 || ++echoes > (int)SX_G_MAXECHO))
                ty[k] = SX_M_VCF;
            snprintf(text + strlen(text), sizeof text - strlen(text), "module m%d %s\n", k,
                     types[ty[k]]);
            const sx_mdesc *d = &sx_modules[ty[k]];
            for (int p = 0; p < d->npar; p++) { /* parameters anywhere, also out of range */
                double lo = d->par[p].min, hi = d->par[p].max;
                double v = lo + (hi - lo) * ((double)(rnd() % 1201) / 1000.0 - 0.1);
                snprintf(text + strlen(text), sizeof text - strlen(text), "param m%d %s %.6g\n", k,
                         d->par[p].name, v);
            }
        }
        for (int k = 0; k < nm; k++) { /* random cables, fed from sources and other modules */
            const sx_mdesc *d = &sx_modules[ty[k]];
            for (int in = 0; in < d->nin; in++) {
                if (rnd() % 3 == 0)
                    continue;
                int from = (int)(rnd() % (unsigned)(nm + 2));
                if (from >= nm || sx_modules[ty[from]].nout == 0)
                    snprintf(text + strlen(text), sizeof text - strlen(text),
                             "cable %s.%u m%d.%s\n", rnd() % 2 ? "dac" : "gate", rnd() % 16, k,
                             d->in[in]);
                else
                    snprintf(text + strlen(text), sizeof text - strlen(text),
                             "cable m%d.%s m%d.%s\n", from,
                             sx_modules[ty[from]].out[rnd() % sx_modules[ty[from]].nout], k,
                             d->in[in]);
            }
        }
        char err[160];
        sx_graph *g = sx_patch_build(text, strlen(text), FS, err, sizeof err);
        if (g == NULL) {
            fprintf(stderr, "  graph %ld did not build: %s\n", gi, err);
            CHECK(g != NULL);
            continue;
        }
        sx_safety_init(&s, FS);
        sx_safety_start(&s);
        for (int blk = 0; blk < 40; blk++) { /* 0.2 s, CV changing every block, extreme too */
            for (int e = 0; e < 4; e++) {
                uint32_t src = rnd() % SX_G_NSRC;
                float v = rnd() % 8 == 0 ? (rnd() % 2 ? 1e9f : -1e9f)
                                         : (float)((double)(rnd() % 2049) / 100.0 - 10.24);
                sx_graph_event(g, src, v);
            }
            sx_graph_render(g, 240, l, r);
            for (int i = 0; i < 240; i++)
                finite &= isfinite(l[i]) && isfinite(r[i]);
            sx_safety_process(&s, l, 240);
            for (int i = 0; i < 240; i++) {
                double v = fabs((double)l[i]);
                worst = v > worst ? v : worst;
            }
        }
        sx_patch_free(g);
    }
    (void)worst_tp;
    double ceil = sx_db_to_lin(SX_HARD_MAX_DBFS);
    printf("DSP-12: %ld random graphs (seed 1974), extreme CV: finite %s, peak after the chain "
           "%.4f (ceiling %.4f)\n",
           count, finite ? "yes" : "NO", worst, ceil);
    CHECK(finite && worst <= ceil + 1e-6);
}

static sx_engine *engine_with(const char *patch)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    sx_engine *e = sx_create(&c);
    if (e && patch)
        CHECK(sx_patch_load(e, patch, strlen(patch), NULL, 0) == SX_OK);
    return e;
}

static void test_crossfade(void)
{
    /* two patches making the same steady tone from the same noise-free source: one through a
     * saw, one through a pulse; the swap is a 5 ms crossfade, so no sample-to-sample step is
     * bigger than either patch's own largest step */
    static const char *drone =
        "graph 1\nmodule osc vco\nmodule amp vca\nmodule o out\nparam amp bias 10\n"
        "cable dac.0 osc.pitch\ncable osc.%s amp.in\ncable amp.out o.l\n";
    char p1[512], p2[512];
    snprintf(p1, sizeof p1, drone, "sine");
    snprintf(p2, sizeof p2, drone, "tri");
    sx_engine *e = engine_with(p1);
    if (!e)
        return;
    static float buf[2 * 48000];
    sx_render(e, buf, 24000); /* past the 200 ms fade-in */
    sx_snapshot s;
    sx_snapshot_read(e, &s);
    uint32_t seq = s.patch_seq;
    CHECK(sx_patch_load(e, p2, strlen(p2), NULL, 0) == SX_OK);
    CHECK(sx_patch_load(e, p2, strlen(p2), NULL, 0) == SX_E_AGAIN); /* one at a time */
    sx_render(e, buf, 9600);
    sx_snapshot_read(e, &s);
    CHECK(s.patch_seq == seq + 1 && !s.fading);
    double step = 0;
    for (int i = 1; i < 9600; i++) {
        double d = fabs((double)buf[2 * i] - (double)buf[2 * i - 2]);
        step = d > step ? d : step;
    }
    /* a 0 V (16 Hz) sine or triangle at full scale moves at most ~0.0021 per sample */
    printf("patch change: patch_seq %u -> %u, largest sample step %.5f (5 ms crossfade)\n", seq,
           s.patch_seq, step);
    CHECK(step < 0.01);
    sx_destroy(e);
}

static void test_budget(void)
{
    /* the default-style four-voice patch: 20 cables or more */
    static const char *v =
        "module osc%d vco\nmodule f%d vcf\nmodule eg%d env\nmodule amp%d vca\n"
        "cable dac.%d osc%d.pitch\ncable dac.%d eg%d.gate\ncable osc%d.saw f%d.in\n"
        "cable f%d.lp amp%d.in\ncable eg%d.out amp%d.cv\ncable amp%d.out mix.in%d\n"
        "cable dac.8 f%d.cutoff\n";
    char text[8192] = "graph 1\nmodule mix mixer\nmodule e echo\nmodule o out\n"
                      "cable mix.out e.in\ncable e.l o.l\ncable e.r o.r\n";
    int cables = 3;
    for (int i = 0; i < 4; i++) {
        snprintf(text + strlen(text), sizeof text - strlen(text), v, i, i, i, i, i, i, i + 4, i, i,
                 i, i, i, i, i, i, i + 1, i);
        cables += 7;
    }
    char err[160];
    sx_graph *g = build(text, err);
    CHECK(g != NULL);
    if (!g)
        return;
    for (int i = 0; i < 4; i++) {
        sx_graph_event(g, (uint32_t)i, 3.0f + 0.3f * (float)i);
        sx_graph_event(g, (uint32_t)(4 + i), 5.0f);
    }
    clock_t t0 = clock();
    int periods = 3750; /* 10 s at 128 frames */
    for (int k = 0; k < periods; k++) {
        if (k % 50 == 0)
            sx_graph_event(g, 8, (float)(k % 400) / 100.0f); /* the cutoff lane moving */
        sx_graph_render(g, 128, l, r);
    }
    double us = (double)(clock() - t0) / CLOCKS_PER_SEC * 1e6 / periods;
    printf("budget: 4 voices with filters and echo, %d cables: %.1f us per 128-frame period "
           "(the period is 2667 us)\n",
           cables, us);
    CHECK(cables >= 20 && us < 0.5 * 2667.0);
    sx_patch_free(g);
    /* PM-04: the same with the FDN reverb in place of the echo */
    char rev[8192];
    const char *at = strstr(text, "module e echo\n");
    snprintf(rev, sizeof rev, "%.*smodule e reverb\n%s", (int)(at - text), text,
             at + strlen("module e echo\n"));
    g = build(rev, err);
    CHECK(g != NULL);
    if (!g)
        return;
    for (int i = 0; i < 4; i++) {
        sx_graph_event(g, (uint32_t)i, 3.0f + 0.3f * (float)i);
        sx_graph_event(g, (uint32_t)(4 + i), 5.0f);
    }
    t0 = clock();
    for (int k = 0; k < periods; k++)
        sx_graph_render(g, 128, l, r);
    double us_rev = (double)(clock() - t0) / CLOCKS_PER_SEC * 1e6 / periods;
    printf("budget: the same with the FDN reverb instead of the echo: %.1f us per period\n",
           us_rev);
    CHECK(us_rev < 0.5 * 2667.0);
    sx_patch_free(g);
}

int main(void)
{
    test_equivalence();
    test_errors();
    test_fuzz();
    test_loop_and_path();
    test_retrigger_in_one_frame();
    test_property();
    test_crossfade();
    test_budget();
    printf("test_graph: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
