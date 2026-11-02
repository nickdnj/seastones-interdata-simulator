/* rt.c: the audio callback's work (VS-13; see rt.h). RT-lint checks this file.
 *
 * Per callback: note the callback clock; then, one engine period of `sub` frames at a time,
 * sx_render into a stereo scratch buffer, take one PC sample, copy channel 0 to the capture
 * ring, and write the frames to the device's channels. With the freeze hook on (test profile)
 * the engine is not rendered at all and the device gets zeros, so `frames` stops: the stalled
 * audio thread of FLT-10.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "rt.h"

#include <string.h>

void sxh_rt_note_sched(sxh_rt *rt, int32_t policy, int32_t priority)
{
    atomic_store_explicit(&rt->sched_policy, policy, memory_order_relaxed);
    atomic_store_explicit(&rt->sched_priority, priority, memory_order_relaxed);
}

static void note_clock(sxh_rt *rt, uint64_t host_ns)
{
    uint64_t n = atomic_load_explicit(&rt->clock_n, memory_order_relaxed);
    sxh_clock_ent *c = &rt->clock[n % SXH_CLOCK_RING];
    /* a reader checks frame0 before and after reading host_ns (see sxh_frame_host_ns) */
    atomic_store_explicit(&c->frame0, UINT64_MAX, memory_order_relaxed);
    atomic_thread_fence(memory_order_release);
    atomic_store_explicit(&c->host_ns, host_ns, memory_order_relaxed);
    atomic_store_explicit(&c->frame0, rt->frames, memory_order_release);
    atomic_store_explicit(&rt->clock_n, n + 1u, memory_order_release);

    if (rt->last_ns && host_ns > rt->last_ns) {
        uint64_t dt = host_ns - rt->last_ns;
        uint64_t nominal = (uint64_t)rt->period * 1000000000u / (rt->rate ? rt->rate : 48000u);
        if (rt->count_late && dt > nominal + nominal / 2u)
            atomic_fetch_add_explicit(&rt->late, 1u, memory_order_relaxed);
        if (dt > atomic_load_explicit(&rt->max_interval_ns, memory_order_relaxed))
            atomic_store_explicit(&rt->max_interval_ns, dt, memory_order_relaxed);
    }
    rt->last_ns = host_ns;
    atomic_store_explicit(&rt->last_callback_ns, host_ns, memory_order_relaxed);
    atomic_fetch_add_explicit(&rt->callbacks, 1u, memory_order_relaxed);
}

static void take_sample(sxh_rt *rt)
{
    uint32_t head = atomic_load_explicit(&rt->s_head, memory_order_relaxed);
    uint32_t tail = atomic_load_explicit(&rt->s_tail, memory_order_acquire);
    if (head - tail >= SXH_SAMPLE_RING)
        return; /* nobody is reading: drop the newest, never block */
    /* the snapshot was published by this thread a moment ago, so the seqlock read never retries */
    if (sx_snapshot_read(rt->e, &rt->snap) != SX_OK)
        return;
    sxh_sample *p = &rt->samples[head % SXH_SAMPLE_RING];
    p->frame = rt->frames;
    p->keys_reads = sx_keys_reads_count(rt->e);
    p->pc = rt->snap.pc;
    p->halted = rt->snap.halted;
    atomic_store_explicit(&rt->s_head, head + 1u, memory_order_release);
}

static void capture(sxh_rt *rt, const float *stereo, uint32_t n)
{
    if (!atomic_load_explicit(&rt->capturing, memory_order_acquire))
        return;
    if (atomic_load_explicit(&rt->cap_first, memory_order_relaxed) == UINT64_MAX)
        atomic_store_explicit(&rt->cap_first, rt->frames - n, memory_order_release);
    uint32_t head = atomic_load_explicit(&rt->c_head, memory_order_relaxed);
    uint32_t tail = atomic_load_explicit(&rt->c_tail, memory_order_acquire);
    uint32_t room = SXH_CAPTURE_RING - (head - tail);
    uint32_t k = n < room ? n : room;
    for (uint32_t i = 0; i < k; i++)
        rt->cap[(head + i) % SXH_CAPTURE_RING] = stereo[2u * i];
    if (k < n)
        atomic_fetch_add_explicit(&rt->cap_dropped, n - k, memory_order_relaxed);
    atomic_store_explicit(&rt->c_head, head + k, memory_order_release);
}

static void to_device(const sxh_rt *rt, float *out, const float *stereo, uint32_t n)
{
    uint32_t ch = rt->channels;
    for (uint32_t i = 0; i < n; i++) {
        float l = rt->silent ? 0.0f : stereo[2u * i];
        float r = rt->silent ? 0.0f : stereo[2u * i + 1u];
        if (ch == 1u) {
            out[i] = l;
            continue;
        }
        float *f = out + (uint64_t)i * ch;
        f[0] = l;
        f[1] = r;
        for (uint32_t c = 2; c < ch; c++)
            f[c] = 0.0f;
    }
}

void sxh_rt_render(sxh_rt *rt, float *out, uint32_t frames, uint64_t host_ns)
{
    note_clock(rt, host_ns);
    if (atomic_load_explicit(&rt->freeze, memory_order_acquire) || rt->e == NULL) {
        memset(out, 0, (size_t)frames * rt->channels * sizeof *out);
        return;
    }
    uint32_t done = 0;
    while (done < frames) {
        uint32_t n = frames - done < rt->sub ? frames - done : rt->sub;
        sx_render(rt->e, rt->stereo, n);
        rt->frames += n;
        take_sample(rt);
        capture(rt, rt->stereo, n);
        to_device(rt, out + (uint64_t)done * rt->channels, rt->stereo, n);
        done += n;
    }
    atomic_store_explicit(&rt->pub_frames, rt->frames, memory_order_release);
}
