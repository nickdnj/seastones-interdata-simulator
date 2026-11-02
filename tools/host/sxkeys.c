/* sxkeys: a virtual MIDI keyboard for rigd's tests and the latency run (VS-13, VS-18, LAT-02).
 *
 * A developer tool, not shipped. It creates a MIDI source that rigd sees exactly as it sees a
 * USB keyboard (a CoreMIDI virtual source on the Mac, an ALSA sequencer port on Linux), reads
 * commands from stdin, one per line, and prints one JSON line per event it sends, stamped with
 * the host clock rigd uses (src/host/clock.c):
 *
 *   plug [name]        create the source (a keyboard plugged in)
 *   unplug             remove it (pulled out, with any notes still held)
 *   on NOTE [VEL]      note-on (velocity 100 by default)
 *   off NOTE           note-off
 *   cc NUM VAL         control change (123 = all notes off)
 *   raw B1 [B2 [B3]]   any 1 to 3 byte MIDI message (hostility tests, FLT-09)
 *   sleep MS
 *   presses N NOTE HOLD_MS GAP_MIN_MS GAP_MAX_MS SEED
 *                      N presses of NOTE, each held HOLD_MS, gaps uniform in [min, max] from a
 *                      seeded generator (printed), for the latency run
 *   quit
 *
 * Output: {"t":"sent","kind":"on","note":60,"host_ns":...} and {"t":"plug"|"unplug",...}.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "sxhost.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void sleep_ms(double ms)
{
    if (ms <= 0)
        return;
    struct timespec ts = {(time_t)(ms / 1000.0),
                          (long)((ms - 1000.0 * (double)(time_t)(ms / 1000.0)) * 1e6)};
    nanosleep(&ts, NULL);
}

static uint64_t rng;
static double uniform(void) /* xorshift64*, seeded: the gaps are reproducible */
{
    rng ^= rng >> 12;
    rng ^= rng << 25;
    rng ^= rng >> 27;
    return (double)((rng * 2685821657736338717ull) >> 11) / 9007199254740992.0;
}

#if defined(__APPLE__)
#include <CoreMIDI/CoreMIDI.h>
#include <mach/mach_time.h>

static MIDIClientRef client;
static MIDIEndpointRef src;

static int backend_init(void)
{
    return MIDIClientCreate(CFSTR("sxkeys"), NULL, NULL, &client) == noErr ? 0 : -1;
}

static int backend_plug(const char *name)
{
    if (src)
        return 0;
    CFStringRef n = CFStringCreateWithCString(NULL, name, kCFStringEncodingUTF8);
    OSStatus st = MIDISourceCreateWithProtocol(client, n, kMIDIProtocol_1_0, &src);
    CFRelease(n);
    return st == noErr ? 0 : -1;
}

static int backend_unplug(void)
{
    if (!src)
        return 0;
    MIDIEndpointDispose(src);
    src = 0;
    return 0;
}

static int backend_send(const uint8_t *b, int n)
{
    if (!src)
        return -1;
    uint32_t word = (0x2u << 28) | ((uint32_t)b[0] << 16) | ((n > 1 ? (uint32_t)b[1] : 0u) << 8) |
                    (n > 2 ? (uint32_t)b[2] : 0u);
    if (b[0] >= 0xF0u) /* system messages are UMP type 1 */
        word = (0x1u << 28) | (word & 0x00FFFFFFu);
    MIDIEventList list;
    MIDIEventPacket *p = MIDIEventListInit(&list, kMIDIProtocol_1_0);
    p = MIDIEventListAdd(&list, sizeof list, p, mach_absolute_time(), 1, &word);
    return p && MIDIReceivedEventList(src, &list) == noErr ? 0 : -1;
}

static void backend_close(void)
{
    backend_unplug();
    MIDIClientDispose(client);
}
#else
#include <alsa/asoundlib.h>

static snd_seq_t *seq;
static int port = -1;

static int backend_init(void)
{
    if (snd_seq_open(&seq, "default", SND_SEQ_OPEN_OUTPUT, 0) < 0)
        return -1;
    snd_seq_set_client_name(seq, "sxkeys");
    return 0;
}

static int backend_plug(const char *name)
{
    if (port >= 0)
        return 0;
    port = snd_seq_create_simple_port(seq, name, SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ,
                                      SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_HARDWARE);
    return port >= 0 ? 0 : -1;
}

static int backend_unplug(void)
{
    if (port < 0)
        return 0;
    snd_seq_delete_simple_port(seq, port);
    port = -1;
    return 0;
}

static int backend_send(const uint8_t *b, int n)
{
    if (port < 0)
        return -1;
    snd_seq_event_t ev;
    snd_seq_ev_clear(&ev);
    snd_seq_ev_set_source(&ev, port);
    snd_seq_ev_set_subs(&ev);
    snd_seq_ev_set_direct(&ev);
    uint8_t kind = b[0] & 0xF0u, ch = b[0] & 0x0Fu;
    if (kind == 0x90u && n > 2)
        snd_seq_ev_set_noteon(&ev, ch, b[1], b[2]);
    else if (kind == 0x80u && n > 2)
        snd_seq_ev_set_noteoff(&ev, ch, b[1], b[2]);
    else if (kind == 0xB0u && n > 2)
        snd_seq_ev_set_controller(&ev, ch, b[1], b[2]);
    else
        return 0; /* other raw bytes: the ALSA path does not carry them in this tool */
    return snd_seq_event_output_direct(seq, &ev) >= 0 ? 0 : -1;
}

static void backend_close(void)
{
    backend_unplug();
    snd_seq_close(seq);
}
#endif

static void sent(const char *kind, int note, uint64_t t)
{
    printf("{\"t\":\"sent\",\"kind\":\"%s\",\"note\":%d,\"host_ns\":%" PRIu64 "}\n", kind, note, t);
}

static int send3(uint8_t a, uint8_t b, uint8_t c, const char *kind, int note)
{
    uint8_t m[3] = {a, b, c};
    uint64_t t = sxh_now_ns();
    int rc = backend_send(m, 3);
    if (rc == 0 && kind)
        sent(kind, note, t);
    return rc;
}

int main(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (backend_init() != 0) {
        fprintf(stderr, "sxkeys: no MIDI system\n");
        return 1;
    }
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        char cmd[32] = "", name[128] = "sxkeys-virtual-keyboard";
        int a = 0, b = 0, c = 0;
        if (sscanf(line, "%31s", cmd) != 1)
            continue;
        int rc = 0;
        if (strcmp(cmd, "plug") == 0) {
            sscanf(line, "%*s %127s", name);
            rc = backend_plug(name);
            printf("{\"t\":\"plug\",\"ok\":%s,\"host_ns\":%" PRIu64 "}\n", rc ? "false" : "true",
                   sxh_now_ns());
        } else if (strcmp(cmd, "unplug") == 0) {
            uint64_t t = sxh_now_ns();
            rc = backend_unplug();
            printf("{\"t\":\"unplug\",\"host_ns\":%" PRIu64 "}\n", t);
        } else if (strcmp(cmd, "on") == 0) {
            int vel = 100;
            sscanf(line, "%*s %d %d", &a, &vel);
            rc = send3(0x90, (uint8_t)(a & 0x7F), (uint8_t)(vel & 0x7F), "on", a);
        } else if (strcmp(cmd, "off") == 0) {
            sscanf(line, "%*s %d", &a);
            rc = send3(0x80, (uint8_t)(a & 0x7F), 0, "off", a);
        } else if (strcmp(cmd, "cc") == 0) {
            sscanf(line, "%*s %d %d", &a, &b);
            rc = send3(0xB0, (uint8_t)(a & 0x7F), (uint8_t)(b & 0x7F), "cc", a);
        } else if (strcmp(cmd, "raw") == 0) {
            int n = sscanf(line, "%*s %i %i %i", &a, &b, &c);
            uint8_t m[3] = {(uint8_t)a, (uint8_t)b, (uint8_t)c};
            rc = n > 0 ? backend_send(m, n) : 0;
        } else if (strcmp(cmd, "sleep") == 0) {
            sscanf(line, "%*s %d", &a);
            sleep_ms(a);
        } else if (strcmp(cmd, "presses") == 0) {
            int n = 0, note = 60, hold = 50, gmin = 100, gmax = 300;
            unsigned long long seed = 1;
            sscanf(line, "%*s %d %d %d %d %d %llu", &n, &note, &hold, &gmin, &gmax, &seed);
            rng = seed ? seed : 1;
            printf("{\"t\":\"presses\",\"n\":%d,\"seed\":%llu}\n", n, seed);
            for (int i = 0; i < n && rc == 0; i++) {
                rc = send3(0x90, (uint8_t)note, 100, "on", note);
                sleep_ms(hold);
                rc |= send3(0x80, (uint8_t)note, 0, "off", note);
                sleep_ms(gmin + (gmax - gmin) * uniform());
            }
        } else if (strcmp(cmd, "quit") == 0) {
            break;
        } else {
            fprintf(stderr, "sxkeys: unknown command %s\n", cmd);
        }
        if (rc != 0)
            printf("{\"t\":\"error\",\"cmd\":\"%s\"}\n", cmd);
    }
    backend_close();
    return 0;
}
