/* engine_int.h: the engine object behind seastones.h (VS-12). Internal to src/engine.
 *
 * engine.c holds the non-RT and any-thread entry points (create, load, keys, commands,
 * snapshot read, disassembly); render/render.c holds sx_render, the real-time path, which
 * RT-lint checks. This header includes no SIMH header.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_ENGINE_INT_H
#define SX_ENGINE_INT_H

#include <stdatomic.h>
#include <stdint.h>

#include "auth.h"
#include "clock.h"
#include "graph.h"
#include "safety.h"
#include "supervisor.h"
#include "seastones.h"
#if defined(SX_TEST_HOOKS)
#include "seastones_test.h"
#endif

#define SX_CMDQ 256u            /* command ring, a power of two */
#define SX_SCOPE_DECIM 4u       /* scope: every 4th output sample, 512 points = 43 ms */
#define SX_ONSET_LEVEL 0.003162 /* -50 dBFS: Method B onset */
#define SX_SCORE_ADDR 0x2000u
#define SX_SCORE_WORDS 12288u /* the 24 KB score area */
#define SX_FADE_S 0.005       /* a patch change's crossfade (ARCHITECTURE 11.3) */

struct sx_engine {
    sx_config cfg;
    sx_clock clk;
    sx_dev_ev *ev;
    uint32_t ev_cap;
    sx_dev_ev *aev; /* the period's writes after the authenticity stage (ev_cap) */
    sx_authst authst;
    sx_safety safety, safety_r; /* left and right: the same chain, each its own guarantee */
    float *bl, *br, *fl, *fr;   /* cfg.max_frames each: the bus, and the outgoing patch's */

    /* the patch graph (PM-05): the live one, the one fading out, and the hand-offs with the
     * non-RT side (pending: built and waiting; retired: done with, to be freed) */
    sx_graph *graph, *old;
    _Atomic(sx_graph *) pending;
    _Atomic(sx_graph *) retired;
    uint32_t fade, fade_len;
    uint32_t patch_seq;
    float dac_v[SX_DAC_CHANNELS]; /* each D/A channel's volts as the synth last received them */

    /* commands: single producer (the host's one writer, ARCHITECTURE 4.5), the render consumes */
    sx_cmd q[SX_CMDQ];
    _Atomic uint32_t q_head, q_tail;

    /* the snapshot, published every period through a seqlock */
    _Atomic uint64_t snap_seq;
    sx_snapshot snap;
    uint64_t periods;

    /* the loaded image, kept for HOME */
    uint16_t *words; /* all segments' words, in order */
    sx_segment *segs;
    uint32_t nsegs;
    uint16_t entry_pc, entry_psw;
    int loaded;

    uint32_t faults;
    uint32_t speed; /* enum sx_speed, or SX_SPEED_DIVISOR */
    uint32_t xruns;
    uint32_t nonfinite_seen;

    /* latency (Method B) */
    _Atomic uint64_t frames_pub; /* frames rendered, for sx_keys_set's arrival stamp */
    _Atomic uint64_t arrival;
    uint64_t keys_prev;
    uint64_t lat_t[SX_LAT_N];
    int wait_write, wait_onset;
    uint64_t gate_rise;  /* frame of the gate rise that the onset waits for; 0 = none yet */
    uint32_t rises_seen; /* the live graph's envelope gate rises, as last looked at */
    uint32_t lat_hist[SX_LAT_BINS];

    uint16_t gates; /* the gate latch as the synth last received it */

    float scope[SX_SCOPE_POINTS];
    uint32_t scope_pos, scope_phase;

    sx_io_sink sink;
    void *sink_ctx;
    uint32_t auth;     /* enum sx_auth in force */
    sx_supervisor sup; /* VS-16 */
    int staff_mute;    /* SX_CMD_MUTE; the supervisor's mute is separate */
    int home_pending;  /* HOME asked: muting, then the reset (render.c) */
    /* the score table waiting for SX_CMD_DEPOSIT_TABLE (sx_score_load) */
    uint16_t *score_stage;
    uint32_t score_n;
    uint16_t score_gen;
    _Atomic int score_busy;
    /* the staff test tone (SX_CMD_TEST_TONE), off unless asked for */
    double tone_phase, tone_inc, tone_gain, tone_target, tone_step;
    uint32_t refused; /* commands the profile refused */

#if defined(SX_TEST_HOOKS) /* the test profile only (VS-27) */
    sx_event_tap tap;
    void *tap_ctx;
    const sx_trace_ev *replay;
    uint32_t replay_n, replay_pos;
    _Atomic uint32_t inject;
#endif
};

/* engine.c helpers the render path calls */
void sx_engine_home(sx_engine *e);                           /* reload the image, RUN */
void sx_engine_fill_cpu(const sx_engine *e, sx_snapshot *s); /* CPU and device fields */
void sx_engine_deposit_score(sx_engine *e);         /* [RT] the staged score table, at X'2000' */
void sx_engine_set_sr(uint32_t sr);                 /* the switch register */
void sx_engine_send_all(sx_engine *e, sx_graph *g); /* every source's value into a graph */

#endif
