/* patch.c: building a patch graph from `seastones.graph/1` text, off the audio thread (PM-05,
 * PM-06), and exporting the module registry (build/modules.json).
 *
 * seastones.graph/1 is the engine's own flat form of a patch: src/toolchain/sxpatch validates a
 * `seastones.patch/1` JSON file (templates, voice counts, wildcards, plain-English errors) and
 * compiles it to this. One statement per line; `#` starts a comment:
 *
 *   graph 1                     first statement, always
 *   module NAME TYPE            NAME is 1-23 of [a-z0-9_]; TYPE is a registry name (graph.c)
 *   param NAME PARAM VALUE      VALUE is clamped to the parameter's declared range
 *   cable FROM TO               FROM: dac.N | gate.N | NAME.OUTPUT    TO: NAME.INPUT
 *   end                         optional; nothing may follow it
 *
 * One cable per input; outputs fan out. A patch with no path from a source to an `out` is legal
 * (the UI's silence hint, PATCH-4). Errors name the line. The parser is fuzzed under ASan and
 * UBSan (tests/engine/test_graph.c).
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "patch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NAMELEN 24

const char sx_patch_builtin[] =
    "graph 1\n"
    "# the engine's own default: four plain voices on the all-D/A map\n"
    "module mix mixer\n"
    "param mix l1 0.35\nparam mix l2 0.35\nparam mix l3 0.35\nparam mix l4 0.35\n"
    "module o out\n"
    "cable mix.out o.l\n"
    "module osc0 vco\nmodule eg0 env\nmodule amp0 vca\n"
    "cable dac.0 osc0.pitch\ncable dac.4 eg0.gate\ncable osc0.saw amp0.in\n"
    "cable eg0.out amp0.cv\ncable amp0.out mix.in1\n"
    "module osc1 vco\nmodule eg1 env\nmodule amp1 vca\n"
    "cable dac.1 osc1.pitch\ncable dac.5 eg1.gate\ncable osc1.saw amp1.in\n"
    "cable eg1.out amp1.cv\ncable amp1.out mix.in2\n"
    "module osc2 vco\nmodule eg2 env\nmodule amp2 vca\n"
    "cable dac.2 osc2.pitch\ncable dac.6 eg2.gate\ncable osc2.saw amp2.in\n"
    "cable eg2.out amp2.cv\ncable amp2.out mix.in3\n"
    "module osc3 vco\nmodule eg3 env\nmodule amp3 vca\n"
    "cable dac.3 osc3.pitch\ncable dac.7 eg3.gate\ncable osc3.saw amp3.in\n"
    "cable eg3.out amp3.cv\ncable amp3.out mix.in4\n";

typedef struct {
    sx_graph *g;
    char names[SX_G_MAXMOD][NAMELEN];
    uint32_t echoes, reverbs;
} builder;

static int fail(char *err, size_t n, uint32_t line, const char *msg, const char *what)
{
    if (err && n)
        snprintf(err, n, "line %u: %s%s%s", line, msg, what ? ": " : "", what ? what : "");
    return -1;
}

static int find(const builder *b, const char *name, size_t len)
{
    for (uint32_t i = 0; i < b->g->nmod; i++)
        if (strlen(b->names[i]) == len && memcmp(b->names[i], name, len) == 0)
            return (int)i;
    return -1;
}

static int valid_name(const char *s)
{
    size_t n = strlen(s);
    if (n == 0 || n >= NAMELEN)
        return 0;
    for (size_t i = 0; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9') || s[i] == '_'))
            return 0;
    return 1;
}

/* "dac.N", "gate.N" or "NAME.PORT": 0 on success */
static int endpoint(const builder *b, const char *tok, int output, sx_gin *out)
{
    const char *dot = strchr(tok, '.');
    if (dot == NULL || dot == tok || dot[1] == 0 || strchr(dot + 1, '.'))
        return -1;
    size_t nl = (size_t)(dot - tok);
    if (output &&
        ((nl == 3 && memcmp(tok, "dac", 3) == 0) || (nl == 4 && memcmp(tok, "gate", 4) == 0))) {
        char *end;
        long v = strtol(dot + 1, &end, 10);
        if (*end || v < 0 || v > 15 || dot[1] < '0' || dot[1] > '9')
            return -1;
        *out = (sx_gin){SX_GIN_SRC, (uint8_t)(v + (nl == 4 ? 16 : 0)), 0};
        return 0;
    }
    int m = find(b, tok, nl);
    if (m < 0)
        return -1;
    int p = sx_module_port(b->g->m[m].type, output, dot + 1);
    if (p < 0)
        return -1;
    *out = (sx_gin){SX_GIN_MOD, (uint8_t)m, (uint8_t)p};
    return 0;
}

static int statement(builder *b, uint32_t line, char *tok[], int nt, char *err, size_t errn)
{
    sx_graph *g = b->g;
    if (strcmp(tok[0], "module") == 0) {
        if (nt != 3)
            return fail(err, errn, line, "expected 'module NAME TYPE'", NULL);
        if (!valid_name(tok[1]))
            return fail(err, errn, line, "a module name is 1-23 of a-z, 0-9 and _", tok[1]);
        if (find(b, tok[1], strlen(tok[1])) >= 0)
            return fail(err, errn, line, "two modules have the same name", tok[1]);
        int t = sx_module_type(tok[2]);
        if (t < 0)
            return fail(err, errn, line, "no such module type", tok[2]);
        if (g->nmod >= SX_G_MAXMOD)
            return fail(err, errn, line, "too many modules (64 at most)", NULL);
        if (t == SX_M_ECHO && ++b->echoes > SX_G_MAXECHO)
            return fail(err, errn, line, "too many echoes (2 at most)", NULL);
        if (t == SX_M_REVERB && ++b->reverbs > SX_G_MAXREV)
            return fail(err, errn, line, "too many reverbs (2 at most)", NULL);
        sx_gmod *m = &g->m[g->nmod];
        memset(m, 0, sizeof *m);
        m->type = (uint8_t)t;
        for (int k = 0; k < sx_modules[t].npar; k++)
            m->par[k] = sx_modules[t].par[k].def;
        snprintf(b->names[g->nmod], NAMELEN, "%s", tok[1]);
        g->nmod++;
        return 0;
    }
    if (strcmp(tok[0], "param") == 0) {
        if (nt != 4)
            return fail(err, errn, line, "expected 'param NAME PARAM VALUE'", NULL);
        int m = find(b, tok[1], strlen(tok[1]));
        if (m < 0)
            return fail(err, errn, line, "no module of that name", tok[1]);
        int p = sx_module_param(g->m[m].type, tok[2]);
        if (p < 0)
            return fail(err, errn, line, "no such parameter", tok[2]);
        char *end;
        double v = strtod(tok[3], &end);
        if (*end || !(v == v))
            return fail(err, errn, line, "not a number", tok[3]);
        const sx_mparam *mp = &sx_modules[g->m[m].type].par[p];
        g->m[m].par[p] = v < mp->min ? mp->min : (v > mp->max ? mp->max : v);
        return 0;
    }
    if (strcmp(tok[0], "cable") == 0) {
        if (nt != 3)
            return fail(err, errn, line, "expected 'cable FROM TO'", NULL);
        sx_gin from, to;
        if (endpoint(b, tok[1], 1, &from) != 0)
            return fail(err, errn, line, "no such output", tok[1]);
        if (endpoint(b, tok[2], 0, &to) != 0 || to.kind != SX_GIN_MOD)
            return fail(err, errn, line, "no such input", tok[2]);
        sx_gin *in = &g->m[to.idx].in[to.port];
        if (in->kind != SX_GIN_NONE)
            return fail(err, errn, line, "that input already has a cable", tok[2]);
        *in = from;
        return 0;
    }
    return fail(err, errn, line, "unknown statement", tok[0]);
}

sx_graph *sx_patch_build(const char *text, size_t len, double fs, char *err, size_t errn)
{
    if (err && errn)
        err[0] = 0;
    if (text == NULL)
        return NULL;
    builder *b = calloc(1, sizeof *b);
    sx_graph *g = calloc(1, sizeof *g);
    if (b == NULL || g == NULL) {
        free(b);
        free(g);
        fail(err, errn, 0, "out of memory", NULL);
        return NULL;
    }
    sx_graph_init(g, fs);
    b->g = g;
    int rc = 0, header = 0, ended = 0;
    uint32_t lineno = 0;
    size_t pos = 0;
    char buf[256];
    while (pos < len && rc == 0) {
        size_t e = pos;
        while (e < len && text[e] != '\n')
            e++;
        lineno++;
        size_t n = e - pos;
        if (n >= sizeof buf) {
            rc = fail(err, errn, lineno, "line too long", NULL);
            break;
        }
        memcpy(buf, text + pos, n);
        buf[n] = 0;
        pos = e + 1;
        char *hash = strchr(buf, '#');
        if (hash)
            *hash = 0;
        char *tok[6];
        int nt = 0;
        for (char *p = buf; *p && nt < 6;) {
            while (*p == ' ' || *p == '\t' || *p == '\r')
                *p++ = 0;
            if (!*p)
                break;
            tok[nt++] = p;
            while (*p && *p != ' ' && *p != '\t' && *p != '\r')
                p++;
        }
        if (nt == 0)
            continue;
        if (ended) {
            rc = fail(err, errn, lineno, "nothing may follow 'end'", NULL);
        } else if (!header) {
            if (nt == 2 && strcmp(tok[0], "graph") == 0 && strcmp(tok[1], "1") == 0)
                header = 1;
            else
                rc = fail(err, errn, lineno, "the first line must be 'graph 1'", NULL);
        } else if (nt == 1 && strcmp(tok[0], "end") == 0) {
            ended = 1;
        } else if (nt >= 6) {
            rc = fail(err, errn, lineno, "too many words", NULL);
        } else {
            rc = statement(b, lineno, tok, nt, err, errn);
        }
    }
    if (rc == 0 && !header)
        rc = fail(err, errn, lineno, "empty: the first line must be 'graph 1'", NULL);
    size_t echo_words = (size_t)b->echoes * 2u * SX_ECHO_LEN;
    if (rc == 0 && (b->echoes || b->reverbs)) {
        g->mem = calloc(echo_words + (size_t)b->reverbs * SX_REV_LINES * SX_REV_LEN, sizeof(float));
        if (g->mem == NULL)
            rc = fail(err, errn, 0, "out of memory", NULL);
    }
    if (rc == 0 && sx_graph_finish(g) != 0)
        rc = fail(err, errn, lineno, "too many envelopes share one gate (16 at most)", NULL);
    if (rc == 0) { /* the echoes' lines */
        uint32_t k = 0;
        for (uint32_t i = 0; i < g->nmod; i++)
            if (g->m[i].type == SX_M_ECHO)
                sx_echo_init(&g->m[i].u.echo, g->fs, g->mem + (size_t)(k++) * 2u * SX_ECHO_LEN);
        for (uint32_t i = 0; i < g->nmod; i++)
            if (g->m[i].type == SX_M_ECHO)
                sx_graph_param(g, i, 3, g->m[i].par[3]);
        k = 0;
        for (uint32_t i = 0; i < g->nmod; i++)
            if (g->m[i].type == SX_M_REVERB) {
                sx_rev_init(&g->m[i].u.rev, g->fs,
                            g->mem + echo_words + (size_t)(k++) * SX_REV_LINES * SX_REV_LEN);
                sx_graph_param(g, i, 0, g->m[i].par[0]);
            }
    }
    free(b);
    if (rc != 0) {
        sx_patch_free(g);
        return NULL;
    }
    return g;
}

void sx_patch_free(sx_graph *g)
{
    if (g) {
        free(g->mem);
        free(g);
    }
}

/* --- the registry as JSON ------------------------------------------------------------------- */

typedef struct {
    char *buf;
    size_t n, at;
} jout;

static void put(jout *j, const char *fmt, const char *s, double a, double b, double c)
{
    char tmp[512];
    int k = snprintf(tmp, sizeof tmp, fmt, s, a, b, c);
    if (k < 0)
        return;
    if (j->buf && j->at + (size_t)k < j->n)
        memcpy(j->buf + j->at, tmp, (size_t)k + 1u);
    j->at += (size_t)k;
}

static void list(jout *j, const char *const *names, const char *const *units, int n)
{
    for (int i = 0; i < n; i++) {
        put(j, "%s", i ? ", " : "", 0, 0, 0);
        put(j, "{\"name\": \"%s\", ", names[i], 0, 0, 0);
        put(j, "\"unit\": \"%s\"}", units[i], 0, 0, 0);
    }
}

size_t sx_modules_json(char *buf, size_t n)
{
    jout j = {buf, n, 0};
    if (buf && n)
        buf[0] = 0;
    put(&j, "{\n  \"format\": \"seastones.modules/1\",%s\n", "", 0, 0, 0);
    put(&j, "  \"sources\": {\"dac\": 16, \"gate\": 16, \"gate_volts\": %s5.0},\n", "", 0, 0, 0);
    put(&j, "  \"modules\": [%s\n", "", 0, 0, 0);
    for (int t = 0; t < SX_M_NTYPES; t++) {
        const sx_mdesc *d = &sx_modules[t];
        put(&j, "    {\"type\": \"%s\",\n     \"inputs\": [", d->name, 0, 0, 0);
        list(&j, d->in, d->in_unit, d->nin);
        put(&j, "],\n     \"outputs\": [%s", "", 0, 0, 0);
        list(&j, d->out, d->out_unit, d->nout);
        put(&j, "],\n     \"params\": [%s", "", 0, 0, 0);
        for (int p = 0; p < d->npar; p++) {
            put(&j, "%s", p ? ",\n                 " : "", 0, 0, 0);
            put(&j, "{\"name\": \"%s\", ", d->par[p].name, 0, 0, 0);
            put(&j, "%s\"min\": %.17g, \"max\": %.17g, \"default\": %.17g, ", "", d->par[p].min,
                d->par[p].max, d->par[p].def);
            put(&j, "\"unit\": \"%s\"}", d->par[p].unit, 0, 0, 0);
        }
        put(&j, "],\n     \"note\": \"%s\"}", d->note, 0, 0, 0);
        put(&j, "%s\n", t + 1 < SX_M_NTYPES ? "," : "", 0, 0, 0);
    }
    put(&j, "  ]\n}\n%s", "", 0, 0, 0);
    return j.at;
}
