/* sx-render: headless offline render (VS-12; research, golden renders, QA).
 *
 *   sx-render --image rig.img.json --script keys.txt --seconds S
 *             [--rate 48000] [--period 128] [--word-bits 12] [--rig-dac dac.md]
 *             [--graph PATCH.graph] [--sr HEX] [--auth 0..3]
 *             [--wav OUT.wav] [--features OUT.json] [--stats]
 *             [--trace-out TRACE] [--replay TRACE]          (test profile only, VS-26)
 *   sx-render --modules                                   the module registry (modules.json)
 *
 * Runs the real engine (libseastones: CPU, devices, DSP, safety chain) with no audio device and
 * no clock but the sample count, so the output is a pure function of the image, the script and
 * the options. Prints `sha256 <hex>` of the float32 PCM (interleaved L R, little-endian): the
 * golden-render identity (QA-STRATEGY 13.2). Golden renders are that hash plus the feature JSON,
 * never audio.
 *
 * --wav writes a listening copy, but ONLY outside every git work tree, or under the work tree's
 * git-ignored build/ directory (VS-12 AC; RE-1). Anywhere else it refuses (exit 3) and writes
 * nothing. A tampered image is refused with `image_hash_mismatch` (exit 4) and renders nothing.
 *
 * Replay mode (VS-26, QA request 1): --trace-out records every D/A and gate write as the DSP
 * applied it, `frame dev ch value` (seastones.trace/1); --replay feeds such a trace to the DSP with
 * the CPU not running, through the same seam (sx_test_replay), so DSP tests need no CPU. A replay
 * of a recorded run renders bit-identically to the run. --image is optional with --replay.
 *
 * --rig-dac reads the D/A model (word_bits, range_v, output_hz, strobe_hz) from a rig data file
 * (src/program/rig/dac.md; MACH-3, PM-07); --word-bits overrides its word_bits. --graph loads a
 * seastones.graph/1 patch (sxpatch compiles them) before the first period; --sr sets the switch
 * register (the routine the program plays, rig.s); --auth the authenticity mode.
 *
 * Script lines (times in seconds; applied at the first period that starts at or after them):
 *   T keys HEX64      key bitmap (bit k = key k), as the MIDI source
 *   T speed P         speed position (0 RUN .. 4 CRAWL, 5 SINGLE)
 *   T step            one STEP (SINGLE)
 *   T mute 0|1        mute
 *   T home            HOME
 *   T sr HEX          switch register
 *   T graph FILE      load a patch (crossfaded in at the next period)
 *   T auth N          authenticity mode (0 authentic, 1 analog, 2 strobed, 3 jitter)
 *   T volume DB       visitor volume
 *   T ceiling DB      staff ceiling
 *   T score FILE      deposit a score table (seastones.table/1, sxscore.compile) at X'2000'
 *   # comment
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "seastones.h"
#include "sha256.h"
#if defined(SX_TEST_HOOKS)
#include "seastones_test.h"
#endif

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* --- the image (seastones.image/1 as sxasm writes it; the Python validator is strict) --- */

static char *slurp(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL)
        return NULL;
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return NULL;
    }
    long n = ftell(f);
    rewind(f);
    char *b = n >= 0 ? malloc((size_t)n + 1u) : NULL;
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) {
        free(b);
        b = NULL;
    }
    fclose(f);
    if (b) {
        b[n] = 0;
        if (len)
            *len = (size_t)n;
    }
    return b;
}

/* next JSON string after p; returns a pointer past it and copies at most n-1 chars */
static const char *jstring(const char *p, char *out, size_t n)
{
    p = strchr(p, '"');
    if (p == NULL)
        return NULL;
    p++;
    size_t i = 0;
    while (*p && *p != '"') {
        if (i + 1 < n)
            out[i++] = *p;
        p++;
    }
    out[i] = 0;
    return *p ? p + 1 : NULL;
}

static int hexval(int c)
{
    return c >= '0' && c <= '9'   ? c - '0'
           : c >= 'a' && c <= 'f' ? c - 'a' + 10
           : c >= 'A' && c <= 'F' ? c - 'A' + 10
                                  : -1;
}

#define MAXSEG 64
static uint16_t img_words[32768];
static sx_segment img_segs[MAXSEG];

static int load_image_json(const char *path, sx_image *img)
{
    char *t = slurp(path, NULL);
    if (t == NULL)
        return -1;
    memset(img, 0, sizeof *img);
    char s[80];
    const char *p;
    if ((p = strstr(t, "\"entry_pc\"")) && jstring(p + 10, s, sizeof s))
        img->entry_pc = (uint16_t)strtoul(s, NULL, 16);
    if ((p = strstr(t, "\"entry_psw\"")) && jstring(p + 11, s, sizeof s))
        img->entry_psw = (uint16_t)strtoul(s, NULL, 16);
    if ((p = strstr(t, "\"sha256\"")) && jstring(p + 8, s, sizeof s) && strlen(s) == 64)
        for (int i = 0; i < 32; i++)
            img->sha256[i] = (uint8_t)(hexval(s[2 * i]) << 4 | hexval(s[2 * i + 1]));
    uint32_t nw = 0, ns = 0;
    p = strstr(t, "\"segments\"");
    while (p && (p = strstr(p, "\"addr\"")) != NULL && ns < MAXSEG) {
        p = jstring(p + 6, s, sizeof s);
        if (p == NULL)
            break;
        img_segs[ns].addr = (uint16_t)strtoul(s, NULL, 16);
        img_segs[ns].words = img_words + nw;
        const char *w = strstr(p, "\"words\"");
        const char *end = w ? strchr(w, ']') : NULL;
        if (w == NULL || end == NULL)
            break;
        w += 7;
        uint16_t count = 0;
        while ((w = strchr(w, '"')) != NULL && w < end && nw < 32768) {
            w = jstring(w, s, sizeof s);
            img_words[nw++] = (uint16_t)strtoul(s, NULL, 16);
            count++;
        }
        img_segs[ns].nwords = count;
        ns++;
        p = end;
    }
    img->segments = img_segs;
    img->nsegments = ns;
    free(t);
    return ns ? 0 : -1;
}

/* --- the D/A model from rig data (src/program/rig/dac.md: key: value, then a blank line) ---- */

static int read_rig_dac(const char *path, sx_config *c)
{
    char *t = slurp(path, NULL);
    if (t == NULL) {
        fprintf(stderr, "sx-render: %s: %s\n", path, strerror(errno));
        return -1;
    }
    for (char *ln = t; ln && *ln && *ln != '\n';) {
        char *next = strchr(ln, '\n');
        if (next)
            *next++ = 0;
        char key[32];
        double v;
        if (sscanf(ln, "%31[a-z_]: %lf", key, &v) == 2) {
            if (strcmp(key, "word_bits") == 0)
                c->dac_word_bits = (uint32_t)v;
            else if (strcmp(key, "range_v") == 0)
                c->dac_range_v = (float)v;
            else if (strcmp(key, "output_hz") == 0)
                c->dac_output_hz = (float)v;
            else if (strcmp(key, "strobe_hz") == 0)
                c->dac_strobe_hz = (float)v;
        }
        ln = next;
    }
    free(t);
    return 0;
}

/* --- where a listening copy may go -------------------------------------------------------- */

static int gitignore_has_build(const char *root)
{
    char path[PATH_MAX + 16];
    snprintf(path, sizeof path, "%s/.gitignore", root);
    char *t = slurp(path, NULL);
    int ok = 0;
    for (char *ln = t ? strtok(t, "\n") : NULL; ln; ln = strtok(NULL, "\n")) {
        size_t n = strlen(ln);
        while (n && (ln[n - 1] == '\r' || ln[n - 1] == ' '))
            ln[--n] = 0;
        if (strcmp(ln, "build/") == 0 || strcmp(ln, "/build/") == 0 || strcmp(ln, "build") == 0)
            ok = 1;
    }
    free(t);
    return ok;
}

/* 0 if `out` may be written, else prints why and returns 3 */
static int check_wav_path(const char *out)
{
    char dir[PATH_MAX], real[PATH_MAX];
    snprintf(dir, sizeof dir, "%s", out);
    char *slash = strrchr(dir, '/');
    if (slash == NULL)
        snprintf(dir, sizeof dir, ".");
    else if (slash == dir)
        dir[1] = 0;
    else
        *slash = 0;
    if (realpath(dir, real) == NULL) {
        fprintf(stderr, "sx-render: %s: directory does not exist\n", dir);
        return 3;
    }
    char probe[PATH_MAX];
    snprintf(probe, sizeof probe, "%s", real);
    for (;;) {
        char git[PATH_MAX + 8];
        struct stat st;
        snprintf(git, sizeof git, "%s/.git", probe);
        if (stat(git, &st) == 0) { /* inside a work tree whose root is `probe` */
            char build[PATH_MAX + 8];
            snprintf(build, sizeof build, "%s/build", probe);
            size_t bl = strlen(build);
            int under = strncmp(real, build, bl) == 0 && (real[bl] == 0 || real[bl] == '/');
            if (under && gitignore_has_build(probe))
                return 0;
            fprintf(stderr,
                    "sx-render: refusing to write %s: it is inside the git work tree %s; audio "
                    "may go only under its git-ignored build/ or outside any work tree\n",
                    out, probe);
            return 3;
        }
        char *s = strrchr(probe, '/');
        if (s == NULL || s == probe)
            return 0; /* reached / without a work tree */
        *s = 0;
    }
}

static void put32(FILE *f, uint32_t v)
{
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24)};
    fwrite(b, 1, 4, f);
}

static void put16(FILE *f, uint16_t v)
{
    uint8_t b[2] = {(uint8_t)v, (uint8_t)(v >> 8)};
    fwrite(b, 1, 2, f);
}

static int write_wav(const char *path, const float *pcm, uint64_t frames, uint32_t rate)
{
    FILE *f = fopen(path, "wb");
    if (f == NULL)
        return -1;
    uint32_t data = (uint32_t)(frames * 8u);
    fwrite("RIFF", 1, 4, f);
    put32(f, 36u + data);
    fwrite("WAVEfmt ", 1, 8, f);
    put32(f, 16);
    put16(f, 3); /* IEEE float */
    put16(f, 2);
    put32(f, rate);
    put32(f, rate * 8u);
    put16(f, 8);
    put16(f, 32);
    fwrite("data", 1, 4, f);
    put32(f, data);
    for (uint64_t i = 0; i < 2 * frames; i++) {
        uint32_t u;
        memcpy(&u, &pcm[i], 4);
        put32(f, u);
    }
    return fclose(f);
}

/* --- features: what a golden render keeps instead of audio ------------------------------- */

static double goertzel_db(const float *x, uint32_t n, uint32_t stride, double f, double fs)
{
    double w = 2.0 * cos(2.0 * 3.14159265358979323846 * f / fs), s1 = 0, s2 = 0;
    for (uint32_t i = 0; i < n; i++) {
        double s0 = (double)x[i * stride] + w * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    double p = s1 * s1 + s2 * s2 - w * s1 * s2;
    double a = 2.0 * sqrt(p > 0 ? p : 0) / (double)n;
    return a > 1e-10 ? 20.0 * log10(a) : -200.0;
}

static void write_features(FILE *f, const float *pcm, uint64_t frames, uint32_t rate,
                           const char *hex)
{
    static const double bands[7] = {125, 250, 500, 1000, 2000, 4000, 8000};
    uint32_t win = rate / 10u;
    fprintf(f, "{\n  \"format\": \"seastones.render-features/1\",\n");
    fprintf(f, "  \"sha256\": \"%s\",\n  \"rate\": %u,\n  \"frames\": %llu,\n", hex, rate,
            (unsigned long long)frames);
    fprintf(f, "  \"window_s\": 0.1,\n  \"windows\": [\n");
    double gpk = 0;
    uint64_t gpos = 0;
    for (uint64_t w0 = 0; w0 + win <= frames; w0 += win) {
        const float *x = pcm + 2 * w0;
        double ss = 0, pk = 0, first = -1, last = -1;
        int zc = 0;
        for (uint32_t i = 0; i < win; i++) {
            double v = x[2 * i];
            ss += v * v;
            if (fabs(v) > pk)
                pk = fabs(v);
            if (fabs(v) > gpk) {
                gpk = fabs(v);
                gpos = w0 + i;
            }
            if (i && x[2 * (i - 1)] < 0.0f && x[2 * i] >= 0.0f) {
                double t =
                    (double)(i - 1) + (double)(-x[2 * (i - 1)] / (x[2 * i] - x[2 * (i - 1)]));
                if (first < 0)
                    first = t;
                last = t;
                zc++;
            }
        }
        double rms = sqrt(ss / win);
        double rdb = rms > 1e-10 ? 20.0 * log10(rms) : -200.0;
        double f0 = (rdb > -60.0 && zc > 1) ? (double)(zc - 1) * rate / (last - first) : 0.0;
        fprintf(f, "    {\"t\": %.1f, \"rms_dbfs\": %.1f, \"peak_dbfs\": %.1f, \"f0_hz\": %.1f, ",
                (double)w0 / rate, rdb, pk > 1e-10 ? 20.0 * log10(pk) : -200.0, f0);
        fprintf(f, "\"bands_db\": [");
        for (int b = 0; b < 7; b++)
            fprintf(f, "%s%.1f", b ? ", " : "", goertzel_db(x, win, 2, bands[b], rate));
        fprintf(f, "]}%s\n", w0 + 2 * win <= frames ? "," : "");
    }
    fprintf(f, "  ],\n  \"peak\": {\"t\": %.4f, \"dbfs\": %.2f}\n}\n", (double)gpos / rate,
            gpk > 1e-10 ? 20.0 * log10(gpk) : -200.0);
}

/* --- traces (VS-26) ----------------------------------------------------------------------- */

#if defined(SX_TEST_HOOKS)
#define MAXTRACE (1u << 21)
static sx_trace_ev *trace;
static uint32_t ntrace;

static void tap(void *ctx, const sx_trace_ev *ev)
{
    (void)ctx;
    if (ntrace < MAXTRACE)
        trace[ntrace++] = *ev;
}

static int save_trace(const char *path)
{
    FILE *f = fopen(path, "w");
    if (f == NULL)
        return -1;
    fprintf(f, "# seastones.trace/1: frame dev ch value (hex dev, ch, value)\n");
    for (uint32_t i = 0; i < ntrace; i++)
        fprintf(f, "%llu %02X %X %04X\n", (unsigned long long)trace[i].frame, trace[i].dev,
                trace[i].ch, trace[i].val);
    return fclose(f);
}

static int load_trace(const char *path)
{
    FILE *f = fopen(path, "r");
    if (f == NULL)
        return -1;
    char line[128];
    while (fgets(line, sizeof line, f) && ntrace < MAXTRACE) {
        unsigned long long fr;
        unsigned dev, ch, val;
        if (line[0] == '#' || sscanf(line, "%llu %x %x %x", &fr, &dev, &ch, &val) != 4)
            continue;
        trace[ntrace++] = (sx_trace_ev){fr, (uint8_t)dev, (uint8_t)ch, (uint16_t)val};
    }
    fclose(f);
    return 0;
}
#endif

/* --- the script ---------------------------------------------------------------------------- */

typedef struct {
    uint64_t frame;
    char what[8];
    unsigned long long arg;
    double num;
    char text[256];
} event;

static event evs[4096];
static int nev;

static int load_script(const char *path, uint32_t rate)
{
    FILE *f = fopen(path, "r");
    if (f == NULL)
        return -1;
    char line[256];
    while (fgets(line, sizeof line, f) && nev < 4096) {
        double t;
        char what[16] = "", arg[256] = "0";
        if (line[0] == '#' || sscanf(line, "%lf %15s %255s", &t, what, arg) < 2)
            continue;
        evs[nev].frame = (uint64_t)llround(t * rate);
        snprintf(evs[nev].what, sizeof evs[nev].what, "%s", what);
        int hex = strcmp(what, "keys") == 0 || strcmp(what, "sr") == 0;
        evs[nev].arg = strtoull(arg, NULL, hex ? 16 : 10);
        evs[nev].num = atof(arg);
        snprintf(evs[nev].text, sizeof evs[nev].text, "%s", arg);
        nev++;
    }
    fclose(f);
    return 0;
}

static int load_graph(sx_engine *e, const char *path)
{
    size_t n = 0;
    char *t = slurp(path, &n);
    if (t == NULL) {
        fprintf(stderr, "sx-render: %s: %s\n", path, strerror(errno));
        return -1;
    }
    char err[256];
    int rc = sx_patch_load(e, t, n, err, sizeof err);
    free(t);
    if (rc != SX_OK) {
        fprintf(stderr, "sx-render: %s: %s\n", path, err);
        return -1;
    }
    return 0;
}

static uint16_t tbl[12288];

static int load_score(sx_engine *e, const char *path)
{
    FILE *f = fopen(path, "r");
    if (f == NULL) {
        fprintf(stderr, "sx-render: %s: %s\n", path, strerror(errno));
        return -1;
    }
    char line[512];
    uint32_t n = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#')
            continue;
        for (char *p = strtok(line, " \t\r\n"); p && n < 12288u; p = strtok(NULL, " \t\r\n"))
            tbl[n++] = (uint16_t)strtoul(p, NULL, 16);
    }
    fclose(f);
    int rc = sx_score_load(e, tbl, n);
    if (rc != SX_OK)
        fprintf(stderr, "sx-render: %s: the score was not loaded (%d)\n", path, rc);
    return rc == SX_OK ? 0 : -1;
}

static void apply(sx_engine *e, const event *v)
{
    sx_cmd c = {0, 0, 0, 0.0f};
    if (strcmp(v->what, "keys") == 0) {
        sx_keys_set(e, SX_KEYS_MIDI, v->arg);
        return;
    }
    if (strcmp(v->what, "graph") == 0) {
        load_graph(e, v->text);
        return;
    }
    if (strcmp(v->what, "score") == 0) {
        load_score(e, v->text);
        return;
    }
    if (strcmp(v->what, "sr") == 0) {
        c.kind = SX_CMD_SR_SET;
        c.a = (uint32_t)(v->arg & 0xFFFFu);
    } else if (strcmp(v->what, "auth") == 0) {
        c.kind = SX_CMD_AUTH_MODE;
        c.a = (uint32_t)v->arg;
    } else if (strcmp(v->what, "volume") == 0) {
        c.kind = SX_CMD_VOLUME;
        c.f = (float)v->num;
    } else if (strcmp(v->what, "ceiling") == 0) {
        c.kind = SX_CMD_CEILING;
        c.f = (float)v->num;
    } else if (strcmp(v->what, "speed") == 0) {
        c.kind = SX_CMD_SPEED;
        c.a = (uint32_t)v->arg;
    } else if (strcmp(v->what, "step") == 0) {
        c.kind = SX_CMD_STEP;
    } else if (strcmp(v->what, "mute") == 0) {
        c.kind = SX_CMD_MUTE;
        c.a = (uint32_t)v->arg;
    } else if (strcmp(v->what, "home") == 0) {
        c.kind = SX_CMD_RESET_HOME;
    } else {
        fprintf(stderr, "sx-render: unknown script event %s\n", v->what);
        return;
    }
    sx_command(e, &c);
}

int main(int argc, char **argv)
{
    const char *image = NULL, *script = NULL, *wav = NULL, *feat = NULL, *tout = NULL,
               *replay = NULL, *graph = NULL, *rigdac = NULL;
    double seconds = 1.0;
    uint32_t rate = 48000, per = 128, bits = 0, sr = 0, auth = 0;
    int stats = 0, have_sr = 0;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (strcmp(a, "--stats") == 0) {
            stats = 1;
            continue;
        }
        if (strcmp(a, "--modules") == 0) {
            size_t n = sx_modules_json(NULL, 0);
            char *buf = malloc(n + 1u);
            if (buf == NULL)
                return 2;
            sx_modules_json(buf, n + 1u);
            fputs(buf, stdout);
            free(buf);
            return 0;
        }
        if (v == NULL) {
            fprintf(stderr, "sx-render: %s needs a value\n", a);
            return 2;
        }
        i++;
        if (strcmp(a, "--image") == 0)
            image = v;
        else if (strcmp(a, "--script") == 0)
            script = v;
        else if (strcmp(a, "--seconds") == 0)
            seconds = atof(v);
        else if (strcmp(a, "--rate") == 0)
            rate = (uint32_t)atoi(v);
        else if (strcmp(a, "--period") == 0)
            per = (uint32_t)atoi(v);
        else if (strcmp(a, "--word-bits") == 0)
            bits = (uint32_t)atoi(v);
        else if (strcmp(a, "--wav") == 0)
            wav = v;
        else if (strcmp(a, "--features") == 0)
            feat = v;
        else if (strcmp(a, "--trace-out") == 0)
            tout = v;
        else if (strcmp(a, "--replay") == 0)
            replay = v;
        else if (strcmp(a, "--graph") == 0)
            graph = v;
        else if (strcmp(a, "--rig-dac") == 0)
            rigdac = v;
        else if (strcmp(a, "--sr") == 0) {
            sr = (uint32_t)strtoul(v, NULL, 16);
            have_sr = 1;
        } else if (strcmp(a, "--auth") == 0)
            auth = (uint32_t)atoi(v);
        else {
            fprintf(stderr, "sx-render: unknown option %s\n", a);
            return 2;
        }
    }
#if !defined(SX_TEST_HOOKS)
    if (tout || replay) {
        fprintf(stderr, "sx-render: --trace-out and --replay exist only in the test profile\n");
        return 2;
    }
#endif
    if ((image == NULL && replay == NULL) || per == 0 || per > 4096 || !(seconds > 0) ||
        seconds > 3600) {
        fprintf(stderr, "usage: sx-render --image IMG --script TXT --seconds S [--wav OUT]\n");
        return 2;
    }
    if (wav && check_wav_path(wav) != 0)
        return 3;
    sx_image img;
    if (image && load_image_json(image, &img) != 0) {
        fprintf(stderr, "sx-render: %s: not a seastones.image/1 file\n", image);
        return 2;
    }
    if (script && load_script(script, rate) != 0) {
        fprintf(stderr, "sx-render: %s: %s\n", script, strerror(errno));
        return 2;
    }
    sx_config cfg = {SX_API_VERSION, rate, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    if (rigdac && read_rig_dac(rigdac, &cfg) != 0)
        return 2;
    if (bits)
        cfg.dac_word_bits = bits;
    sx_engine *e = sx_create(&cfg);
    if (e == NULL) {
        fprintf(stderr, "sx-render: engine create failed\n");
        return 2;
    }
#if defined(SX_TEST_HOOKS)
    if (tout || replay) {
        trace = calloc(MAXTRACE, sizeof *trace);
        if (trace == NULL)
            return 2;
    }
    if (replay) {
        if (load_trace(replay) != 0) {
            fprintf(stderr, "sx-render: %s: cannot read the trace\n", replay);
            return 2;
        }
        sx_test_replay(e, trace, ntrace);
    }
    if (tout)
        sx_test_set_event_tap(e, tap, NULL);
#endif
    if (image && !replay && sx_load_image(e, &img) == SX_E_HASH) {
        fprintf(stderr, "sx-render: image_hash_mismatch: %s refused, nothing rendered\n", image);
        sx_destroy(e);
        return 4;
    }
    if (graph && load_graph(e, graph) != 0) {
        sx_destroy(e);
        return 2;
    }
    if (have_sr) {
        sx_cmd c = {SX_CMD_SR_SET, sr & 0xFFFFu, 0, 0.0f};
        sx_command(e, &c);
    }
    if (auth) {
        sx_cmd c = {SX_CMD_AUTH_MODE, auth, 0, 0.0f};
        sx_command(e, &c);
    }
    uint64_t frames = (uint64_t)llround(seconds * rate);
    float *pcm = calloc(frames * 2u, sizeof *pcm);
    if (pcm == NULL)
        return 2;
    int next = 0;
    sx_sha256 h;
    sx_sha256_init(&h);
    for (uint64_t f = 0; f < frames; f += per) {
        while (next < nev && evs[next].frame <= f)
            apply(e, &evs[next++]);
        uint32_t n = (uint32_t)(frames - f < per ? frames - f : per);
        sx_render(e, pcm + 2 * f, n);
    }
    for (uint64_t i = 0; i < 2 * frames; i++) {
        uint32_t u;
        memcpy(&u, &pcm[i], 4);
        uint8_t b[4] = {(uint8_t)u, (uint8_t)(u >> 8), (uint8_t)(u >> 16), (uint8_t)(u >> 24)};
        sx_sha256_update(&h, b, 4);
    }
    uint8_t d[32];
    char hex[65];
    sx_sha256_final(&h, d);
    sx_sha256_hex(d, hex);
    printf("sha256 %s\n", hex);
    if (stats) {
        sx_snapshot s;
        if (sx_snapshot_read(e, &s) == SX_OK) {
            printf("frames %llu cycles %llu faults %u\n", (unsigned long long)s.frames,
                   (unsigned long long)s.cycles, s.faults);
            printf("lat_t arrival %llu latch %llu first_write %llu onset %llu\n",
                   (unsigned long long)s.lat_t[SX_LAT_ARRIVAL],
                   (unsigned long long)s.lat_t[SX_LAT_LATCH],
                   (unsigned long long)s.lat_t[SX_LAT_FIRST_WRITE],
                   (unsigned long long)s.lat_t[SX_LAT_ONSET]);
            printf("lat_hist");
            for (int i = 0; i < SX_LAT_BINS; i++)
                printf(" %u", s.lat_hist[i]);
            printf("\n");
        }
    }
    int rc = 0;
    if (feat) {
        FILE *f = strcmp(feat, "-") == 0 ? stdout : fopen(feat, "w");
        if (f) {
            write_features(f, pcm, frames, rate, hex);
            if (f != stdout)
                fclose(f);
        } else {
            rc = 2;
        }
    }
    if (wav && write_wav(wav, pcm, frames, rate) != 0)
        rc = 2;
#if defined(SX_TEST_HOOKS)
    if (tout && save_trace(tout) != 0)
        rc = 2;
    free(trace);
#endif
    free(pcm);
    sx_destroy(e);
    return rc;
}
