/* midi_alsa.c: the ALSA sequencer backend (the station, Linux) (VS-13, VS-18; ADR-002).
 *
 * One thread: a sequencer client "seastones-rigd" with one writable port, subscribed to the
 * system announce port, so a keyboard's PORT_START and PORT_EXIT arrive as events on the same
 * queue as its notes (ARCHITECTURE 8.1: the unplug is seen at once, the bitmap cleared at once).
 * Every readable port that is not a system port or our own is connected and given a slot. The
 * thread polls the sequencer and a wake pipe, so stop() ends it within one poll.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "midi_int.h"

#include <alsa/asoundlib.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <unistd.h>

static pthread_t thr;
static snd_seq_t *seq;
static int my_client, my_port;
static int wake[2] = {-1, -1};
static _Atomic uint32_t stopping;

static uint64_t addr_key(int client, int port)
{
    return ((uint64_t)(uint32_t)client << 8) | (uint64_t)(uint32_t)port;
}

static void try_connect(int client, int port)
{
    if (client == my_client || client == SND_SEQ_CLIENT_SYSTEM)
        return;
    snd_seq_port_info_t *pi;
    snd_seq_port_info_alloca(&pi);
    if (snd_seq_get_any_port_info(seq, client, port, pi) < 0)
        return;
    unsigned caps = snd_seq_port_info_get_capability(pi);
    unsigned type = snd_seq_port_info_get_type(pi);
    if ((caps & (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ)) !=
            (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ) ||
        (caps & SND_SEQ_PORT_CAP_NO_EXPORT) || !(type & SND_SEQ_PORT_TYPE_MIDI_GENERIC) ||
        !sxh_midi_name_ok(snd_seq_port_info_get_name(pi)))
        return;
    int slot = sxh_midi_slot_open(addr_key(client, port));
    if (slot >= 0 && snd_seq_connect_from(seq, my_port, client, port) < 0)
        sxh_midi_slot_close(slot);
}

static void connect_all(void)
{
    snd_seq_client_info_t *ci;
    snd_seq_port_info_t *pi;
    snd_seq_client_info_alloca(&ci);
    snd_seq_port_info_alloca(&pi);
    snd_seq_client_info_set_client(ci, -1);
    while (snd_seq_query_next_client(seq, ci) >= 0) {
        int c = snd_seq_client_info_get_client(ci);
        snd_seq_port_info_set_client(pi, c);
        snd_seq_port_info_set_port(pi, -1);
        while (snd_seq_query_next_port(seq, pi) >= 0)
            try_connect(c, snd_seq_port_info_get_port(pi));
    }
}

static void close_client(int client)
{
    for (int p = 0; p < 256; p++) {
        int slot = sxh_midi_slot_find(addr_key(client, p));
        if (slot >= 0)
            sxh_midi_slot_close(slot);
    }
}

static void handle(const snd_seq_event_t *ev, uint64_t now)
{
    int slot;
    switch (ev->type) {
    case SND_SEQ_EVENT_PORT_START:
        try_connect(ev->data.addr.client, ev->data.addr.port);
        return;
    case SND_SEQ_EVENT_PORT_EXIT:
        sxh_midi_slot_close(sxh_midi_slot_find(addr_key(ev->data.addr.client, ev->data.addr.port)));
        return;
    case SND_SEQ_EVENT_CLIENT_EXIT:
        close_client(ev->data.addr.client);
        return;
    case SND_SEQ_EVENT_NOTEON:
    case SND_SEQ_EVENT_NOTEOFF:
    case SND_SEQ_EVENT_CONTROLLER:
        slot = sxh_midi_slot_find(addr_key(ev->source.client, ev->source.port));
        if (slot < 0)
            return;
        if (ev->type == SND_SEQ_EVENT_CONTROLLER)
            sxh_midi_message(slot, (uint8_t)(0xB0u | (ev->data.control.channel & 0xFu)),
                             (uint8_t)(ev->data.control.param & 0x7Fu),
                             (uint8_t)(ev->data.control.value & 0x7F), now);
        else
            sxh_midi_message(slot,
                             (uint8_t)((ev->type == SND_SEQ_EVENT_NOTEON ? 0x90u : 0x80u) |
                                       (ev->data.note.channel & 0xFu)),
                             (uint8_t)(ev->data.note.note & 0x7Fu),
                             (uint8_t)(ev->data.note.velocity & 0x7Fu), now);
        return;
    default:
        sxh_midi_ignored();
        return;
    }
}

static void *run(void *arg)
{
    (void)arg;
    int nfd = snd_seq_poll_descriptors_count(seq, POLLIN);
    struct pollfd fds[9];
    if (nfd > 8)
        nfd = 8;
    snd_seq_poll_descriptors(seq, fds, (unsigned)nfd, POLLIN);
    fds[nfd].fd = wake[0];
    fds[nfd].events = POLLIN;
    while (!atomic_load(&stopping)) {
        if (poll(fds, (nfds_t)nfd + 1u, 250) <= 0)
            continue;
        snd_seq_event_t *ev = NULL;
        while (snd_seq_event_input(seq, &ev) >= 0 && ev) {
            handle(ev, sxh_now_ns());
            if (snd_seq_event_input_pending(seq, 0) == 0)
                break;
        }
    }
    return NULL;
}

int sxh_midi_backend_start(void)
{
    if (snd_seq_open(&seq, "default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK) < 0)
        return SXH_E_DEVICE;
    snd_seq_set_client_name(seq, "seastones-rigd");
    my_client = snd_seq_client_id(seq);
    my_port = snd_seq_create_simple_port(
        seq, "seastones-keys", SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
        SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION);
    if (my_port < 0 || pipe(wake) != 0) {
        snd_seq_close(seq);
        return SXH_E_DEVICE;
    }
    /* the announce port: PORT_START and PORT_EXIT for every client (hot-plug, INPUT-3) */
    snd_seq_connect_from(seq, my_port, SND_SEQ_CLIENT_SYSTEM, SND_SEQ_PORT_SYSTEM_ANNOUNCE);
    connect_all();
    atomic_store(&stopping, 0u);
    if (pthread_create(&thr, NULL, run, NULL) != 0) {
        close(wake[0]);
        close(wake[1]);
        snd_seq_close(seq);
        return SXH_E_STATE;
    }
    return SXH_OK;
}

void sxh_midi_backend_stop(void)
{
    atomic_store(&stopping, 1u);
    char b = 1;
    if (write(wake[1], &b, 1) < 0) {
        /* the poll times out within 250 ms anyway */
    }
    pthread_join(thr, NULL);
    close(wake[0]);
    close(wake[1]);
    snd_seq_close(seq);
    seq = NULL;
}
