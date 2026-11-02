/*
 * sxmidi ALSA sequencer backend (Linux, the station).
 *
 * The listener client subscribes to System:Announce (0:1) for PORT_START / PORT_EXIT and to
 * every readable hardware or virtual port, with real-time queue timestamps on the
 * subscription (the kernel stamps the event when the sequencer delivers it). It also records
 * CLOCK_MONOTONIC_RAW at the moment the reader thread receives the event; QA's Method B uses
 * that host time (QA-STRATEGY 4.3).
 *
 * selftest: a second client in this process acts as a virtual keyboard. Delete its port to
 * simulate an unplug; the listener times the PORT_EXIT announce. A real `snd-virmidi` card can
 * be exercised the same way in CI with `listen` plus `aseqsend`/`amidi`.
 */
#define _GNU_SOURCE
#include "sxmidi.h"

#include <alsa/asoundlib.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static uint64_t g_send[SXMIDI_MAX_EVENTS], g_arrive[SXMIDI_MAX_EVENTS], g_ts[SXMIDI_MAX_EVENTS];
static atomic_uint g_next_expected, g_out_of_order;
static _Atomic uint64_t g_exit_ns;
static atomic_int g_run;
static snd_seq_t *g_in;
static int g_in_port, g_queue;
static snd_seq_addr_t g_src_addr;
static uint64_t g_queue_start_ns;

static uint64_t ev_time_ns(const snd_seq_event_t *ev) {
    if (!(ev->flags & SND_SEQ_TIME_STAMP_REAL)) return 0;
    return g_queue_start_ns + (uint64_t)ev->time.time.tv_sec * 1000000000ull + (uint64_t)ev->time.time.tv_nsec;
}

static int open_listener(void) {
    if (snd_seq_open(&g_in, "default", SND_SEQ_OPEN_DUPLEX, 0) < 0) return -1;
    snd_seq_set_client_name(g_in, "sxmidi");
    g_in_port = snd_seq_create_simple_port(g_in, "in", SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
                                           SND_SEQ_PORT_TYPE_APPLICATION);
    if (g_in_port < 0) return -1;
    g_queue = snd_seq_alloc_queue(g_in);
    snd_seq_start_queue(g_in, g_queue, NULL);
    snd_seq_drain_output(g_in);
    g_queue_start_ns = sxmidi_now_ns();
    /* announce port: PORT_START / PORT_EXIT / CLIENT_EXIT */
    snd_seq_connect_from(g_in, g_in_port, SND_SEQ_CLIENT_SYSTEM, SND_SEQ_PORT_SYSTEM_ANNOUNCE);
    return 0;
}

static int subscribe_from(snd_seq_addr_t sender) {
    snd_seq_port_subscribe_t *sub;
    snd_seq_port_subscribe_alloca(&sub);
    snd_seq_addr_t dest = {.client = (unsigned char)snd_seq_client_id(g_in), .port = (unsigned char)g_in_port};
    snd_seq_port_subscribe_set_sender(sub, &sender);
    snd_seq_port_subscribe_set_dest(sub, &dest);
    snd_seq_port_subscribe_set_queue(sub, g_queue);
    snd_seq_port_subscribe_set_time_update(sub, 1);
    snd_seq_port_subscribe_set_time_real(sub, 1);
    return snd_seq_subscribe_port(g_in, sub);
}

static void *reader(void *arg) {
    (void)arg;
    int npfd = snd_seq_poll_descriptors_count(g_in, POLLIN);
    struct pollfd pfd[8];
    if (npfd > 8) npfd = 8;
    snd_seq_poll_descriptors(g_in, pfd, (unsigned)npfd, POLLIN);
    while (atomic_load(&g_run)) {
        if (poll(pfd, (nfds_t)npfd, 50) <= 0) continue;
        snd_seq_event_t *ev;
        while (snd_seq_event_input(g_in, &ev) >= 0 && ev) {
            uint64_t now = sxmidi_now_ns();
            if (ev->type == SND_SEQ_EVENT_NOTEON && ev->data.note.velocity) {
                unsigned idx = ev->data.note.note * 127u + (ev->data.note.velocity - 1u);
                unsigned exp = atomic_fetch_add(&g_next_expected, 1);
                if (idx != exp) atomic_fetch_add(&g_out_of_order, 1);
                if (idx < SXMIDI_MAX_EVENTS) {
                    g_arrive[idx] = now;
                    g_ts[idx] = ev_time_ns(ev);
                }
            } else if (ev->type == SND_SEQ_EVENT_PORT_EXIT && ev->data.addr.client == g_src_addr.client &&
                       ev->data.addr.port == g_src_addr.port) {
                atomic_store(&g_exit_ns, now);
            }
            if (snd_seq_event_input_pending(g_in, 0) <= 0) break;
        }
    }
    return NULL;
}

int sxmidi_selftest(unsigned n, double spacing_ms, unsigned seed, sxmidi_selftest_result *r) {
    r->backend = "alsa-seq";
    if (open_listener() != 0) return -1;
    snd_seq_t *src;
    if (snd_seq_open(&src, "default", SND_SEQ_OPEN_OUTPUT, 0) < 0) return -1;
    snd_seq_set_client_name(src, "sxmidi-virtual-keyboard");
    int sp = snd_seq_create_simple_port(src, "out", SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ,
                                        SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION);
    if (sp < 0) return -1;
    g_src_addr.client = (unsigned char)snd_seq_client_id(src);
    g_src_addr.port = (unsigned char)sp;
    if (subscribe_from(g_src_addr) < 0) return -1;

    atomic_store(&g_run, 1);
    pthread_t th;
    pthread_create(&th, NULL, reader, NULL);
    sxmidi_sleep_ns(100000000ull);

    srand(seed);
    for (unsigned i = 0; i < n; i++) {
        snd_seq_event_t ev;
        snd_seq_ev_clear(&ev);
        snd_seq_ev_set_source(&ev, (unsigned char)sp);
        snd_seq_ev_set_subs(&ev);
        snd_seq_ev_set_direct(&ev);
        snd_seq_ev_set_noteon(&ev, 0, (unsigned char)(i / 127u), (unsigned char)(i % 127u + 1u));
        g_send[i] = sxmidi_now_ns();
        snd_seq_event_output_direct(src, &ev);
        double jitter = spacing_ms * 0.5 * ((double)rand() / RAND_MAX);
        sxmidi_sleep_ns((uint64_t)((spacing_ms + jitter) * 1e6));
    }
    sxmidi_sleep_ns(200000000ull);
    r->out_of_order = atomic_load(&g_out_of_order);
    sxmidi_stats(g_send, g_arrive, g_ts, n, r);

    uint64_t t_unplug = sxmidi_now_ns();
    snd_seq_delete_simple_port(src, sp);
    while (!atomic_load(&g_exit_ns) && sxmidi_now_ns() - t_unplug < 2000000000ull) sxmidi_sleep_ns(100000ull);
    uint64_t ex = atomic_load(&g_exit_ns);
    r->unplug_seen = ex != 0;
    r->unplug_ms = ex ? (double)(ex - t_unplug) / 1e6 : -1.0;
    atomic_store(&g_run, 0);
    pthread_join(th, NULL);
    snd_seq_close(src);
    snd_seq_close(g_in);
    return 0;
}

/* ------------------------------------------------------------------ listen */

static volatile sig_atomic_t g_stop;
static void on_sig(int s) { (void)s; g_stop = 1; }

static void subscribe_all(void) {
    snd_seq_client_info_t *ci;
    snd_seq_port_info_t *pi;
    snd_seq_client_info_alloca(&ci);
    snd_seq_port_info_alloca(&pi);
    snd_seq_client_info_set_client(ci, -1);
    while (snd_seq_query_next_client(g_in, ci) >= 0) {
        int c = snd_seq_client_info_get_client(ci);
        if (c == SND_SEQ_CLIENT_SYSTEM || c == snd_seq_client_id(g_in)) continue;
        snd_seq_port_info_set_client(pi, c);
        snd_seq_port_info_set_port(pi, -1);
        while (snd_seq_query_next_port(g_in, pi) >= 0) {
            unsigned caps = snd_seq_port_info_get_capability(pi);
            if ((caps & (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ)) ==
                (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ)) {
                snd_seq_addr_t a = *snd_seq_port_info_get_addr(pi);
                if (subscribe_from(a) >= 0)
                    printf("{\"type\":\"source_added\",\"host_ns\":%llu,\"client\":%u,\"port\":%u,\"name\":\"%s\"}\n",
                           (unsigned long long)sxmidi_now_ns(), a.client, a.port, snd_seq_port_info_get_name(pi));
            }
        }
    }
}

int sxmidi_listen(double seconds, const char *sync_path, double sync_every_ms) {
    signal(SIGINT, on_sig);
    signal(SIGTERM, on_sig);
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (open_listener() != 0) {
        fprintf(stderr, "sxmidi: cannot open the ALSA sequencer\n");
        return 1;
    }
    subscribe_all();
    int fd = -1;
    if (sync_path && (fd = open(sync_path, O_WRONLY | O_NOCTTY)) < 0) {
        fprintf(stderr, "sxmidi: cannot open %s\n", sync_path);
        return 1;
    }
    int npfd = snd_seq_poll_descriptors_count(g_in, POLLIN);
    struct pollfd pfd[8];
    if (npfd > 8) npfd = 8;
    snd_seq_poll_descriptors(g_in, pfd, (unsigned)npfd, POLLIN);
    uint64_t t0 = sxmidi_now_ns(), next_sync = t0;
    while (!g_stop && (double)(sxmidi_now_ns() - t0) / 1e9 < seconds) {
        if (fd >= 0 && sxmidi_now_ns() >= next_sync) {
            unsigned char b = 'S';
            if (write(fd, &b, 1) == 1)
                printf("{\"type\":\"sync\",\"host_ns\":%llu}\n", (unsigned long long)sxmidi_now_ns());
            next_sync += (uint64_t)(sync_every_ms * 1e6);
        }
        if (poll(pfd, (nfds_t)npfd, 2) <= 0) continue;
        snd_seq_event_t *ev;
        while (snd_seq_event_input(g_in, &ev) >= 0 && ev) {
            uint64_t now = sxmidi_now_ns();
            switch (ev->type) {
            case SND_SEQ_EVENT_NOTEON:
            case SND_SEQ_EVENT_NOTEOFF:
                printf("{\"type\":\"%s\",\"note\":%u,\"velocity\":%u,\"host_ns\":%llu,\"driver_ns\":%llu,"
                       "\"client\":%u,\"port\":%u}\n",
                       (ev->type == SND_SEQ_EVENT_NOTEON && ev->data.note.velocity) ? "note_on" : "note_off",
                       ev->data.note.note, ev->data.note.velocity, (unsigned long long)now,
                       (unsigned long long)ev_time_ns(ev), ev->source.client, ev->source.port);
                break;
            case SND_SEQ_EVENT_PORT_START: {
                snd_seq_addr_t a = ev->data.addr;
                subscribe_from(a);
                printf("{\"type\":\"source_added\",\"host_ns\":%llu,\"client\":%u,\"port\":%u}\n",
                       (unsigned long long)now, a.client, a.port);
                break;
            }
            case SND_SEQ_EVENT_PORT_EXIT:
                printf("{\"type\":\"source_removed\",\"host_ns\":%llu,\"client\":%u,\"port\":%u}\n",
                       (unsigned long long)now, ev->data.addr.client, ev->data.addr.port);
                break;
            default:
                break;
            }
            if (snd_seq_event_input_pending(g_in, 0) <= 0) break;
        }
    }
    if (fd >= 0) close(fd);
    snd_seq_close(g_in);
    return 0;
}
