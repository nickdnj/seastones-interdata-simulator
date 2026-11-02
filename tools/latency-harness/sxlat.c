/*
 * sxlat: S-1a native audio latency harness (SP-S1A). Spike code, not shipped.
 *
 * Usage: sxlat [--mode silent|step|pulses|hold] [--period 128] [--rate 48000]
 *              [--seconds 10] [--device hw:1,0] [--step-ms 500]
 *              [--interval-ms 250] [--burst-ms 50] [--tone-hz 1000]
 *              [--amp-dbfs -12] [--events FILE] [--trigger PATH]
 *
 * Prints one JSON report on stdout when it stops (after --seconds, or on
 * SIGINT/SIGTERM). kill -9 and SIGSTOP are deliberately not handled: that
 * is what S-6 measures at the line output.
 *
 * --events FILE writes one JSON line per tone onset (frame, host time,
 * reported output latency). --trigger PATH writes one byte per onset to a
 * serial device for the QA loopback rig's Pico (from the logger thread, not
 * the audio thread, so its own jitter is in the log as trigger_ns - cb_host_ns).
 */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "sxlat.h"

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifdef __APPLE__
#include <mach/mach_time.h>
uint64_t sxlat_now_ns(void) {
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0) mach_timebase_info(&tb);
    return mach_absolute_time() * tb.numer / tb.denom;
}
#else
uint64_t sxlat_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
#endif

static void push_event(sxlat_state *st, const sxlat_event *ev) {
    uint_fast32_t head = atomic_load_explicit(&st->ring_head, memory_order_relaxed);
    uint_fast32_t tail = atomic_load_explicit(&st->ring_tail, memory_order_acquire);
    if (head - tail >= SXLAT_RING) {
        atomic_fetch_add_explicit(&st->ring_dropped, 1, memory_order_relaxed);
        return;
    }
    st->ring[head & (SXLAT_RING - 1)] = *ev;
    atomic_store_explicit(&st->ring_head, head + 1, memory_order_release);
}

static int tone_on(const sxlat_state *st, uint64_t f) {
    switch (st->mode) {
    case SXLAT_MODE_SILENT: return 0;
    case SXLAT_MODE_HOLD: return 1;
    case SXLAT_MODE_STEP: return f >= st->step_frame;
    case SXLAT_MODE_PULSES:
        if (f < st->step_frame) return 0;
        return ((f - st->step_frame) % st->interval_frames) < st->burst_frames;
    }
    return 0;
}

void sxlat_render(sxlat_state *st, float *out, uint32_t frames, uint64_t cb_host_ns) {
    /* callback interval statistics */
    if (st->last_cb_ns != 0 && cb_host_ns > st->last_cb_ns) {
        uint64_t d = cb_host_ns - st->last_cb_ns;
        uint64_t bin = d / (SXLAT_HIST_BIN_US * 1000ull);
        if (bin >= SXLAT_HIST_BINS) bin = SXLAT_HIST_BINS - 1;
        atomic_fetch_add_explicit(&st->hist[bin], 1, memory_order_relaxed);
        uint64_t period_ns = (uint64_t)st->period * 1000000000ull / st->rate;
        if (d * 2 > period_ns * 3) atomic_fetch_add_explicit(&st->late_callbacks, 1, memory_order_relaxed);
        if (d > atomic_load_explicit(&st->max_interval_ns, memory_order_relaxed))
            atomic_store_explicit(&st->max_interval_ns, d, memory_order_relaxed);
    }
    st->last_cb_ns = cb_host_ns;
    atomic_fetch_add_explicit(&st->callbacks, 1, memory_order_relaxed);

    const double inc = 2.0 * M_PI * st->tone_hz / (double)st->rate;
    for (uint32_t i = 0; i < frames; i++) {
        uint64_t f = st->frames + i;
        int on = tone_on(st, f);
        if (on && (f == 0 || !tone_on(st, f - 1))) {
            /* onset: restart at the crest (cosine) so the edge is one sample sharp */
            st->phase = M_PI / 2.0;
            sxlat_event ev = {
                .index = st->step_index++,
                .frame = f,
                .cb_host_ns = cb_host_ns,
                .cb_offset = i,
                .latency_frames = (uint32_t)atomic_load_explicit(&st->latency_frames, memory_order_relaxed),
            };
            push_event(st, &ev);
        }
        float s = on ? st->amp * (float)sin(st->phase) : 0.0f;
        if (on) {
            st->phase += inc;
            if (st->phase >= 2.0 * M_PI) st->phase -= 2.0 * M_PI;
        }
        for (uint32_t c = 0; c < st->channels; c++) out[i * st->channels + c] = s;
    }
    st->frames += frames;
}

/* ---------------------------------------------------------------- non-RT */

static volatile sig_atomic_t g_stop = 0;
static void on_signal(int sig) { (void)sig; g_stop = 1; }

typedef struct {
    sxlat_state *st;
    FILE *events;
    int trigger_fd;
    uint64_t written;
} logger_ctx;

static void drain(logger_ctx *lc) {
    sxlat_state *st = lc->st;
    for (;;) {
        uint_fast32_t tail = atomic_load_explicit(&st->ring_tail, memory_order_relaxed);
        uint_fast32_t head = atomic_load_explicit(&st->ring_head, memory_order_acquire);
        if (tail == head) return;
        sxlat_event ev = st->ring[tail & (SXLAT_RING - 1)];
        atomic_store_explicit(&st->ring_tail, tail + 1, memory_order_release);
        uint64_t trig_ns = 0;
        if (lc->trigger_fd >= 0) {
            unsigned char b = 'T';
            if (write(lc->trigger_fd, &b, 1) == 1) trig_ns = sxlat_now_ns();
        }
        if (lc->events) {
            fprintf(lc->events,
                    "{\"index\":%u,\"frame\":%llu,\"cb_host_ns\":%llu,\"cb_offset\":%u,"
                    "\"latency_frames\":%u,\"trigger_ns\":%llu}\n",
                    ev.index, (unsigned long long)ev.frame, (unsigned long long)ev.cb_host_ns, ev.cb_offset,
                    ev.latency_frames, (unsigned long long)trig_ns);
        }
        lc->written++;
    }
}

static void *logger_main(void *arg) {
    logger_ctx *lc = arg;
    struct timespec ts = {0, 2000000}; /* 2 ms */
    while (!g_stop) {
        drain(lc);
        nanosleep(&ts, NULL);
    }
    drain(lc);
    return NULL;
}

static void usage(void) {
    fprintf(stderr,
            "usage: sxlat [--mode silent|step|pulses|hold] [--period N] [--rate HZ] [--seconds S]\n"
            "             [--device NAME] [--step-ms MS] [--interval-ms MS] [--burst-ms MS]\n"
            "             [--tone-hz HZ] [--amp-dbfs DB] [--events FILE] [--trigger PATH]\n");
}

int main(int argc, char **argv) {
    static sxlat_state st; /* static: large ring, zero-initialised */
    st.mode = SXLAT_MODE_SILENT;
    st.rate = 48000;
    st.channels = 2;
    st.period = 128;
    st.tone_hz = 1000.0;
    double seconds = 10.0, step_ms = 500.0, interval_ms = 250.0, burst_ms = 50.0, amp_db = -12.0;
    const char *device = NULL, *events_path = NULL, *trigger_path = NULL;

    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = (i + 1 < argc) ? argv[i + 1] : NULL;
#define ARG(name) (strcmp(a, name) == 0 && v && ++i)
        if (ARG("--mode")) {
            if (!strcmp(v, "silent")) st.mode = SXLAT_MODE_SILENT;
            else if (!strcmp(v, "step")) st.mode = SXLAT_MODE_STEP;
            else if (!strcmp(v, "pulses")) st.mode = SXLAT_MODE_PULSES;
            else if (!strcmp(v, "hold")) st.mode = SXLAT_MODE_HOLD;
            else { usage(); return 2; }
        } else if (ARG("--period")) st.period = (uint32_t)atoi(v);
        else if (ARG("--rate")) st.rate = (uint32_t)atoi(v);
        else if (ARG("--seconds")) seconds = atof(v);
        else if (ARG("--device")) device = v;
        else if (ARG("--step-ms")) step_ms = atof(v);
        else if (ARG("--interval-ms")) interval_ms = atof(v);
        else if (ARG("--burst-ms")) burst_ms = atof(v);
        else if (ARG("--tone-hz")) st.tone_hz = atof(v);
        else if (ARG("--amp-dbfs")) amp_db = atof(v);
        else if (ARG("--events")) events_path = v;
        else if (ARG("--trigger")) trigger_path = v;
        else { usage(); return 2; }
#undef ARG
    }
    if (st.period == 0 || st.rate == 0 || interval_ms <= 0 || burst_ms <= 0 || burst_ms >= interval_ms) {
        usage();
        return 2;
    }
    st.amp = (float)pow(10.0, amp_db / 20.0);

    sxlat_backend_info info;
    memset(&info, 0, sizeof info);
    if (sxlat_backend_open(&st, device, &info) != 0) {
        printf("{\"ok\":false,\"error\":\"backend open failed\",\"backend\":\"%s\",\"device\":\"%s\"}\n", info.name,
               info.device);
        return 1;
    }
    /* frame-based parameters use the rate actually granted */
    st.rate = info.actual_rate ? info.actual_rate : st.rate;
    st.step_frame = (uint64_t)(step_ms * st.rate / 1000.0);
    st.interval_frames = (uint64_t)(interval_ms * st.rate / 1000.0);
    st.burst_frames = (uint64_t)(burst_ms * st.rate / 1000.0);

    logger_ctx lc = {.st = &st, .events = NULL, .trigger_fd = -1, .written = 0};
    if (events_path && !(lc.events = fopen(events_path, "w"))) {
        fprintf(stderr, "sxlat: cannot open %s: %s\n", events_path, strerror(errno));
        return 1;
    }
    if (trigger_path && (lc.trigger_fd = open(trigger_path, O_WRONLY | O_NOCTTY)) < 0) {
        fprintf(stderr, "sxlat: cannot open trigger %s: %s\n", trigger_path, strerror(errno));
        return 1;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    pthread_t logger;
    pthread_create(&logger, NULL, logger_main, &lc);

    uint64_t t_start = sxlat_now_ns();
    if (sxlat_backend_start(&st) != 0) {
        g_stop = 1;
        pthread_join(logger, NULL);
        printf("{\"ok\":false,\"error\":\"backend start failed\",\"backend\":\"%s\"}\n", info.name);
        return 1;
    }
    while (!g_stop && (double)(sxlat_now_ns() - t_start) / 1e9 < seconds) {
        struct timespec ts = {0, 20000000};
        nanosleep(&ts, NULL);
    }
    sxlat_backend_stop(&st, &info);
    double elapsed = (double)(sxlat_now_ns() - t_start) / 1e9;
    g_stop = 1;
    pthread_join(logger, NULL);
    if (lc.events) fclose(lc.events);
    if (lc.trigger_fd >= 0) close(lc.trigger_fd);

    static const char *mode_names[] = {"silent", "step", "pulses", "hold"};
    double lat_ms = 1000.0 * info.reported_latency_frames / st.rate;
    printf("{\"ok\":true,\"harness\":\"sxlat\",\"spike\":\"S-1a\",\"backend\":\"%s\",\"device\":\"%s\","
           "\"mode\":\"%s\",\"rate\":%u,\"period_requested\":%u,\"period_actual\":%u,\"buffer_frames\":%u,"
           "\"elapsed_s\":%.3f,\"frames\":%llu,\"callbacks\":%llu,\"xruns\":%llu,\"late_callbacks\":%llu,"
           "\"max_callback_interval_ms\":%.3f,\"output_latency_frames\":%u,\"output_latency_ms\":%.3f,"
           "\"latency_detail\":%s,\"sched\":\"%s\",\"onsets_logged\":%llu,\"events_dropped\":%llu,"
           "\"callback_interval_hist_250us\":[",
           info.name, info.device, mode_names[st.mode], st.rate, st.period, info.actual_period,
           info.buffer_frames, elapsed, (unsigned long long)st.frames,
           (unsigned long long)atomic_load(&st.callbacks), (unsigned long long)atomic_load(&st.xruns),
           (unsigned long long)atomic_load(&st.late_callbacks), (double)atomic_load(&st.max_interval_ns) / 1e6,
           info.reported_latency_frames, lat_ms, info.latency_detail[0] ? info.latency_detail : "{}", info.sched,
           (unsigned long long)lc.written, (unsigned long long)atomic_load(&st.ring_dropped));
    for (int b = 0; b < SXLAT_HIST_BINS; b++)
        printf("%s%llu", b ? "," : "", (unsigned long long)atomic_load(&st.hist[b]));
    printf("]}\n");
    return 0;
}
