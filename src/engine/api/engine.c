/* engine.c: the engine's non-RT and any-thread entry points (VS-12; seastones.h).
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "engine_int.h"

#include "cycles.h"
#include "id_seastones.h"
#include "keys.h"
#include "patch.h"
#include "scp_shim.h"
#include "sha256.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern UNIT cpu_unit;
extern DEVICE cpu_dev;
extern uint32 PC, PSW, SR, DR, DRX, GREG[16];
extern t_stat cpu_set_size(UNIT *uptr, int32 val, char *cptr, void *desc);

static atomic_int instance; /* SIMH keeps CPU state in globals: one engine per process */

uint32_t sx_api_version(void)
{
    return SX_API_VERSION;
}

/* The profile, also as a string in the binary for the release gate (VS-27, SEA-3). */
#if defined(SX_PROFILE_PRODUCTION) && defined(SX_TEST_HOOKS)
#error "the production profile cannot have test hooks"
#endif
#if defined(SX_PROFILE_PRODUCTION)
#define SX_PROFILE_NAME "production"
#else
#define SX_PROFILE_NAME "test"
#endif
#if defined(__GNUC__)
__attribute__((used))
#endif
const char sx_profile_tag[] = "SEASTONES_PROFILE=" SX_PROFILE_NAME;

const char *sx_profile(void)
{
    return sx_profile_tag + sizeof "SEASTONES_PROFILE=" - 1u;
}

#if defined(SX_TEST_HOOKS)
void sx_test_inject(sx_engine *e, uint32_t what)
{
    if (e)
        atomic_store(&e->inject, what);
}

void sx_test_set_event_tap(sx_engine *e, sx_event_tap tap, void *ctx)
{
    if (e) {
        e->tap = tap;
        e->tap_ctx = ctx;
    }
}

void sx_test_replay(sx_engine *e, const sx_trace_ev *trace, uint32_t n)
{
    if (e) {
        e->replay = trace;
        e->replay_n = trace ? n : 0u;
        e->replay_pos = 0;
    }
}
#endif

static void on_write(void *ctx, uint64_t cycle, uint8_t dev, uint8_t ch, uint16_t val)
{
    sx_engine *e = ctx;
    if (e->sink)
        e->sink(e->sink_ctx, cycle, dev, ch, val);
}

static int valid(sx_config *c)
{
    if (c->api_version != SX_API_VERSION)
        return 0;
    if (c->sample_rate == 0)
        c->sample_rate = 48000;
    if (c->mem_bytes == 0)
        c->mem_bytes = 32768;
    if (c->cycle_ns == 0)
        c->cycle_ns = 250;
    if (c->dac_word_bits == 0)
        c->dac_word_bits = 12;
    if (!(c->dac_range_v > 0.0f))
        c->dac_range_v = 10.24f;
    if (c->max_frames == 0)
        c->max_frames = 4096;
    if (!(c->dac_output_hz > 0.0f))
        c->dac_output_hz = 2000.0f;
    if (!(c->dac_strobe_hz > 0.0f))
        c->dac_strobe_hz = 1000.0f;
    if (!(c->jitter_ms > 0.0f))
        c->jitter_ms = 1.0f;
    return c->sample_rate >= 8000 && c->sample_rate <= 192000 && c->cycle_ns <= 10000 &&
           c->dac_word_bits <= 16 && c->mem_bytes >= 8192 && c->mem_bytes <= 65536 &&
           c->mem_bytes % 4096 == 0 && c->max_frames <= 65536 && c->dac_output_hz <= 20000.0f &&
           c->dac_strobe_hz <= (float)c->sample_rate && c->jitter_ms <= 100.0f;
}

static void clear_memory(uint32_t bytes)
{
    for (uint32_t a = 0; a < bytes; a += 2)
        cpu_dev.deposit(0, a, &cpu_unit, 0);
}

sx_engine *sx_create(const sx_config *cfg)
{
    if (cfg == NULL)
        return NULL;
    sx_config c = *cfg;
    if (!valid(&c))
        return NULL;
    int expect = 0;
    if (!atomic_compare_exchange_strong(&instance, &expect, 1))
        return NULL;
    sx_engine *e = calloc(1, sizeof *e);
    uint32_t cap = sx_clock_ev_capacity(c.sample_rate, c.cycle_ns, c.max_frames);
    int ok = e != NULL;
    if (ok) {
        e->ev = calloc(cap, sizeof *e->ev);
        e->aev = calloc(cap, sizeof *e->aev);
        e->bl = calloc(c.max_frames, sizeof *e->bl);
        e->br = calloc(c.max_frames, sizeof *e->br);
        e->fl = calloc(c.max_frames, sizeof *e->fl);
        e->fr = calloc(c.max_frames, sizeof *e->fr);
        e->score_stage = calloc(SX_SCORE_WORDS, sizeof *e->score_stage);
        e->graph = sx_patch_build(sx_patch_builtin, strlen(sx_patch_builtin), (double)c.sample_rate,
                                  NULL, 0);
        ok = e->ev && e->aev && e->bl && e->br && e->fl && e->fr && e->graph && e->score_stage;
    }
    if (!ok) {
        if (e) {
            sx_patch_free(e->graph);
            free(e->ev);
            free(e->aev);
            free(e->bl);
            free(e->br);
            free(e->fl);
            free(e->fr);
            free(e->score_stage);
            free(e);
        }
        atomic_store(&instance, 0);
        return NULL;
    }
    e->cfg = c;
    e->ev_cap = cap;
    sx_shim_reset_all(); /* the CPU's reset allocates memory, before it can be sized */
    if (cpu_set_size(&cpu_unit, (int32)c.mem_bytes, NULL, NULL) != SCPE_OK) {
        sx_destroy(e);
        return NULL;
    }
    clear_memory(c.mem_bytes);
    sx_dac_word_bits = c.dac_word_bits;
    sx_clock_init(&e->clk, c.sample_rate, c.cycle_ns, e->ev, cap);
    e->clk.sink = &on_write;
    e->clk.sink_ctx = e;
    sx_shim_reset_all();
    sx_clock_rebase(&e->clk); /* halted until an image is loaded */
    sx_keys_reset_sources();
    sx_safety_init(&e->safety, (double)c.sample_rate);
    sx_safety_init(&e->safety_r, (double)c.sample_rate);
    sx_safety_start(&e->safety); /* the 200 ms fade-in starts with the first period */
    sx_safety_start(&e->safety_r);
    sx_auth_init(&e->authst, c.sample_rate, (double)c.dac_strobe_hz, (double)c.jitter_ms);
    e->fade_len = (uint32_t)((double)c.sample_rate * SX_FADE_S);
    if (e->fade_len == 0)
        e->fade_len = 1;
    e->patch_seq = 1;
    atomic_store(&e->pending, (sx_graph *)0);
    atomic_store(&e->retired, (sx_graph *)0);
    sx_sup_init(&e->sup, c.sample_rate, c.cycle_ns);
    e->faults = SX_FAULT_IMAGE_MISSING;
    e->speed = SX_SPEED_RUN;
    return e;
}

void sx_destroy(sx_engine *e)
{
    if (e == NULL)
        return;
    sx_dev_event = NULL;
    sx_cycles_configure(0);
    free(e->words);
    free(e->segs);
    sx_patch_free(e->graph);
    sx_patch_free(e->old);
    sx_patch_free(atomic_exchange(&e->pending, (sx_graph *)0));
    sx_patch_free(atomic_exchange(&e->retired, (sx_graph *)0));
    free(e->bl);
    free(e->br);
    free(e->fl);
    free(e->fr);
    free(e->score_stage);
    free(e->aev);
    free(e->ev);
    free(e);
    atomic_store(&instance, 0);
}

/* seastones.image/1's hash: per segment in address order, address and word count as
 * big-endian halfwords, then the words big-endian (src/toolchain/sxasm/image.py). */
static void image_digest(const sx_image *img, uint8_t out[32])
{
    sx_sha256 h;
    sx_sha256_init(&h);
    for (uint32_t i = 0; i < img->nsegments; i++) {
        const sx_segment *s = &img->segments[i];
        uint8_t hd[4] = {(uint8_t)(s->addr >> 8), (uint8_t)s->addr, (uint8_t)(s->nwords >> 8),
                         (uint8_t)s->nwords};
        sx_sha256_update(&h, hd, 4);
        for (uint32_t k = 0; k < s->nwords; k++) {
            uint8_t w[2] = {(uint8_t)(s->words[k] >> 8), (uint8_t)s->words[k]};
            sx_sha256_update(&h, w, 2);
        }
    }
    sx_sha256_final(&h, out);
}

int sx_load_image(sx_engine *e, const sx_image *img)
{
    if (e == NULL || img == NULL || (img->nsegments && img->segments == NULL))
        return SX_E_ARG;
    uint32_t total = 0;
    for (uint32_t i = 0; i < img->nsegments; i++) {
        const sx_segment *s = &img->segments[i];
        if ((s->addr & 1u) || (uint32_t)s->addr + 2u * s->nwords > e->cfg.mem_bytes ||
            (s->nwords && s->words == NULL) || (i && s->addr <= img->segments[i - 1].addr))
            return SX_E_ARG;
        total += s->nwords;
    }
    uint8_t d[32];
    image_digest(img, d);
    if (memcmp(d, img->sha256, 32) != 0) {
        e->faults |= SX_FAULT_IMAGE_HASH; /* refused, silently: nothing is loaded or run */
        return SX_E_HASH;
    }
    uint16_t *words = malloc((total ? total : 1u) * sizeof *words);
    sx_segment *segs = malloc((img->nsegments ? img->nsegments : 1u) * sizeof *segs);
    if (words == NULL || segs == NULL) {
        free(words);
        free(segs);
        return SX_E_STATE;
    }
    uint32_t at = 0;
    for (uint32_t i = 0; i < img->nsegments; i++) {
        memcpy(words + at, img->segments[i].words, img->segments[i].nwords * sizeof *words);
        segs[i] = img->segments[i];
        segs[i].words = words + at;
        at += img->segments[i].nwords;
    }
    free(e->words);
    free(e->segs);
    e->words = words;
    e->segs = segs;
    e->nsegs = img->nsegments;
    e->entry_pc = img->entry_pc;
    e->entry_psw = img->entry_psw;
    e->loaded = 1;
    e->faults &= ~(SX_FAULT_IMAGE_MISSING | SX_FAULT_IMAGE_HASH);
    clear_memory(e->cfg.mem_bytes);
    sx_engine_home(e);
    return SX_OK;
}

/* HOME: devices to power-on state, the image deposited again, PC and PSW from the image, RUN.
 * Called from the render path (SX_CMD_RESET_HOME) too: no allocation, no I/O. */
void sx_engine_home(sx_engine *e)
{
    if (!e->loaded)
        return;
    sx_shim_reset_all();
    for (uint32_t i = 0; i < e->nsegs; i++)
        for (uint32_t k = 0; k < e->segs[i].nwords; k++)
            cpu_dev.deposit(e->segs[i].words[k], (t_addr)(e->segs[i].addr + 2u * k), &cpu_unit, 0);
    PC = e->entry_pc;
    PSW = e->entry_psw;
    /* the synth sees the devices' power-on state: every gate down, each D/A at rest */
    e->gates = 0;
    for (uint32_t c = 0; c < SX_DAC_CHANNELS; c++)
        e->dac_v[c] = sx_dac_volts(sx_dac_code[c], e->cfg.dac_word_bits, e->cfg.dac_range_v);
    /* nothing from before HOME may sound after it: every module's state (envelopes, filters, the
     * echo's lines) and the audio held in the safety chain start from rest (FLT-12) */
    sx_graph_reset(e->graph);
    sx_engine_send_all(e, e->graph);
    if (e->old)
        sx_engine_send_all(e, e->old);
    sx_safety_clear(&e->safety);
    sx_safety_clear(&e->safety_r);
    e->faults &= ~(SX_FAULT_CPU_STOPPED | SX_FAULT_PROGRAM_STALLED | SX_FAULT_DSP);
    sx_clock_halt(&e->clk);
    sx_clock_rebase(&e->clk);
    sx_clock_run(&e->clk);
    /* the program's code is the segment that holds its entry point (the tables are elsewhere) */
    uint16_t lo = e->entry_pc, hi = (uint16_t)(e->entry_pc + 2u);
    for (uint32_t i = 0; i < e->nsegs; i++) {
        uint32_t a = e->segs[i].addr, end = a + 2u * e->segs[i].nwords;
        if (e->entry_pc >= a && e->entry_pc < end) {
            lo = (uint16_t)a;
            hi = (uint16_t)(end > 0xFFFFu ? 0xFFFFu : end);
        }
    }
    sx_sup_reset(&e->sup, lo, hi);
    sx_safety_mute(&e->safety, e->staff_mute); /* a fault's mute ends; the fade-in brings it back */
    sx_safety_mute(&e->safety_r, e->staff_mute);
}

void sx_engine_fill_cpu(const sx_engine *e, sx_snapshot *s)
{
    s->pc = (uint16_t)PC;
    s->psw = (uint16_t)PSW;
    for (int i = 0; i < 16; i++)
        s->r[i] = (uint16_t)GREG[i];
    s->cc = (uint8_t)(PSW & 0xFu);
    s->dr = DR;
    s->drx = (uint8_t)DRX;
    s->sr = (uint16_t)SR;
    for (uint32_t r = 0; r < SX_KEY_ROWS; r++) {
        s->keys_raw[r] = sx_keys_rows[r];
        s->keys_seen[r] = sx_keys_seen[r];
    }
    for (uint32_t c = 0; c < SX_DAC_CHANNELS; c++) {
        s->dac_code[c] = sx_dac_code[c];
        s->dac_volts[c] = sx_dac_volts(sx_dac_code[c], e->cfg.dac_word_bits, e->cfg.dac_range_v);
    }
    s->gates = (uint16_t)sx_gate_latch;
    s->halted = (uint8_t)!e->clk.running;
    s->waiting = (uint8_t)((PSW & 0x8000u) != 0);
    s->cycles = sx_shim_now64();
}

void sx_engine_set_sr(uint32_t sr)
{
    SR = sr & 0xFFFFu;
}

void sx_keys_set(sx_engine *e, sx_key_source src, uint64_t bits)
{
    if (e == NULL)
        return;
    atomic_store_explicit(&e->arrival, atomic_load(&e->frames_pub), memory_order_release);
    sx_keys_source_set((uint32_t)src, bits);
}

int sx_command(sx_engine *e, const sx_cmd *cmd)
{
    if (e == NULL || cmd == NULL)
        return SX_E_ARG;
    uint32_t head = atomic_load_explicit(&e->q_head, memory_order_relaxed);
    uint32_t tail = atomic_load_explicit(&e->q_tail, memory_order_acquire);
    if (head - tail >= SX_CMDQ)
        return SX_E_AGAIN;
    e->q[head & (SX_CMDQ - 1u)] = *cmd;
    atomic_store_explicit(&e->q_head, head + 1u, memory_order_release);
    return SX_OK;
}

int sx_snapshot_read(sx_engine *e, sx_snapshot *out)
{
    if (e == NULL || out == NULL)
        return SX_E_ARG;
    for (int tries = 0; tries < 100000; tries++) {
        uint64_t s1 = atomic_load_explicit(&e->snap_seq, memory_order_acquire);
        if (s1 & 1u)
            continue; /* a write is in progress */
        memcpy(out, &e->snap, sizeof *out);
        atomic_thread_fence(memory_order_acquire);
        uint64_t s2 = atomic_load_explicit(&e->snap_seq, memory_order_relaxed);
        if (s1 == s2)
            return SX_OK;
    }
    return SX_E_AGAIN;
}

int sx_patch_load(sx_engine *e, const char *text, size_t len, char *err, size_t errlen)
{
    if (e == NULL || text == NULL)
        return SX_E_ARG;
    sx_patch_free(atomic_exchange(&e->retired, (sx_graph *)0)); /* the last swap's old patch */
    if (atomic_load(&e->pending) != NULL) {
        if (err && errlen)
            snprintf(err, errlen, "the last patch has not come in yet: try again");
        return SX_E_AGAIN;
    }
    sx_graph *g = sx_patch_build(text, len, (double)e->cfg.sample_rate, err, errlen);
    if (g == NULL)
        return SX_E_ARG;
    atomic_store_explicit(&e->pending, g, memory_order_release);
    return SX_OK;
}

int sx_score_load(sx_engine *e, const uint16_t *words, uint32_t n)
{
    if (e == NULL || words == NULL || n < 3u || n > SX_SCORE_WORDS ||
        SX_SCORE_ADDR + 2u * n > e->cfg.mem_bytes)
        return SX_E_ARG;
    int idle = 0;
    if (!atomic_compare_exchange_strong(&e->score_busy, &idle, 1))
        return SX_E_AGAIN;
    memcpy(e->score_stage, words, n * sizeof *words);
    e->score_n = n;
    sx_cmd c = {SX_CMD_DEPOSIT_TABLE, 0, 0, 0.0f};
    if (sx_command(e, &c) != SX_OK) {
        atomic_store(&e->score_busy, 0);
        return SX_E_AGAIN;
    }
    return SX_OK;
}

/* [RT] the deposit itself, at a period start */
void sx_engine_deposit_score(sx_engine *e)
{
    if (!atomic_load_explicit(&e->score_busy, memory_order_acquire))
        return;
    e->score_gen = (uint16_t)(e->score_gen + 1u);
    if (e->score_gen == 0)
        e->score_gen = 1; /* 0 means no tape yet */
    for (uint32_t i = 0; i < e->score_n; i++)
        cpu_dev.deposit(i ? e->score_stage[i] : e->score_gen, (t_addr)(SX_SCORE_ADDR + 2u * i),
                        &cpu_unit, 0);
    atomic_store_explicit(&e->score_busy, 0, memory_order_release);
}

size_t sx_disasm(sx_engine *e, uint16_t addr, char *buf, size_t n)
{
    if (e == NULL || buf == NULL)
        return 0;
    return sx_shim_disasm(addr, buf, n);
}

uint32_t sx_keys_reads_count(sx_engine *e)
{
    return e ? (uint32_t)sx_keys_reads : 0u; /* the device's own liveness counter (VS-16) */
}

void sx_set_io_sink(sx_engine *e, sx_io_sink sink, void *ctx)
{
    if (e == NULL)
        return;
    e->sink = sink;
    e->sink_ctx = ctx;
}
