/* rt.h: the audio callback's work (VS-13). Everything in src/host/rt/ runs on the device's
 * real-time thread and is checked by scripts/rt-lint.py: no allocation, locks, syscalls, clocks
 * or logging. The backend glue (src/host/audio.c) reads the clock once per callback and passes
 * it in; all memory is allocated before the device starts.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SXH_RT_H
#define SXH_RT_H

#include <stdatomic.h>
#include <stdint.h>

#include "seastones.h"
#include "sxhost.h"

#define SXH_SAMPLE_RING 16384u    /* PC samples: 8.7 s at 32-frame periods, 48 kHz */
#define SXH_CLOCK_RING 4096u      /* callback clock: 10.9 s at 128-frame callbacks */
#define SXH_CAPTURE_RING 1048576u /* capture: 21.8 s of mono float at 48 kHz */

typedef struct sxh_clock_ent {
    _Atomic uint64_t frame0;  /* engine frame at the callback's start */
    _Atomic uint64_t host_ns; /* host time at the callback's start */
} sxh_clock_ent;

typedef struct sxh_rt {
    /* configuration, written before the device starts */
    sx_engine *e;
    uint32_t rate;
    uint32_t sub;        /* engine period, frames */
    uint32_t channels;   /* device channels */
    uint32_t period;     /* nominal device period, frames */
    uint32_t silent;     /* SXH_AUDIO_SILENT_DEVICE */
    uint32_t count_late; /* 0 on the null device: its timer wakes in bursts by design */
    float *stereo;       /* sub x 2, allocated before start */
    sx_snapshot snap;    /* scratch for the per-period sample */

    /* state of the callback thread */
    uint64_t frames;
    uint64_t last_ns;
    int first;

    /* published to the control thread */
    _Atomic uint64_t pub_frames, callbacks, late, max_interval_ns, last_callback_ns;
    _Atomic int32_t sched_policy, sched_priority;
    _Atomic uint32_t freeze;

    /* PC samples: the callback produces, sxh_samples_read consumes */
    sxh_sample samples[SXH_SAMPLE_RING];
    _Atomic uint32_t s_head, s_tail;

    /* callback clock: written in place, read by anyone */
    sxh_clock_ent clock[SXH_CLOCK_RING];
    _Atomic uint64_t clock_n;

    /* capture: the callback produces, the writer thread consumes */
    float *cap; /* SXH_CAPTURE_RING floats, allocated before start */
    _Atomic uint32_t c_head, c_tail;
    _Atomic uint32_t capturing;
    _Atomic uint64_t cap_dropped;
    _Atomic uint64_t cap_first; /* engine frame of the first captured sample; UINT64_MAX: none */
} sxh_rt;

/* The device callback's body. `out` holds `frames` interleaved frames of rt->channels.
 * `host_ns` is the host time at the callback's start. [RT] */
void sxh_rt_render(sxh_rt *rt, float *out, uint32_t frames, uint64_t host_ns);

/* Once, on the first callback: record the thread's scheduling (the glue reads it). [RT] */
void sxh_rt_note_sched(sxh_rt *rt, int32_t policy, int32_t priority);

#endif
