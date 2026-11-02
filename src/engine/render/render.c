/* render.c: sx_render, the real-time path (VS-12, PM-05; ARCHITECTURE 4.2). RT-lint checks this
 * file: no allocation, locks, syscalls, clocks or logging.
 *
 * One period of N frames:
 *   1. apply the queued commands; take a queued patch (it comes in with a 5 ms crossfade)
 *   2. latch the key bitmap (the period-start latch); note a new press for Method B
 *   3. run the CPU to the period's end on the emulated clock; every D/A and gate write comes back
 *      stamped with its frame (the devices-to-DSP seam, ARCHITECTURE 12.1)
 *   4. the authenticity stage (strobed, research jitter) re-times the writes when it is on
 *   5. render the patch graph in slices between those frames, applying each write at its frame;
 *      during a patch change, the outgoing graph too, crossfaded
 *   6. the safety chain on L and on R
 *   7. publish the snapshot (seqlock)
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "engine_int.h"

#include "id_seastones.h"
#include "keys.h"
#include "sx_math.h"

#if defined(SX_TEST_HOOKS)
static volatile float nonfinite_zero = 0.0f; /* for the injected NaN and Inf */
#endif

static void apply(sx_engine *e, const sx_cmd *c)
{
    switch (c->kind) {
    case SX_CMD_RUN:
        if (e->loaded)
            sx_clock_run(&e->clk);
        break;
    case SX_CMD_HALT:
        sx_clock_halt(&e->clk);
        break;
    case SX_CMD_STEP:
        sx_clock_step(&e->clk);
        break;
    case SX_CMD_SPEED:
        if (c->a < SX_SPEED_NPOS && sx_clock_set_speed(&e->clk, c->a) == 0)
            e->speed = c->a;
        else if (c->a == SX_SPEED_DIVISOR && c->b >= 1u && sx_clock_set_divisor(&e->clk, c->b) == 0)
            e->speed = SX_SPEED_DIVISOR;
        break;
    case SX_CMD_RESET_HOME: /* fade out over the 5 ms mute ramp first, then reset (period) */
        if (e->loaded)
            e->home_pending = 1;
        break;
    case SX_CMD_SR_SET:
        sx_engine_set_sr(c->a & 0xFFFFu); /* the host bounds-checks it (PANEL-4) */
        break;
    case SX_CMD_CEILING:
        sx_safety_set_ceiling(&e->safety, (double)c->f, e->safety.quiet_dbfs);
        sx_safety_set_ceiling(&e->safety_r, (double)c->f, e->safety_r.quiet_dbfs);
        break;
    case SX_CMD_VOLUME:
        sx_safety_set_volume(&e->safety, (double)c->f);
        sx_safety_set_volume(&e->safety_r, (double)c->f);
        break;
    case SX_CMD_PATCH: /* patch.param: the live graph's module a, parameter b, to f */
        sx_graph_param(e->graph, c->a, c->b, (double)c->f);
        break;
    case SX_CMD_MUTE:
        e->staff_mute = c->a != 0;
        break;
    case SX_CMD_AUTH_MODE:
#if defined(SX_PROFILE_PRODUCTION)
        if (c->a == SX_AUTH_JITTER) { /* research only: not on the floor (VS-27) */
            e->refused++;
            break;
        }
#endif
        if (c->a <= SX_AUTH_JITTER) {
            e->auth = c->a;
            sx_auth_set_mode(&e->authst, c->a, e->clk.frame);
            sx_graph_set_analog(e->graph, c->a == SX_AUTH_ANALOG, (double)e->cfg.dac_output_hz);
            if (e->old)
                sx_graph_set_analog(e->old, c->a == SX_AUTH_ANALOG, (double)e->cfg.dac_output_hz);
        }
        break;
    case SX_CMD_TEST_TONE: {
        double hz = c->b ? (double)c->b : 1000.0, db = c->f != 0.0f ? (double)c->f : -20.0;
        hz = hz < 100.0 ? 100.0 : (hz > 4000.0 ? 4000.0 : hz);
        db = !(db >= -60.0) ? -60.0 : (db > -12.0 ? -12.0 : db); /* never near the limiter */
        e->tone_inc = hz / (double)e->cfg.sample_rate;
        e->tone_target = c->a ? sx_db_to_lin(db) : 0.0;
        double span = e->tone_target > e->tone_gain ? e->tone_target : e->tone_gain;
        e->tone_step = span / (0.010 * (double)e->cfg.sample_rate); /* 10 ms either way */
        break;
    }
    case SX_CMD_DEPOSIT_TABLE:
        sx_engine_deposit_score(e);
        break;
    default:
        break;
    }
}

/* the staff test tone: added to both channels before the safety chain, ramped in and out */
static void test_tone(sx_engine *e, uint32_t n)
{
    if (e->tone_gain == 0.0 && e->tone_target == 0.0)
        return;
    for (uint32_t i = 0; i < n; i++) {
        double d = e->tone_target - e->tone_gain;
        e->tone_gain = d > e->tone_step    ? e->tone_gain + e->tone_step
                       : d < -e->tone_step ? e->tone_gain - e->tone_step
                                           : e->tone_target;
        e->tone_phase += e->tone_inc;
        if (e->tone_phase >= 1.0)
            e->tone_phase -= 1.0;
        float v = (float)(e->tone_gain * sx_sin_cycles(e->tone_phase));
        e->bl[i] += v;
        e->br[i] += v;
    }
}

static void latch_keys(sx_engine *e, uint64_t frame0)
{
    sx_keys_latch();
    uint64_t raw = sx_keys_raw_bits();
    if (raw & ~e->keys_prev) { /* a new press: start a Method B record */
        e->lat_t[SX_LAT_ARRIVAL] = atomic_load_explicit(&e->arrival, memory_order_acquire);
        e->lat_t[SX_LAT_LATCH] = frame0;
        e->lat_t[SX_LAT_FIRST_WRITE] = e->lat_t[SX_LAT_ONSET] = 0;
        e->wait_write = e->wait_onset = 1;
        e->gate_rise = 0;
    }
    e->keys_prev = raw;
}

static void to_graph(sx_graph *g, uint32_t src, float v)
{
    if (g)
        sx_graph_event(g, src, v);
}

/* the onset waits for an envelope's gate to rise in the live patch */
static void note_rise(sx_engine *e)
{
    if (e->wait_onset && !e->gate_rise && e->graph->rises != e->rises_seen)
        e->gate_rise = e->graph->rise_frame;
    e->rises_seen = e->graph->rises;
}

static void on_event(sx_engine *e, const sx_dev_ev *ev, uint64_t frame0)
{
    if (ev->dev == SX_D_DAC && ev->ch < SX_DAC_CHANNELS) {
        float v = sx_dac_volts(ev->val, e->cfg.dac_word_bits, e->cfg.dac_range_v);
        e->dac_v[ev->ch] = v;
        to_graph(e->graph, ev->ch, v);
        to_graph(e->old, ev->ch, v);
    } else if (ev->dev == SX_D_GATE) {
        uint16_t changed = (uint16_t)(ev->val ^ e->gates);
        for (uint32_t i = 0; i < 16u; i++) {
            uint16_t m = (uint16_t)(0x8000u >> i);
            if (changed & m) {
                float v = (ev->val & m) ? SX_GATE_V : 0.0f;
                to_graph(e->graph, 16u + i, v);
                to_graph(e->old, 16u + i, v);
            }
        }
        e->gates = ev->val;
    }
    note_rise(e);
    if (e->wait_write && (ev->dev == SX_D_DAC || ev->dev == SX_D_GATE)) {
        uint64_t f = frame0 + ev->frame;
        e->lat_t[SX_LAT_FIRST_WRITE] = f;
        e->wait_write = 0;
        uint64_t us = (f - e->lat_t[SX_LAT_LATCH]) * 1000000u / e->cfg.sample_rate;
        uint64_t bin = us / SX_LAT_BIN_US;
        e->lat_hist[bin < SX_LAT_BINS ? bin : SX_LAT_BINS - 1u]++;
    }
}

/* every source as the synth last received it, into a graph that has just come in */
void sx_engine_send_all(sx_engine *e, sx_graph *g)
{
    for (uint32_t c = 0; c < SX_DAC_CHANNELS; c++)
        sx_graph_event(g, c, e->dac_v[c]);
    for (uint32_t i = 0; i < 16u; i++)
        sx_graph_event(g, 16u + i, (e->gates & (0x8000u >> i)) ? SX_GATE_V : 0.0f);
}

/* a queued patch comes in at the period boundary, crossfaded over SX_FADE_S */
static void take_patch(sx_engine *e, uint64_t frame0)
{
    if (e->old || atomic_load_explicit(&e->retired, memory_order_acquire) != NULL)
        return;
    sx_graph *g = atomic_exchange_explicit(&e->pending, (sx_graph *)0, memory_order_acq_rel);
    if (g == NULL)
        return;
    g->frame = frame0;
    sx_graph_set_analog(g, e->auth == SX_AUTH_ANALOG, (double)e->cfg.dac_output_hz);
    sx_engine_send_all(e, g);
    e->old = e->graph;
    e->graph = g;
    e->rises_seen = g->rises;
    e->fade = e->fade_len;
    e->patch_seq++;
}

static void render_slice(sx_engine *e, uint32_t pos, uint32_t k)
{
    sx_graph_render(e->graph, k, e->bl + pos, e->br + pos);
    note_rise(e);
    if (e->old == NULL)
        return;
    sx_graph_render(e->old, k, e->fl + pos, e->fr + pos);
    for (uint32_t i = pos; i < pos + k && e->fade; i++) {
        double w = (double)(e->fade_len - e->fade) / (double)e->fade_len; /* the new patch's */
        e->bl[i] = (float)((double)e->fl[i] * (1.0 - w) + (double)e->bl[i] * w);
        e->br[i] = (float)((double)e->fr[i] * (1.0 - w) + (double)e->br[i] * w);
        e->fade--;
    }
    if (e->fade == 0) { /* done with the old one: the non-RT side frees it */
        atomic_store_explicit(&e->retired, e->old, memory_order_release);
        e->old = NULL;
    }
}

static void publish(sx_engine *e, uint64_t frames)
{
    uint64_t s = atomic_load_explicit(&e->snap_seq, memory_order_relaxed);
    atomic_store_explicit(&e->snap_seq, s + 1u, memory_order_relaxed);
    atomic_thread_fence(memory_order_release);
    sx_snapshot *p = &e->snap;
    p->seq = ++e->periods;
    p->frames = frames;
    sx_engine_fill_cpu(e, p);
    p->muted = (uint8_t)e->safety.muted;
    p->speed = e->speed;
    p->faults = e->faults;
    p->xruns = e->xruns;
    p->patch_seq = e->patch_seq;
    p->path_to_out = e->graph->path_to_out;
    p->fading = e->old != NULL;
    p->auth = e->auth;
    for (uint32_t i = 0; i < SX_SCOPE_POINTS; i++)
        p->scope[i] = e->scope[(e->scope_pos + i) % SX_SCOPE_POINTS];
    for (uint32_t i = 0; i < SX_LAT_BINS; i++)
        p->lat_hist[i] = e->lat_hist[i];
    for (uint32_t i = 0; i < SX_LAT_N; i++)
        p->lat_t[i] = e->lat_t[i];
    atomic_store_explicit(&e->snap_seq, s + 2u, memory_order_release);
}

static void period(sx_engine *e, float *out_lr, uint32_t n)
{
    uint64_t frame0 = e->clk.frame;
    uint32_t tail = atomic_load_explicit(&e->q_tail, memory_order_relaxed);
    uint32_t head = atomic_load_explicit(&e->q_head, memory_order_acquire);
    for (; tail != head; tail++)
        apply(e, &e->q[tail & (SX_CMDQ - 1u)]);
    atomic_store_explicit(&e->q_tail, tail, memory_order_release);
    if (e->home_pending && e->safety.out_gain == 0.0 && e->safety_r.out_gain == 0.0) {
        sx_engine_home(e); /* silent now: nothing is cut off mid-sound */
        e->home_pending = 0;
    }
    take_patch(e, frame0);

    latch_keys(e, frame0);
#if defined(SX_TEST_HOOKS)
    if (e->replay) { /* VS-26: the trace's writes instead of the CPU's, same seam below */
        uint32_t k = 0;
        while (e->replay_pos < e->replay_n && e->replay[e->replay_pos].frame < frame0 + n &&
               k < e->ev_cap) {
            const sx_trace_ev *t = &e->replay[e->replay_pos++];
            sx_dev_ev *d = &e->clk.ev[k++];
            d->frame = t->frame > frame0 ? (uint32_t)(t->frame - frame0) : 0u;
            d->dev = t->dev;
            d->ch = t->ch;
            d->val = t->val;
        }
        e->clk.ev_n = k;
        e->clk.frame += n;
    } else
#endif
        if (e->loaded) {
        sx_clock_period(&e->clk, n);
        sx_sup_check_cpu(&e->sup, &e->clk); /* VS-16, in emulated time */
    } else {
        e->clk.ev_n = 0;
        e->clk.frame += n;
    }

    /* the authenticity stage: strobed and research jitter re-time the writes */
    const sx_dev_ev *ev = e->clk.ev;
    uint32_t nev = e->clk.ev_n;
    if (e->auth == SX_AUTH_STROBED || e->auth == SX_AUTH_JITTER) {
        nev = sx_auth_process(&e->authst, e->clk.ev, e->clk.ev_n, frame0, n, e->aev, e->ev_cap);
        ev = e->aev;
    }

    e->graph->frame = frame0;
    if (e->old)
        e->old->frame = frame0;
    uint32_t pos = 0;
    for (uint32_t i = 0; i < nev; i++) {
        if (ev[i].frame > pos) {
            render_slice(e, pos, ev[i].frame - pos);
            pos = ev[i].frame;
        }
        on_event(e, &ev[i], frame0);
#if defined(SX_TEST_HOOKS)
        if (e->tap) {
            sx_trace_ev t = {frame0 + ev[i].frame, ev[i].dev, ev[i].ch, ev[i].val};
            e->tap(e->tap_ctx, &t);
        }
#endif
    }
    if (pos < n)
        render_slice(e, pos, n - pos);

#if defined(SX_TEST_HOOKS)
    uint32_t inj = atomic_exchange(&e->inject, 0u);
    if (inj && n) /* DSP-20: a non-finite sample where the synth's output enters the chain */
        e->bl[n / 2u] =
            inj == SX_INJECT_NAN ? nonfinite_zero / nonfinite_zero : 1.0f / nonfinite_zero;
#endif
    test_tone(e, n);
    sx_sup_check_audio(&e->sup, e->bl, n, frame0, 0);
    /* any supervisor fault mutes, through the 5 ms ramp, until HOME (ARCHITECTURE 8.1) */
    const uint32_t sup_bits = SX_FAULT_PROGRAM_STALLED | SX_FAULT_DSP | SX_FAULT_CPU_STOPPED;
    int mute = e->staff_mute || e->home_pending || (e->sup.faults & sup_bits);
    sx_safety_mute(&e->safety, mute);
    sx_safety_mute(&e->safety_r, mute);
    sx_safety_process(&e->safety, e->bl, n);
    sx_safety_process(&e->safety_r, e->br, n);
    uint32_t nf = e->safety.nonfinite + e->safety_r.nonfinite;
    if (nf != e->nonfinite_seen) { /* caught and reset; repeated is a fault */
        sx_sup_check_audio(&e->sup, e->bl, 0, frame0, nf - e->nonfinite_seen);
        e->nonfinite_seen = nf;
        sx_graph_reset(e->graph); /* the module state that made it starts again */
    }
    e->faults = (e->faults & ~sup_bits) | (e->sup.faults & sup_bits);
    for (uint32_t i = 0; i < n; i++) {
        float y = e->bl[i];
        out_lr[2 * i] = y;
        out_lr[2 * i + 1] = e->br[i];
        /* onset: the output, which runs SX_SAFETY_LATENCY behind the synth, above -50 dBFS
         * at or after the gate rise reaches it */
        if (e->wait_onset && e->gate_rise && frame0 + i >= e->gate_rise + SX_SAFETY_LATENCY &&
            (y > SX_ONSET_LEVEL || y < -SX_ONSET_LEVEL)) {
            e->lat_t[SX_LAT_ONSET] = frame0 + i;
            e->wait_onset = 0;
        }
        if (++e->scope_phase == SX_SCOPE_DECIM) {
            e->scope_phase = 0;
            e->scope[e->scope_pos] = y;
            e->scope_pos = (e->scope_pos + 1u) % SX_SCOPE_POINTS;
        }
    }
    atomic_store_explicit(&e->frames_pub, frame0 + n, memory_order_release);
    publish(e, frame0 + n);
}

void sx_render(sx_engine *e, float *out_lr, uint32_t frames)
{
    if (e == NULL || out_lr == NULL)
        return;
    while (frames) {
        uint32_t n = frames < e->cfg.max_frames ? frames : e->cfg.max_frames;
        period(e, out_lr, n);
        out_lr += 2u * n;
        frames -= n;
    }
}
