/*
 * sxlat: S-1a native audio latency harness (SP-S1A). Spike code, not shipped.
 *
 * Shared state between the tone generator (real-time callback) and the
 * backends. The callback path (sxlat_render) does no allocation, no locks,
 * no syscalls and no logging: it only writes samples, bumps counters and
 * pushes fixed-size records into a single-producer single-consumer ring.
 */
#ifndef SXLAT_H
#define SXLAT_H

#include <stdatomic.h>
#include <stdint.h>

#define SXLAT_HIST_BINS 64      /* callback-interval histogram, 0.25 ms bins */
#define SXLAT_HIST_BIN_US 250
#define SXLAT_RING 1024         /* step-event ring, power of two */

typedef enum {
    SXLAT_MODE_SILENT = 0, /* zeros: smoke runs on a shared Mac make no sound */
    SXLAT_MODE_STEP,       /* silence, then a tone from step_frame on */
    SXLAT_MODE_PULSES,     /* tone bursts every interval_frames (loopback rig) */
    SXLAT_MODE_HOLD        /* loud continuous tone (S-6 fault-injection target) */
} sxlat_mode;

typedef struct {
    uint32_t index;          /* step number, from 0 */
    uint64_t frame;          /* sample frame at which the tone starts */
    uint64_t cb_host_ns;     /* host monotonic time at the callback start */
    uint32_t cb_offset;      /* frame offset of the step inside the callback */
    uint32_t latency_frames; /* backend's reported output latency at that time */
} sxlat_event;

typedef struct {
    /* configuration (written before start, read-only after) */
    sxlat_mode mode;
    uint32_t rate;
    uint32_t channels;
    uint32_t period;
    uint64_t step_frame;
    uint64_t interval_frames;
    uint64_t burst_frames;
    double tone_hz;
    float amp;

    /* real-time state (callback thread only) */
    uint64_t frames;
    double phase;
    uint64_t next_step;
    uint32_t step_index;
    uint64_t last_cb_ns;

    /* counters (written by the callback or backend, read at the end) */
    atomic_uint_fast64_t callbacks;
    atomic_uint_fast64_t xruns;
    atomic_uint_fast64_t late_callbacks; /* interval > 1.5 periods */
    atomic_uint_fast64_t hist[SXLAT_HIST_BINS];
    atomic_uint_fast64_t max_interval_ns;
    atomic_uint_fast32_t latency_frames; /* backend writes, callback reads */

    /* event ring: callback produces, logger thread consumes */
    sxlat_event ring[SXLAT_RING];
    atomic_uint_fast32_t ring_head;
    atomic_uint_fast32_t ring_tail;
    atomic_uint_fast64_t ring_dropped;
} sxlat_state;

/* Real-time safe. Fills `frames` interleaved frames of `st->channels`. */
void sxlat_render(sxlat_state *st, float *out, uint32_t frames, uint64_t cb_host_ns);

/* Monotonic host clock in ns (CLOCK_MONOTONIC_RAW on Linux, mach time on the Mac). */
uint64_t sxlat_now_ns(void);

/* Backend interface. Each returns 0 on success and fills a short JSON fragment. */
typedef struct {
    char name[32];
    char device[128];
    uint32_t actual_rate;
    uint32_t actual_period;
    uint32_t buffer_frames;
    uint32_t reported_latency_frames; /* device + safety + buffer, or snd_pcm_delay */
    char latency_detail[512];         /* JSON object text, backend specific */
    char sched[64];                   /* SCHED_FIFO status */
} sxlat_backend_info;

int sxlat_backend_open(sxlat_state *st, const char *device, sxlat_backend_info *info);
int sxlat_backend_start(sxlat_state *st);
void sxlat_backend_stop(sxlat_state *st, sxlat_backend_info *info);

#endif
