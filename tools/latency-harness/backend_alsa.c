/*
 * sxlat ALSA backend (Linux, the station): `hw:` direct, no sound server,
 * interleaved float or S32 (whatever the interface accepts), 2 periods of the
 * requested size, own write thread at SCHED_FIFO 80 where permitted.
 *
 * Output latency reported = median snd_pcm_delay() sampled after each write
 * in steady state (ring occupancy, frames). The USB interface's converter
 * and filter delay are not visible to ALSA: S-1b measures them on the rig.
 * Xruns: -EPIPE from snd_pcm_writei (recovered with snd_pcm_prepare).
 */
#define _GNU_SOURCE
#include "sxlat.h"

#include <alsa/asoundlib.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DELAY_SAMPLES 4096

static snd_pcm_t *g_pcm;
static pthread_t g_thread;
static atomic_int g_run;
static snd_pcm_format_t g_fmt;
static float *g_fbuf;
static int32_t *g_ibuf;
static snd_pcm_sframes_t g_delays[DELAY_SAMPLES];
static unsigned g_ndelays;
static char g_sched[64];

static int cmp_sf(const void *a, const void *b) {
    snd_pcm_sframes_t x = *(const snd_pcm_sframes_t *)a, y = *(const snd_pcm_sframes_t *)b;
    return (x > y) - (x < y);
}

static void *writer(void *arg) {
    sxlat_state *st = arg;
    struct sched_param sp = {.sched_priority = 80};
    int rc = pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp);
    snprintf(g_sched, sizeof g_sched, rc == 0 ? "SCHED_FIFO 80" : "SCHED_OTHER (SCHED_FIFO refused: %s)",
             rc == 0 ? "" : strerror(rc));

    const uint32_t n = st->period;
    uint64_t writes = 0;
    while (atomic_load(&g_run)) {
        sxlat_render(st, g_fbuf, n, sxlat_now_ns());
        const void *buf = g_fbuf;
        if (g_fmt == SND_PCM_FORMAT_S32_LE) {
            for (uint32_t i = 0; i < n * st->channels; i++) {
                float s = g_fbuf[i];
                if (s > 1.0f) s = 1.0f;
                if (s < -1.0f) s = -1.0f;
                g_ibuf[i] = (int32_t)(s * 2147483520.0f);
            }
            buf = g_ibuf;
        }
        snd_pcm_sframes_t w = snd_pcm_writei(g_pcm, buf, n);
        if (w == -EPIPE) {
            atomic_fetch_add(&st->xruns, 1);
            snd_pcm_prepare(g_pcm);
            continue;
        } else if (w < 0) {
            if (snd_pcm_recover(g_pcm, (int)w, 1) < 0) break;
            continue;
        }
        writes++;
        snd_pcm_sframes_t delay = 0;
        if (writes > 16 && g_ndelays < DELAY_SAMPLES && snd_pcm_delay(g_pcm, &delay) == 0) {
            g_delays[g_ndelays++] = delay;
            if (g_ndelays % 64 == 0) atomic_store(&st->latency_frames, (uint32_t)delay);
        }
    }
    return NULL;
}

int sxlat_backend_open(sxlat_state *st, const char *device, sxlat_backend_info *info) {
    snprintf(info->name, sizeof info->name, "alsa");
    const char *dev = device ? device : "hw:0,0";
    snprintf(info->device, sizeof info->device, "%s", dev);
    int rc = snd_pcm_open(&g_pcm, dev, SND_PCM_STREAM_PLAYBACK, 0);
    if (rc < 0) {
        fprintf(stderr, "sxlat: snd_pcm_open(%s): %s\n", dev, snd_strerror(rc));
        return -1;
    }
    snd_pcm_hw_params_t *hw;
    snd_pcm_hw_params_alloca(&hw);
    snd_pcm_hw_params_any(g_pcm, hw);
    snd_pcm_hw_params_set_access(g_pcm, hw, SND_PCM_ACCESS_RW_INTERLEAVED);
    g_fmt = SND_PCM_FORMAT_FLOAT_LE;
    if (snd_pcm_hw_params_set_format(g_pcm, hw, g_fmt) < 0) {
        g_fmt = SND_PCM_FORMAT_S32_LE;
        if (snd_pcm_hw_params_set_format(g_pcm, hw, g_fmt) < 0) {
            fprintf(stderr, "sxlat: device takes neither FLOAT_LE nor S32_LE\n");
            return -1;
        }
    }
    unsigned ch = st->channels;
    snd_pcm_hw_params_set_channels_near(g_pcm, hw, &ch);
    st->channels = ch;
    unsigned rate = st->rate;
    snd_pcm_hw_params_set_rate_near(g_pcm, hw, &rate, NULL);
    snd_pcm_uframes_t period = st->period;
    snd_pcm_hw_params_set_period_size_near(g_pcm, hw, &period, NULL);
    unsigned periods = 2;
    snd_pcm_hw_params_set_periods_near(g_pcm, hw, &periods, NULL);
    if ((rc = snd_pcm_hw_params(g_pcm, hw)) < 0) {
        fprintf(stderr, "sxlat: hw_params: %s\n", snd_strerror(rc));
        return -1;
    }
    snd_pcm_uframes_t bufsize = 0;
    snd_pcm_hw_params_get_buffer_size(hw, &bufsize);

    snd_pcm_sw_params_t *sw;
    snd_pcm_sw_params_alloca(&sw);
    snd_pcm_sw_params_current(g_pcm, sw);
    snd_pcm_sw_params_set_start_threshold(g_pcm, sw, period);
    /* stop on underrun (the fail-silent behaviour S-6 relies on) */
    snd_pcm_sw_params_set_stop_threshold(g_pcm, sw, bufsize);
    snd_pcm_sw_params(g_pcm, sw);

    st->rate = rate;
    st->period = (uint32_t)period;
    info->actual_rate = rate;
    info->actual_period = (uint32_t)period;
    info->buffer_frames = (uint32_t)bufsize;
    g_fbuf = calloc((size_t)period * ch, sizeof(float));
    g_ibuf = calloc((size_t)period * ch, sizeof(int32_t));
    return (g_fbuf && g_ibuf) ? 0 : -1;
}

int sxlat_backend_start(sxlat_state *st) {
    atomic_store(&g_run, 1);
    return pthread_create(&g_thread, NULL, writer, st) == 0 ? 0 : -1;
}

void sxlat_backend_stop(sxlat_state *st, sxlat_backend_info *info) {
    atomic_store(&g_run, 0);
    pthread_join(g_thread, NULL);
    snd_pcm_drop(g_pcm);
    snd_pcm_close(g_pcm);
    snd_pcm_sframes_t med = 0, p95 = 0, mx = 0;
    if (g_ndelays) {
        qsort(g_delays, g_ndelays, sizeof g_delays[0], cmp_sf);
        med = g_delays[g_ndelays / 2];
        p95 = g_delays[(g_ndelays * 95) / 100];
        mx = g_delays[g_ndelays - 1];
    }
    info->reported_latency_frames = (uint32_t)med;
    snprintf(info->sched, sizeof info->sched, "%s", g_sched);
    snprintf(info->latency_detail, sizeof info->latency_detail,
             "{\"snd_pcm_delay_median\":%ld,\"snd_pcm_delay_p95\":%ld,\"snd_pcm_delay_max\":%ld,\"samples\":%u,"
             "\"format\":\"%s\",\"note\":\"ring occupancy only; interface converter delay measured in S-1b\"}",
             (long)med, (long)p95, (long)mx, g_ndelays, snd_pcm_format_name(g_fmt));
    (void)st;
    free(g_fbuf);
    free(g_ibuf);
}
