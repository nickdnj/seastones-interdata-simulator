/* audio.c: the audio device for rigd (VS-13; ADR-002), on miniaudio.
 *
 * Backends: CoreAudio on macOS (developer Macs), ALSA on Linux (the station: `hw:` direct, 48 kHz,
 * 128-frame periods, 2 periods, the device thread at SCHED_FIFO 70 when the unit grants
 * LimitRTPRIO), and miniaudio's null device for tests (paced in real time, no hardware).
 *
 * The callback (on_data) reads the host clock once, notes the thread's scheduling on its first
 * call, and hands the rest to sxh_rt_render (src/host/rt/, RT-lint checked). Nothing else here
 * runs on the audio thread except on_note, miniaudio's notification callback, which only sets a
 * flag. miniaudio converts nothing on the way: the engine renders f32 stereo at the device's own
 * rate, and the device is opened at that rate.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "rt.h"
#include "sxhost.h"

#include "ma_config.h"
/* after ma_config.h, so the ma_device layout matches miniaudio_impl.c */
#include "miniaudio.h"

#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__APPLE__)
#include <CoreAudio/CoreAudio.h>
#endif

static sxh_rt g_rt;
static ma_context g_ctx;
static ma_device g_dev;
static int g_open, g_started;
static _Atomic uint32_t g_lost, g_stopping;
static sxh_audio_info g_info;

/* capture writer */
static pthread_t g_writer;
static _Atomic uint32_t g_writer_stop;
static FILE *g_cap_fp;
static uint64_t g_cap_written;
static int g_writer_on;

static void on_data(ma_device *dev, void *out, const void *in, ma_uint32 frames)
{
    (void)in;
    sxh_rt *rt = dev->pUserData;
    uint64_t now = sxh_now_ns();
    if (!rt->first) {
        rt->first = 1;
        int policy = -1;
        struct sched_param sp = {0};
        if (pthread_getschedparam(pthread_self(), &policy, &sp) != 0)
            policy = -1;
        sxh_rt_note_sched(rt, policy, sp.sched_priority);
    }
    sxh_rt_render(rt, out, frames, now);
}

static void on_note(const ma_device_notification *n)
{
    if (n->type == ma_device_notification_type_stopped && !atomic_load(&g_stopping))
        atomic_store(&g_lost, 1u); /* nobody asked: unplugged or failed */
}

#if defined(__APPLE__)
static uint32_t ca_u32(AudioObjectID obj, AudioObjectPropertySelector sel,
                       AudioObjectPropertyScope scope)
{
    AudioObjectPropertyAddress a = {sel, scope, kAudioObjectPropertyElementMain};
    UInt32 v = 0, size = sizeof v;
    if (AudioObjectGetPropertyData(obj, &a, 0, NULL, &size, &v) != noErr)
        return 0;
    return v;
}
#endif

/* The output path's reported latency in frames: on CoreAudio the HAL's device latency, safety
 * offset, the first output stream's latency and the IO buffer (as the S-1a harness reports it);
 * elsewhere the buffer the device holds. Indicative only: S-1b measures the real one. */
static uint32_t backend_latency(const ma_device *dev, uint32_t period, uint32_t periods)
{
#if defined(__APPLE__)
    if (dev->pContext->backend == ma_backend_coreaudio) {
        AudioObjectID id = (AudioObjectID)dev->coreaudio.deviceObjectIDPlayback;
        const AudioObjectPropertyScope out = kAudioObjectPropertyScopeOutput;
        uint32_t total = ca_u32(id, kAudioDevicePropertyLatency, out) +
                         ca_u32(id, kAudioDevicePropertySafetyOffset, out) +
                         ca_u32(id, kAudioDevicePropertyBufferFrameSize, out);
        AudioObjectPropertyAddress sa = {kAudioDevicePropertyStreams, out,
                                         kAudioObjectPropertyElementMain};
        AudioStreamID streams[8];
        UInt32 size = sizeof streams;
        if (AudioObjectGetPropertyData(id, &sa, 0, NULL, &size, streams) == noErr &&
            size >= sizeof streams[0])
            total +=
                ca_u32(streams[0], kAudioStreamPropertyLatency, kAudioObjectPropertyScopeGlobal);
        return total;
    }
#endif
    return dev->pContext->backend == ma_backend_null ? 0u : period * (periods ? periods : 2u);
}

static int pick_device(ma_device_type type, const char *want, ma_device_id *id, char *name,
                       size_t name_n)
{
    ma_device_info *play = NULL, *cap = NULL;
    ma_uint32 nplay = 0, ncap = 0;
    if (ma_context_get_devices(&g_ctx, &play, &nplay, &cap, &ncap) != MA_SUCCESS)
        return 0;
    (void)type;
    for (ma_uint32 i = 0; i < nplay; i++) {
        const char *idtext = "";
#if defined(__linux__)
        idtext = play[i].id.alsa;
#elif defined(__APPLE__)
        idtext = play[i].id.coreaudio;
#endif
        if (strstr(play[i].name, want) || strstr(idtext, want)) {
            *id = play[i].id;
            snprintf(name, name_n, "%s", play[i].name);
            return 1;
        }
    }
    return 0;
}

int sxh_audio_open(const sxh_audio_cfg *cfg, sxh_audio_info *info)
{
    if (cfg == NULL || info == NULL || cfg->period == 0 || cfg->period > 8192)
        return SXH_E_ARG;
    if (g_open)
        return SXH_E_STATE;
    const char *backend = cfg->backend && cfg->backend[0] ? cfg->backend : "auto";
    ma_backend list[1];
    if (strcmp(backend, "null") == 0)
        list[0] = ma_backend_null;
    else if (strcmp(backend, "auto") == 0)
#if defined(__APPLE__)
        list[0] = ma_backend_coreaudio;
#else
        list[0] = ma_backend_alsa;
#endif
    else
        return SXH_E_ARG;

    ma_context_config cc = ma_context_config_init();
    cc.threadPriority = ma_thread_priority_realtime;
    if (ma_context_init(list, 1, &cc, &g_ctx) != MA_SUCCESS)
        return SXH_E_DEVICE;

    memset(&g_info, 0, sizeof g_info);
    ma_device_id id;
    int have_id = 0;
    if (cfg->device && cfg->device[0] && list[0] != ma_backend_null) {
        have_id = pick_device(ma_device_type_playback, cfg->device, &id, g_info.device,
                              sizeof g_info.device);
        if (!have_id) {
            ma_context_uninit(&g_ctx);
            return SXH_E_DEVICE;
        }
    }

    ma_device_config dc = ma_device_config_init(ma_device_type_playback);
    dc.playback.format = ma_format_f32;
    dc.playback.channels = 2;
    dc.playback.pDeviceID = have_id ? &id : NULL;
    dc.sampleRate = cfg->rate; /* 0: the device's own rate, so miniaudio does not resample */
    dc.periodSizeInFrames = cfg->period;
    dc.periods = cfg->periods ? cfg->periods : 2u;
    dc.performanceProfile = ma_performance_profile_low_latency;
    dc.noPreSilencedOutputBuffer = MA_TRUE; /* the callback writes every sample */
    dc.noClip = MA_TRUE;                    /* the engine's safety chain is the limiter */
    dc.noFixedSizedCallback = MA_TRUE;      /* no intermediate buffer, no added latency */
    dc.dataCallback = on_data;
    dc.notificationCallback = on_note;
    dc.pUserData = &g_rt;
    dc.alsa.noAutoResample = MA_TRUE;
    dc.coreaudio.allowNominalSampleRateChange = MA_FALSE; /* a shared Mac keeps its rate */

    if (ma_device_init(&g_ctx, &dc, &g_dev) != MA_SUCCESS) {
        ma_context_uninit(&g_ctx);
        return SXH_E_DEVICE;
    }

    uint32_t rate = g_dev.sampleRate;
    uint32_t period = g_dev.playback.internalPeriodSizeInFrames;
    uint32_t sub = cfg->sub_period ? cfg->sub_period : period;
    if (sub == 0 || sub > 4096)
        sub = 128;
    float *stereo = calloc((size_t)sub * 2u, sizeof *stereo);
    float *cap = calloc(SXH_CAPTURE_RING, sizeof *cap);
    if (stereo == NULL || cap == NULL) {
        free(stereo);
        free(cap);
        ma_device_uninit(&g_dev);
        ma_context_uninit(&g_ctx);
        return SXH_E_STATE;
    }

    /* every field of the real-time state, before the device can call back */
    free(g_rt.stereo);
    free(g_rt.cap);
    memset(&g_rt, 0, sizeof g_rt);
    g_rt.rate = rate;
    g_rt.sub = sub;
    g_rt.channels = g_dev.playback.channels;
    g_rt.period = period ? period : cfg->period;
    g_rt.silent = (cfg->flags & SXH_AUDIO_SILENT_DEVICE) != 0u;
    g_rt.count_late = list[0] != ma_backend_null;
    g_rt.stereo = stereo;
    g_rt.cap = cap;
    atomic_store(&g_rt.sched_policy, -1);
    atomic_store(&g_rt.cap_first, UINT64_MAX);

    snprintf(g_info.backend, sizeof g_info.backend, "%.31s", ma_get_backend_name(list[0]));
    if (!g_info.device[0]) /* names are cut to the field: they are for the log and staff screen */
        snprintf(g_info.device, sizeof g_info.device, "%.127s", g_dev.playback.name);
    g_info.rate = rate;
    g_info.period = g_rt.period;
    g_info.periods = g_dev.playback.internalPeriods;
    g_info.latency_frames = backend_latency(&g_dev, g_info.period, g_info.periods);
    *info = g_info;
    atomic_store(&g_lost, 0u);
    atomic_store(&g_stopping, 0u);
    g_open = 1;
    return SXH_OK;
}

int sxh_audio_start(sx_engine *e)
{
    if (!g_open || g_started || e == NULL)
        return SXH_E_STATE;
    /* the callback counts on from the engine's own frame count, so a reopened device keeps
     * the callback clock and the capture in engine frames (the engine is not rendering now) */
    static sx_snapshot snap;
    if (sx_snapshot_read(e, &snap) == SX_OK)
        g_rt.frames = snap.frames;
    atomic_store(&g_rt.pub_frames, g_rt.frames);
    g_rt.e = e;
    if (ma_device_start(&g_dev) != MA_SUCCESS)
        return SXH_E_DEVICE;
    g_started = 1;
    return SXH_OK;
}

void sxh_audio_close(void)
{
    if (!g_open)
        return;
    atomic_store(&g_stopping, 1u);
    sxh_capture_stop();
    ma_device_uninit(&g_dev); /* stops it first; no callback runs after this returns */
    ma_context_uninit(&g_ctx);
    g_rt.e = NULL;
    g_open = g_started = 0;
}

void sxh_audio_status_read(sxh_audio_status *s)
{
    if (s == NULL)
        return;
    memset(s, 0, sizeof *s);
    s->open = (uint32_t)g_open;
    s->running =
        (uint32_t)(g_started && !atomic_load(&g_lost) && ma_device_is_started(&g_dev) == MA_TRUE);
    s->lost = atomic_load(&g_lost);
    s->frames = atomic_load_explicit(&g_rt.pub_frames, memory_order_acquire);
    s->callbacks = atomic_load_explicit(&g_rt.callbacks, memory_order_relaxed);
    s->late_callbacks = atomic_load_explicit(&g_rt.late, memory_order_relaxed);
    s->max_interval_ns = atomic_load_explicit(&g_rt.max_interval_ns, memory_order_relaxed);
    s->last_callback_ns = atomic_load_explicit(&g_rt.last_callback_ns, memory_order_relaxed);
    s->sched_policy = atomic_load_explicit(&g_rt.sched_policy, memory_order_relaxed);
    s->sched_priority = atomic_load_explicit(&g_rt.sched_priority, memory_order_relaxed);
    s->capture_frames = g_cap_written;
    s->capture_dropped = atomic_load_explicit(&g_rt.cap_dropped, memory_order_relaxed);
    s->capture_first_frame = atomic_load_explicit(&g_rt.cap_first, memory_order_acquire);
    s->frozen = atomic_load_explicit(&g_rt.freeze, memory_order_relaxed);
}

/* --- capture ------------------------------------------------------------------------------ */

static void drain_capture(void)
{
    uint32_t tail = atomic_load_explicit(&g_rt.c_tail, memory_order_relaxed);
    uint32_t head = atomic_load_explicit(&g_rt.c_head, memory_order_acquire);
    while (tail != head) {
        uint32_t at = tail % SXH_CAPTURE_RING;
        uint32_t n = head - tail;
        if (n > SXH_CAPTURE_RING - at)
            n = SXH_CAPTURE_RING - at;
        size_t w = fwrite(g_rt.cap + at, sizeof(float), n, g_cap_fp);
        g_cap_written += w;
        tail += n;
        atomic_store_explicit(&g_rt.c_tail, tail, memory_order_release);
    }
    fflush(g_cap_fp);
}

static void *writer(void *arg)
{
    (void)arg;
    struct timespec ts = {0, 5000000}; /* 5 ms */
    while (!atomic_load(&g_writer_stop)) {
        drain_capture();
        nanosleep(&ts, NULL);
    }
    drain_capture();
    return NULL;
}

int sxh_capture_start(const char *path)
{
    if (path == NULL || !g_open || g_writer_on)
        return SXH_E_STATE;
    g_cap_fp = fopen(path, "ab"); /* a reopened device appends; rigd logs each segment */
    if (g_cap_fp == NULL)
        return SXH_E_ARG;
    g_cap_written = 0;
    atomic_store(&g_rt.c_head, 0u);
    atomic_store(&g_rt.c_tail, 0u);
    atomic_store(&g_writer_stop, 0u);
    if (pthread_create(&g_writer, NULL, writer, NULL) != 0) {
        fclose(g_cap_fp);
        g_cap_fp = NULL;
        return SXH_E_STATE;
    }
    g_writer_on = 1;
    atomic_store_explicit(&g_rt.cap_first, UINT64_MAX, memory_order_relaxed);
    atomic_store_explicit(&g_rt.capturing, 1u, memory_order_release);
    return SXH_OK;
}

void sxh_capture_stop(void)
{
    if (!g_writer_on)
        return;
    atomic_store_explicit(&g_rt.capturing, 0u, memory_order_release);
    atomic_store(&g_writer_stop, 1u);
    pthread_join(g_writer, NULL);
    fclose(g_cap_fp);
    g_cap_fp = NULL;
    g_writer_on = 0;
}

/* --- the taps' readers -------------------------------------------------------------------- */

uint32_t sxh_samples_read(sxh_sample *out, uint32_t max)
{
    if (out == NULL)
        return 0;
    uint32_t tail = atomic_load_explicit(&g_rt.s_tail, memory_order_relaxed);
    uint32_t head = atomic_load_explicit(&g_rt.s_head, memory_order_acquire);
    uint32_t n = 0;
    while (tail != head && n < max)
        out[n++] = g_rt.samples[tail++ % SXH_SAMPLE_RING];
    atomic_store_explicit(&g_rt.s_tail, tail, memory_order_release);
    return n;
}

uint64_t sxh_frame_host_ns(uint64_t frame)
{
    uint64_t n = atomic_load_explicit(&g_rt.clock_n, memory_order_acquire);
    uint32_t rate = g_rt.rate ? g_rt.rate : 48000u;
    /* newest first; leave a margin so the writer cannot lap an entry while we read it */
    for (uint64_t k = 0; k + 8u < SXH_CLOCK_RING && k < n; k++) {
        const sxh_clock_ent *c = &g_rt.clock[(n - 1u - k) % SXH_CLOCK_RING];
        uint64_t f1 = atomic_load_explicit(&c->frame0, memory_order_acquire);
        uint64_t t = atomic_load_explicit(&c->host_ns, memory_order_relaxed);
        atomic_thread_fence(memory_order_acquire);
        uint64_t f2 = atomic_load_explicit(&c->frame0, memory_order_relaxed);
        if (f1 != f2 || f1 == UINT64_MAX)
            continue;
        if (f1 <= frame)
            return t + (frame - f1) * 1000000000u / rate;
    }
    return 0;
}

/* --- profile and test hooks ---------------------------------------------------------------- */

uint32_t sxh_api_version(void)
{
    return SXH_API_VERSION;
}

const char *sxh_profile(void)
{
    return sx_profile(); /* built with the engine's profile flags, in one library */
}

#if defined(SX_TEST_HOOKS)
void sxh_test_freeze(uint32_t on)
{
    atomic_store_explicit(&g_rt.freeze, on ? 1u : 0u, memory_order_release);
}

void sxh_test_late(uint32_t n)
{
    atomic_fetch_add_explicit(&g_rt.late, n, memory_order_relaxed);
}

void sxh_test_unplug(void)
{
    if (g_started)
        ma_device_stop(&g_dev); /* nobody asked: on_note marks the device lost, as an unplug */
}
#endif
