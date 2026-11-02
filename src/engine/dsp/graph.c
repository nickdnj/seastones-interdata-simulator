/* graph.c: the module registry and the patch graph runtime (PM-05; see graph.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "graph.h"

#include "sx_math.h"

#define LN2 0.69314718055994531

/* --- the registry: names, ports, ranges (exported to build/modules.json) ------------------- */

const sx_mdesc sx_modules[SX_M_NTYPES] = {
    [SX_M_VCO] = {"vco",
                  4,
                  4,
                  5,
                  {"pitch", "mod", "fm", "pw"},
                  {"V/oct", "V/oct", "V", "V"},
                  {"sine", "tri", "saw", "pulse"},
                  {"audio", "audio", "audio", "audio"},
                  {{"tune", -5.0, 5.0, 0.0, "V"},
                   {"fine", -1.0, 1.0, 0.0, "semitone"},
                   {"mod_amt", -2.0, 2.0, 1.0, "x"},
                   {"fm", 0.0, 2000.0, 0.0, "Hz/V"},
                   {"width", 0.02, 0.98, 0.5, "duty"}},
                  "band-limited (minBLEP/minBLAMP, ADR-010); 0 V is C0, 16.352 Hz; pulse width = "
                  "width + pw/10"},
    [SX_M_VCF] = {"vcf",
                  3,
                  3,
                  5,
                  {"in", "cutoff", "res"},
                  {"audio", "V/oct", "V"},
                  {"lp", "hp", "bp"},
                  {"audio", "audio", "audio"},
                  {{"cutoff", -2.0, 12.0, 7.0, "V"},
                   {"res", 0.0, 1.0, 0.0, "0-1"},
                   {"track", -2.0, 2.0, 1.0, "x"},
                   {"res_amt", 0.0, 1.0, 0.1, "per V"},
                   {"drive", 0.25, 4.0, 1.0, "x"}},
                  "lp: 4-pole ZDF ladder, tanh input, 2x oversampled; hp, bp: 2-pole SVF; "
                  "cutoff = cutoff + track x cutoff input, 0 V is 16.352 Hz"},
    [SX_M_VCA] = {"vca",
                  2,
                  1,
                  2,
                  {"in", "cv"},
                  {"audio", "V"},
                  {"out"},
                  {"audio"},
                  {{"expo", 0.0, 1.0, 0.0, "0 lin, 1 exp"}, {"bias", 0.0, 10.0, 0.0, "V"}},
                  "gain = (bias + cv) / 10 V, after a 0.5 ms declick on the cv (ADR-005)"},
    [SX_M_ENV] = {"env",
                  2,
                  1,
                  5,
                  {"gate", "retrig"},
                  {"gate", "gate"},
                  {"out"},
                  {"V"},
                  {{"attack", 0.0, 30.0, 0.002, "s"},
                   {"decay", 0.0, 30.0, 0.2, "s"},
                   {"sustain", 0.0, 1.0, 0.7, "0-1"},
                   {"release", 0.0, 30.0, 0.3, "s"},
                   {"ar", 0.0, 1.0, 0.0, "0 ADSR, 1 AR"}},
                  "gate high above 2.5 V; out 0-10 V"},
    [SX_M_LFO] = {"lfo",
                  1,
                  4,
                  2,
                  {"rate"},
                  {"V/oct"},
                  {"sine", "tri", "square", "sh"},
                  {"V", "V", "V", "V"},
                  {{"rate", -10.0, 8.0, 0.0, "V (0 V = 1 Hz)"}, {"level", 0.0, 10.0, 1.0, "V"}},
                  "outputs +/- level volts"},
    [SX_M_NOISE] = {"noise",
                    0,
                    2,
                    1,
                    {0},
                    {0},
                    {"white", "pink"},
                    {"audio", "audio"},
                    {{"level", 0.0, 1.0, 1.0, "x"}},
                    "deterministic: seeded per module"},
    [SX_M_SLEW] = {"slew",
                   1,
                   1,
                   2,
                   {"in"},
                   {"V"},
                   {"out"},
                   {"V"},
                   {{"rise", 0.0, 10.0, 0.05, "s"}, {"fall", 0.0, 10.0, 0.05, "s"}},
                   "the only deliberate smoothing of a D/A step (NFR-2)"},
    [SX_M_MIXER] = {"mixer",
                    4,
                    1,
                    4,
                    {"in1", "in2", "in3", "in4"},
                    {"any", "any", "any", "any"},
                    {"out"},
                    {"any"},
                    {{"l1", 0.0, 2.0, 1.0, "x"},
                     {"l2", 0.0, 2.0, 1.0, "x"},
                     {"l3", 0.0, 2.0, 1.0, "x"},
                     {"l4", 0.0, 2.0, 1.0, "x"}},
                    "out = sum of level x input"},
    [SX_M_ECHO] = {"echo",
                   2,
                   2,
                   4,
                   {"in", "time"},
                   {"audio", "V/oct"},
                   {"l", "r"},
                   {"audio", "audio"},
                   {{"time", 0.02, 1.0, 0.35, "s"},
                    {"feedback", 0.0, 0.9, 0.35, "x"},
                    {"mix", 0.0, 1.0, 0.3, "x"},
                    {"tone", 200.0, 12000.0, 3500.0, "Hz"}},
                   "our addition (PATCH-3): a ping-pong delay; 1 V on time doubles it"},
    [SX_M_OUT] =
        {"out",
         2,
         0,
         1,
         {"l", "r"},
         {"audio", "audio"},
         {0},
         {0},
         {{"level", 0.0, 1.0, 0.5, "x"}},
         "to the master bus and the safety chain; r unpatched follows l"},
    [SX_M_REVERB] =
        {"reverb",
         1,
         2,
         4,
         {"in"},
         {"audio"},
         {"l", "r"},
         {"audio", "audio"},
         {{"t60", 0.1, 10.0, 2.0, "s"},
          {"size", 0.5, 1.5, 1.0, "x"},
          {"tone", 500.0, 16000.0, 6000.0, "Hz"},
          {"mix", 0.0, 1.0, 0.3, "x"}},
         "our addition (PATCH-3): a 4-line feedback delay network; -60 dB in t60"},
};

static int streq(const char *a, const char *b)
{
    while (*a && *a == *b) {
        a++;
        b++;
    }
    return *a == *b;
}

int sx_module_type(const char *name)
{
    for (int t = 0; t < SX_M_NTYPES; t++)
        if (streq(name, sx_modules[t].name))
            return t;
    return -1;
}

int sx_module_port(int type, int output, const char *name)
{
    if (type < 0 || type >= SX_M_NTYPES)
        return -1;
    const sx_mdesc *d = &sx_modules[type];
    for (int i = 0; i < (output ? d->nout : d->nin); i++)
        if (streq(name, output ? d->out[i] : d->in[i]))
            return i;
    return -1;
}

int sx_module_param(int type, const char *name)
{
    if (type < 0 || type >= SX_M_NTYPES)
        return -1;
    for (int i = 0; i < sx_modules[type].npar; i++)
        if (streq(name, sx_modules[type].par[i].name))
            return i;
    return -1;
}

/* --- parameters ------------------------------------------------------------------------------ */

static void apply_params(sx_gmod *m)
{
    double *p = m->par;
    switch (m->type) {
    case SX_M_VCO:
        sx_vco_set_tune(&m->u.vco, p[0] + p[1] / 12.0);
        m->u.vco.fm_hz_per_v = p[3];
        break;
    case SX_M_VCA:
        m->u.vca.expo = p[0] >= 0.5;
        break;
    case SX_M_ENV:
        sx_env_set(&m->u.env, p[0], p[1], p[2], p[3]);
        sx_env_set_ar(&m->u.env, p[4] >= 0.5);
        break;
    case SX_M_SLEW:
        sx_slew_set(&m->u.slew, p[0], p[1]);
        break;
    case SX_M_ECHO:
        sx_echo_tone(&m->u.echo, p[3]);
        break;
    case SX_M_REVERB:
        if (m->u.rev.line[0])
            sx_rev_set(&m->u.rev, p[0], p[1], p[2]);
        break;
    default:
        break;
    }
}

void sx_graph_param(sx_graph *g, uint32_t mi, uint32_t pi, double v)
{
    if (mi >= g->nmod)
        return;
    sx_gmod *m = &g->m[mi];
    const sx_mdesc *d = &sx_modules[m->type];
    if (pi >= d->npar)
        return;
    const sx_mparam *mp = &d->par[pi];
    if (!(v >= mp->min)) /* also NaN */
        v = mp->min;
    if (v > mp->max)
        v = mp->max;
    m->par[pi] = v;
    apply_params(m);
}

/* --- building (no allocation here: patch.c allocates) ----------------------------------------- */

void sx_graph_init(sx_graph *g, double fs)
{
    g->fs = fs > 0.0 ? fs : 48000.0;
    g->nmod = 0;
    g->analog = 0;
    g->ac = 0.0;
    g->src_used = 0;
    g->path_to_out = 0;
    g->feedback = 0;
    g->frame = 0;
    g->rises = 0;
    g->rise_frame = 0;
    g->mem = 0;
    g->seq = 0;
    for (uint32_t s = 0; s < SX_G_NSRC; s++) {
        g->src[s] = 0.0f;
        g->cur[s] = 0.0;
        g->nlink[s] = 0;
    }
    for (uint32_t i = 0; i < SX_G_BLOCK; i++)
        g->zero[i] = 0.0f;
}

static void module_init(sx_graph *g, uint32_t i)
{
    sx_gmod *m = &g->m[i];
    double fs = g->fs;
    for (uint32_t k = 0; k < SX_G_MAXIN; k++)
        m->applied[k] = 1e300; /* nothing applied yet */
    switch (m->type) {
    case SX_M_VCO:
        sx_vco_init(&m->u.vco, fs);
        break;
    case SX_M_VCF:
        sx_vcf_init(&m->u.vcf, fs);
        break;
    case SX_M_VCA:
        sx_vca_init(&m->u.vca, fs);
        break;
    case SX_M_ENV:
        sx_env_init(&m->u.env, fs);
        m->applied[0] = m->applied[1] = 0.0; /* the gates start low */
        break;
    case SX_M_LFO:
        sx_lfo_init(&m->u.lfo, fs, 0x9E3779B9u ^ (i * 2654435761u));
        break;
    case SX_M_NOISE:
        sx_noise_init(&m->u.noise, 0x1974u + 7919u * i);
        break;
    case SX_M_SLEW:
        sx_slew_init(&m->u.slew, fs);
        break;
    case SX_M_ECHO:
        m->u.echo.fs = fs; /* the builder gives it its lines (sx_echo_init) */
        m->u.echo.l = m->u.echo.r = 0;
        break;
    case SX_M_REVERB:
        m->u.rev.fs = fs; /* the builder gives it its lines (sx_rev_init) */
        m->u.rev.line[0] = 0;
        break;
    default:
        break;
    }
    apply_params(m);
}

int sx_graph_finish(sx_graph *g)
{
    uint32_t n = g->nmod;
    uint8_t indeg[SX_G_MAXMOD], placed[SX_G_MAXMOD];
    for (uint32_t i = 0; i < n; i++) {
        indeg[i] = 0;
        placed[i] = 0;
        for (uint32_t k = 0; k < SX_G_MAXIN; k++)
            if (g->m[i].in[k].kind == SX_GIN_MOD && g->m[i].in[k].idx != i)
                indeg[i]++;
    }
    /* Kahn's order, ties by declaration order; whatever is left is in a loop */
    uint32_t done = 0;
    while (done < n) {
        uint32_t pick = n;
        for (uint32_t i = 0; i < n && pick == n; i++)
            if (!placed[i] && indeg[i] == 0)
                pick = i;
        if (pick == n) { /* a loop: take the first unplaced module; its back cable reads late */
            g->feedback = 1;
            for (uint32_t i = 0; i < n && pick == n; i++)
                if (!placed[i])
                    pick = i;
        }
        placed[pick] = 1;
        g->order[done++] = (uint8_t)pick;
        for (uint32_t i = 0; i < n; i++)
            for (uint32_t k = 0; k < SX_G_MAXIN; k++)
                if (!placed[i] && g->m[i].in[k].kind == SX_GIN_MOD && g->m[i].in[k].idx == pick &&
                    indeg[i])
                    indeg[i]--;
    }
    /* sources read, edge links, outputs used, and whether any source reaches an out */
    uint8_t reach[SX_G_MAXMOD];
    for (uint32_t i = 0; i < n; i++)
        reach[i] = 0;
    for (uint32_t i = 0; i < n; i++) {
        sx_gmod *m = &g->m[i];
        for (uint32_t k = 0; k < SX_G_MAXIN; k++) {
            sx_gin *in = &m->in[k];
            if (in->kind == SX_GIN_SRC) {
                g->src_used |= 1u << in->idx;
                reach[i] = 1;
                if (m->type == SX_M_ENV) {
                    if (g->nlink[in->idx] >= SX_G_MAXLINK)
                        return -1;
                    g->link[in->idx][g->nlink[in->idx]++] = (sx_glink){(uint8_t)i, (uint8_t)k};
                }
            } else if (in->kind == SX_GIN_MOD) {
                g->m[in->idx].outs_used |= (uint8_t)(1u << in->port);
            }
        }
    }
    for (uint32_t pass = 0; pass < n; pass++) /* propagate reachability along the cables */
        for (uint32_t i = 0; i < n; i++)
            for (uint32_t k = 0; k < SX_G_MAXIN; k++)
                if (g->m[i].in[k].kind == SX_GIN_MOD && reach[g->m[i].in[k].idx])
                    reach[i] = 1;
    for (uint32_t i = 0; i < n; i++) {
        if (g->m[i].type == SX_M_OUT && reach[i])
            g->path_to_out = 1;
        module_init(g, i);
    }
    return 0;
}

/* --- running ---------------------------------------------------------------------------------- */

void sx_graph_set_analog(sx_graph *g, int on, double hz)
{
    g->analog = on != 0;
    if (!(hz > 1.0))
        hz = 2000.0;
    g->ac = sx_exp2(-6.283185307179586 * hz / g->fs / LN2);
}

static void env_edge(sx_graph *g, sx_gmod *m, uint32_t k, double v, uint64_t frame)
{
    int high = v > SX_ENV_GATE_V, was = m->applied[k] > SX_ENV_GATE_V;
    m->applied[k] = v;
    if (k == 0) {
        if (high && !was) {
            g->rises++;
            g->rise_frame = frame;
        }
        sx_env_gate(&m->u.env, v);
    } else if (high && !was) {
        sx_env_retrigger(&m->u.env);
    }
}

void sx_graph_event(sx_graph *g, uint32_t src, float v)
{
    if (src >= SX_G_NSRC)
        return;
    g->src[src] = v;
    if (g->analog && src < 16u)
        return; /* the converter's output stage smooths it: the envelope sees it cross */
    for (uint32_t j = 0; j < g->nlink[src]; j++) {
        sx_gmod *m = &g->m[g->link[src][j].m];
        uint32_t k = g->link[src][j].in;
        if ((double)v != m->applied[k])
            env_edge(g, m, k, (double)v, g->frame);
    }
}

static const float *input(sx_graph *g, const sx_gmod *m, uint32_t k)
{
    const sx_gin *in = &m->in[k];
    if (in->kind == SX_GIN_SRC)
        return g->sbuf[in->idx];
    if (in->kind == SX_GIN_MOD)
        return g->m[in->idx].out[in->port];
    return g->zero;
}

static int connected(const sx_gmod *m, uint32_t k)
{
    return m->in[k].kind != SX_GIN_NONE;
}

static float *out_if(sx_gmod *m, uint32_t k)
{
    return (m->outs_used & (1u << k)) ? m->out[k] : 0;
}

static void run_vco(sx_graph *g, sx_gmod *m, uint32_t n)
{
    const float *pitch = input(g, m, 0), *mod = input(g, m, 1);
    const float *fm = connected(m, 2) ? input(g, m, 2) : 0;
    const float *pw = 0;
    double amt = m->par[2], width = m->par[4];
    if (connected(m, 3)) {
        const float *x = input(g, m, 3);
        for (uint32_t i = 0; i < n; i++)
            g->tmp[0][i] = (float)(width + 0.1 * (double)x[i]);
        pw = g->tmp[0];
    } else if (m->par[4] != 0.5) {
        for (uint32_t i = 0; i < n; i++)
            g->tmp[0][i] = (float)width;
        pw = g->tmp[0];
    }
    float *o[4] = {out_if(m, 0), out_if(m, 1), out_if(m, 2), out_if(m, 3)};
    uint32_t i = 0;
    while (i < n) {
        double tot = (double)pitch[i] + amt * (double)mod[i];
        if (tot != m->applied[0]) {
            sx_vco_set_pitch(&m->u.vco, tot);
            m->applied[0] = tot;
        }
        uint32_t j = i + 1;
        while (j < n && (double)pitch[j] + amt * (double)mod[j] == tot)
            j++;
        sx_vco_render(&m->u.vco, j - i, pw ? pw + i : 0, fm ? fm + i : 0, o[0] ? o[0] + i : 0,
                      o[1] ? o[1] + i : 0, o[2] ? o[2] + i : 0, o[3] ? o[3] + i : 0);
        i = j;
    }
}

static void run_vcf(sx_graph *g, sx_gmod *m, uint32_t n)
{
    const float *x = input(g, m, 0), *cut = input(g, m, 1), *res = input(g, m, 2);
    float *lp = out_if(m, 0), *hp = out_if(m, 1), *bp = out_if(m, 2);
    if (!lp && !hp && !bp)
        return;
    double base = m->par[0], track = m->par[2], r0 = m->par[1], ramt = m->par[3];
    m->u.vcf.drive = m->par[4];
    float dl, dh, db;
    for (uint32_t i = 0; i < n; i++) {
        double v = base + track * (double)cut[i], r = r0 + ramt * (double)res[i];
        if (v != m->u.vcf.volts || r != m->applied[2]) {
            m->applied[2] = r;
            sx_vcf_set(&m->u.vcf, v, r);
        }
        sx_vcf_tick(&m->u.vcf, (double)x[i], lp != 0, hp || bp, lp ? lp + i : &dl,
                    hp ? hp + i : &dh, bp ? bp + i : &db);
    }
}

static void run_vca(sx_graph *g, sx_gmod *m, uint32_t n)
{
    float *o = out_if(m, 0);
    if (!o)
        return;
    const float *cv = connected(m, 1) ? input(g, m, 1) : g->zero;
    if (m->par[1] != 0.0) {
        for (uint32_t i = 0; i < n; i++)
            g->tmp[0][i] = (float)((double)cv[i] + m->par[1]);
        cv = g->tmp[0];
    }
    sx_vca_render(&m->u.vca, n, input(g, m, 0), cv, o);
}

static void run_env(sx_graph *g, sx_gmod *m, uint32_t n)
{
    const float *gate = input(g, m, 0), *rt = input(g, m, 1);
    float *o = m->out[0];
    uint32_t i = 0;
    while (i < n) {
        if ((double)gate[i] != m->applied[0])
            env_edge(g, m, 0, (double)gate[i], g->frame + i);
        if ((double)rt[i] != m->applied[1])
            env_edge(g, m, 1, (double)rt[i], g->frame + i);
        uint32_t j = i + 1;
        while (j < n && (double)gate[j] == m->applied[0] && (double)rt[j] == m->applied[1])
            j++;
        sx_env_render(&m->u.env, j - i, o + i);
        i = j;
    }
}

static void scale(float *x, uint32_t n, double k)
{
    if (x && k != 1.0)
        for (uint32_t i = 0; i < n; i++)
            x[i] = (float)((double)x[i] * k);
}

static void run_module(sx_graph *g, sx_gmod *m, uint32_t n, float *l, float *r)
{
    switch (m->type) {
    case SX_M_VCO:
        run_vco(g, m, n);
        break;
    case SX_M_VCF:
        run_vcf(g, m, n);
        break;
    case SX_M_VCA:
        run_vca(g, m, n);
        break;
    case SX_M_ENV:
        run_env(g, m, n);
        break;
    case SX_M_LFO: {
        float *o[4] = {out_if(m, 0), out_if(m, 1), out_if(m, 2), out_if(m, 3)};
        sx_lfo_render(&m->u.lfo, n, connected(m, 0) ? input(g, m, 0) : 0, m->par[0], o[0], o[1],
                      o[2], o[3]);
        for (int k = 0; k < 4; k++)
            scale(o[k], n, m->par[1]);
        break;
    }
    case SX_M_NOISE: {
        float *w = out_if(m, 0), *p = out_if(m, 1);
        sx_noise_render(&m->u.noise, n, w, p);
        scale(w, n, m->par[0]);
        scale(p, n, m->par[0]);
        break;
    }
    case SX_M_SLEW:
        if (out_if(m, 0))
            sx_slew_render(&m->u.slew, n, input(g, m, 0), m->out[0]);
        break;
    case SX_M_MIXER: {
        float *o = out_if(m, 0);
        if (!o)
            break;
        for (uint32_t i = 0; i < n; i++)
            o[i] = 0.0f;
        for (uint32_t k = 0; k < 4; k++) {
            if (!connected(m, k))
                continue;
            const float *x = input(g, m, k);
            double lv = m->par[k];
            for (uint32_t i = 0; i < n; i++)
                o[i] = (float)((double)o[i] + lv * (double)x[i]);
        }
        break;
    }
    case SX_M_ECHO:
        if (m->u.echo.l)
            sx_echo_render(&m->u.echo, n, input(g, m, 0), connected(m, 1) ? input(g, m, 1) : 0,
                           m->par[0], m->par[1], m->par[2], out_if(m, 0), out_if(m, 1));
        break;
    case SX_M_REVERB:
        if (m->u.rev.line[0])
            sx_rev_render(&m->u.rev, n, input(g, m, 0), m->par[3], out_if(m, 0), out_if(m, 1));
        break;
    case SX_M_OUT: {
        const float *xl = input(g, m, 0), *xr = connected(m, 1) ? input(g, m, 1) : xl;
        double lv = m->par[0];
        for (uint32_t i = 0; i < n; i++) {
            l[i] = (float)((double)l[i] + (double)xl[i] * lv);
            r[i] = (float)((double)r[i] + (double)xr[i] * lv);
        }
        break;
    }
    default:
        break;
    }
}

static void rails(sx_gmod *m, uint32_t n)
{
    for (uint32_t k = 0; k < SX_G_MAXOUT; k++) {
        if (!(m->outs_used & (1u << k)))
            continue;
        float *x = m->out[k];
        for (uint32_t i = 0; i < n; i++) {
            float v = x[i];
            if (!(v >= (float)-SX_RAIL_V)) /* also NaN */
                x[i] = v != v ? 0.0f : (float)-SX_RAIL_V;
            else if (v > (float)SX_RAIL_V)
                x[i] = (float)SX_RAIL_V;
        }
    }
}

static void fill_sources(sx_graph *g, uint32_t n)
{
    for (uint32_t s = 0; s < SX_G_NSRC; s++) {
        if (!(g->src_used & (1u << s)))
            continue;
        float *b = g->sbuf[s];
        if (g->analog && s < 16u) {
            double y = g->cur[s], x = (double)g->src[s], c = g->ac;
            for (uint32_t i = 0; i < n; i++) {
                y = x + (y - x) * c;
                b[i] = (float)y;
            }
            g->cur[s] = y;
        } else {
            float v = g->src[s];
            for (uint32_t i = 0; i < n; i++)
                b[i] = v;
            g->cur[s] = (double)v;
        }
    }
}

void sx_graph_render(sx_graph *g, uint32_t n, float *l, float *r)
{
    while (n) {
        uint32_t k = n < SX_G_BLOCK ? n : SX_G_BLOCK;
        for (uint32_t i = 0; i < k; i++)
            l[i] = r[i] = 0.0f;
        fill_sources(g, k);
        for (uint32_t j = 0; j < g->nmod; j++) {
            sx_gmod *m = &g->m[g->order[j]];
            run_module(g, m, k, l, r);
            rails(m, k);
        }
        g->frame += k;
        l += k;
        r += k;
        n -= k;
    }
}

void sx_graph_reset(sx_graph *g)
{
    for (uint32_t i = 0; i < g->nmod; i++) {
        sx_gmod *m = &g->m[i];
        switch (m->type) {
        case SX_M_VCO:
            sx_vco_reset(&m->u.vco);
            m->applied[0] = 1e300;
            break;
        case SX_M_VCF:
            sx_vcf_reset(&m->u.vcf);
            break;
        case SX_M_VCA:
            sx_vca_reset(&m->u.vca);
            break;
        case SX_M_ENV:
            sx_env_reset(&m->u.env);
            m->applied[0] = m->applied[1] = 0.0;
            break;
        case SX_M_LFO:
            sx_lfo_reset(&m->u.lfo);
            break;
        case SX_M_SLEW:
            sx_slew_reset(&m->u.slew, 0.0);
            break;
        case SX_M_ECHO:
            if (m->u.echo.l)
                sx_echo_reset(&m->u.echo);
            break;
        case SX_M_REVERB:
            if (m->u.rev.line[0])
                sx_rev_reset(&m->u.rev);
            break;
        default:
            break;
        }
    }
}
