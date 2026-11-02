/* graph.h: the patch graph runtime and the module registry (PM-05; ARCHITECTURE 6.2, 11.3).
 *
 * A graph is up to SX_G_MAXMOD modules, each a C struct with declared inputs, outputs and
 * parameters (the registry below is the single source of truth: `sx-render --modules` exports
 * it as JSON, and src/toolchain/sxpatch validates patches against that export). One cable per
 * input; an output may feed any number of inputs. The graph's ONLY control inputs are its 32
 * sources: D/A channels 0-15 (volts after the converter's word size) and gate lines 0-15 (5 V
 * when set); everything else is module parameters (AUDIO-1).
 *
 * Signals are volts for control (1 V/oct pitch and cutoff, 0-10 V envelopes and cv) and +/-1 for
 * audio. Like a real module on +/-12 V supplies, no output swings past SX_RAIL_V, and a NaN
 * becomes 0 V, so a patch with gain round a loop saturates instead of running away (DSP-12). Every
 * module renders whole chunks of at most SX_G_BLOCK frames, in an order sorted from the sources to
 * the outputs; a cable that closes a loop reads the previous chunk (one chunk of delay, never NaN).
 *
 * Steps stay steps (NFR-2): a source changes value only at the frame of its write. Inputs that
 * act on an edge (a VCO's pitch, an envelope's gate and retrigger) are watched sample by sample,
 * and an envelope whose gate comes straight from a source is also told at once, so a gate that
 * drops and rises within one frame still restarts the envelope (a stolen voice, PRG-04).
 *
 * Authenticity (ARCHITECTURE 6.4): `analog` passes each D/A source through a one-pole low-pass
 * at dac.output_hz; `authentic` and `strobed` keep them as steps (strobed and research-only
 * jitter re-time the writes before they reach the graph: auth.h).
 *
 * Real-time safe: the graph is built off the audio thread (src/engine/api/patch.c) and rendered
 * here with no allocation. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_GRAPH_H
#define SX_GRAPH_H

#include <stddef.h>
#include <stdint.h>

#include "env.h"
#include "mods.h"
#include "vca.h"
#include "vcf.h"
#include "vco.h"

#define SX_G_MAXMOD 64u
#define SX_G_MAXIN 4u
#define SX_G_MAXOUT 4u
#define SX_G_MAXPAR 6u
#define SX_G_BLOCK 64u
#define SX_G_NSRC 32u /* 0-15 D/A channels, 16-31 gate lines */
#define SX_G_MAXLINK 16u
#define SX_G_MAXECHO 2u
#define SX_G_MAXREV 2u
#define SX_GATE_V 5.0f
#define SX_RAIL_V 12.0 /* no module output swings past its supply rails */

enum sx_mtype {
    SX_M_VCO = 0,
    SX_M_VCF,
    SX_M_VCA,
    SX_M_ENV,
    SX_M_LFO,
    SX_M_NOISE,
    SX_M_SLEW,
    SX_M_MIXER,
    SX_M_ECHO,
    SX_M_OUT,
    SX_M_REVERB, /* appended: the registry's order is the modules.json order */
    SX_M_NTYPES
};

typedef struct sx_mparam {
    const char *name;
    double min, max, def;
    const char *unit;
} sx_mparam;

typedef struct sx_mdesc {
    const char *name;
    uint8_t nin, nout, npar;
    const char *in[SX_G_MAXIN];
    const char *in_unit[SX_G_MAXIN];
    const char *out[SX_G_MAXOUT];
    const char *out_unit[SX_G_MAXOUT];
    sx_mparam par[SX_G_MAXPAR];
    const char *note;
} sx_mdesc;

extern const sx_mdesc sx_modules[SX_M_NTYPES];
int sx_module_type(const char *name);                   /* -1 if unknown */
int sx_module_port(int type, int output, const char *); /* -1 if unknown */
int sx_module_param(int type, const char *name);        /* -1 if unknown */

enum { SX_GIN_NONE = 0, SX_GIN_SRC, SX_GIN_MOD };

typedef struct sx_gin {
    uint8_t kind, idx, port;
} sx_gin;

typedef struct sx_gmod {
    uint8_t type;
    uint8_t outs_used; /* bit per output: only these are computed */
    sx_gin in[SX_G_MAXIN];
    double par[SX_G_MAXPAR];
    float out[SX_G_MAXOUT][SX_G_BLOCK];
    double applied[SX_G_MAXIN]; /* edge inputs as last acted on */
    union {
        sx_vco vco;
        sx_vcf vcf;
        sx_vca vca;
        sx_env env;
        sx_lfo lfo;
        sx_noise noise;
        sx_slew slew;
        sx_echo echo;
        sx_rev rev;
    } u;
} sx_gmod;

typedef struct sx_glink {
    uint8_t m, in;
} sx_glink;

typedef struct sx_graph {
    double fs;
    uint32_t nmod;
    uint8_t order[SX_G_MAXMOD];
    sx_gmod m[SX_G_MAXMOD];
    float src[SX_G_NSRC];  /* each source's value as last written */
    double cur[SX_G_NSRC]; /* analog: the converter's smoothed output */
    float sbuf[SX_G_NSRC][SX_G_BLOCK];
    float zero[SX_G_BLOCK];
    float tmp[3][SX_G_BLOCK];
    uint8_t nlink[SX_G_NSRC];
    sx_glink link[SX_G_NSRC][SX_G_MAXLINK];
    uint32_t src_used; /* bit per source that any input reads */
    int analog;
    double ac; /* analog low-pass coefficient */
    uint8_t path_to_out;
    uint8_t feedback; /* a cable closes a loop */
    uint64_t frame;   /* frames rendered (the engine sets it at each period) */
    uint32_t rises;   /* envelope gate rises so far */
    uint64_t rise_frame;
    float *mem; /* the echo lines, owned by whoever built the graph */
    uint32_t seq;
} sx_graph;

/* [non-RT] the empty graph at rate fs with every module slot unused; the builder fills it */
void sx_graph_init(sx_graph *g, double fs);
/* [non-RT] after the builder: order, links, path_to_out, src_used; 0 or -1 */
int sx_graph_finish(sx_graph *g);

void sx_graph_set_analog(sx_graph *g, int on, double output_hz);        /* [RT] */
void sx_graph_event(sx_graph *g, uint32_t src, float volts);            /* [RT] a write, now */
void sx_graph_param(sx_graph *g, uint32_t mod, uint32_t par, double v); /* [RT] clamped */
/* [RT] n frames into l and r (overwritten). */
void sx_graph_render(sx_graph *g, uint32_t n, float *l, float *r);
void sx_graph_reset(sx_graph *g); /* [RT] every module's state to rest (the supervisor) */

#endif
