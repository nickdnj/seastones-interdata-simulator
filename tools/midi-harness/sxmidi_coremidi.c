/*
 * sxmidi CoreMIDI backend (macOS, development only; the station uses ALSA).
 * Uses the MIDI 1.0 Universal MIDI Packet API (macOS 11+). The receive block runs on
 * CoreMIDI's own high-priority thread; it only stores times into preallocated arrays.
 * Removal notices arrive on the run loop of the thread that created the client (main), so the
 * main thread pumps its run loop while it waits.
 */
#include "sxmidi.h"

#include <CoreFoundation/CoreFoundation.h>
#include <CoreMIDI/CoreMIDI.h>
#include <mach/mach_time.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>

static uint64_t g_send[SXMIDI_MAX_EVENTS], g_arrive[SXMIDI_MAX_EVENTS], g_ts[SXMIDI_MAX_EVENTS];
static atomic_uint g_next_expected;
static atomic_uint g_out_of_order;
static _Atomic uint64_t g_removed_ns;
static MIDIEndpointRef g_vsrc;

static uint64_t ht_to_ns(MIDITimeStamp t) {
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0) mach_timebase_info(&tb);
    return t * tb.numer / tb.denom;
}

static void pump(double seconds) { CFRunLoopRunInMode(kCFRunLoopDefaultMode, seconds, true); }

static unsigned decode(uint32_t w) {
    unsigned note = (w >> 8) & 0x7F, vel = w & 0x7F;
    return note * 127u + (vel - 1u);
}

int sxmidi_selftest(unsigned n, double spacing_ms, unsigned seed, sxmidi_selftest_result *r) {
    r->backend = "coremidi";
    MIDIClientRef client;
    OSStatus st = MIDIClientCreateWithBlock(CFSTR("sxmidi"), &client, ^(const MIDINotification *msg) {
      if (msg->messageID == kMIDIMsgObjectRemoved) {
          const MIDIObjectAddRemoveNotification *ar = (const MIDIObjectAddRemoveNotification *)msg;
          if (ar->childType == kMIDIObjectType_Source && ar->child == g_vsrc)
              atomic_store(&g_removed_ns, sxmidi_now_ns());
      }
    });
    if (st != noErr) return -1;

    MIDIPortRef in;
    st = MIDIInputPortCreateWithProtocol(client, CFSTR("sxmidi-in"), kMIDIProtocol_1_0, &in,
                                         ^(const MIDIEventList *list, void *ref) {
                                           (void)ref;
                                           uint64_t now = sxmidi_now_ns();
                                           const MIDIEventPacket *p = &list->packet[0];
                                           for (UInt32 i = 0; i < list->numPackets; i++) {
                                               uint32_t w = p->words[0];
                                               if (((w >> 28) & 0xF) == 0x2 && ((w >> 20) & 0xF) == 0x9) {
                                                   unsigned idx = decode(w);
                                                   unsigned exp = atomic_fetch_add(&g_next_expected, 1);
                                                   if (idx != exp) atomic_fetch_add(&g_out_of_order, 1);
                                                   if (idx < SXMIDI_MAX_EVENTS) {
                                                       g_arrive[idx] = now;
                                                       g_ts[idx] = ht_to_ns(p->timeStamp);
                                                   }
                                               }
                                               p = MIDIEventPacketNext(p);
                                           }
                                         });
    if (st != noErr) return -1;
    if (MIDISourceCreateWithProtocol(client, CFSTR("sxmidi-virtual-keyboard"), kMIDIProtocol_1_0, &g_vsrc) != noErr)
        return -1;
    if (MIDIPortConnectSource(in, g_vsrc, NULL) != noErr) return -1;
    pump(0.2); /* let the connection settle */

    srand(seed);
    for (unsigned i = 0; i < n; i++) {
        uint32_t note = i / 127u, vel = i % 127u + 1u;
        uint32_t word = (0x2u << 28) | (0x90u << 16) | (note << 8) | vel; /* MIDI 1.0 note-on, group 0 ch 0 */
        MIDIEventList list;
        MIDIEventPacket *pkt = MIDIEventListInit(&list, kMIDIProtocol_1_0);
        uint64_t t = sxmidi_now_ns();
        MIDITimeStamp ht = mach_absolute_time();
        pkt = MIDIEventListAdd(&list, sizeof list, pkt, ht, 1, &word);
        g_send[i] = t;
        MIDIReceivedEventList(g_vsrc, &list);
        double jitter = spacing_ms * 0.5 * ((double)rand() / RAND_MAX);
        sxmidi_sleep_ns((uint64_t)((spacing_ms + jitter) * 1e6));
    }
    pump(0.2);
    r->out_of_order = atomic_load(&g_out_of_order);
    sxmidi_stats(g_send, g_arrive, g_ts, n, r);

    /* simulated unplug: remove the virtual source and time the removal notice */
    uint64_t t_unplug = sxmidi_now_ns();
    MIDIEndpointDispose(g_vsrc);
    while (!atomic_load(&g_removed_ns) && sxmidi_now_ns() - t_unplug < 2000000000ull) pump(0.001);
    uint64_t rm = atomic_load(&g_removed_ns);
    r->unplug_seen = rm != 0;
    r->unplug_ms = rm ? (double)(rm - t_unplug) / 1e6 : -1.0;
    MIDIPortDispose(in);
    MIDIClientDispose(client);
    return 0;
}

/* ------------------------------------------------------------------ listen */

static volatile sig_atomic_t g_stop;
static void on_sig(int s) { (void)s; g_stop = 1; }
static MIDIPortRef g_lin;

static void connect_all(void) {
    ItemCount n = MIDIGetNumberOfSources();
    for (ItemCount i = 0; i < n; i++) MIDIPortConnectSource(g_lin, MIDIGetSource(i), (void *)(uintptr_t)(i + 1));
}

static void name_of(MIDIObjectRef o, char *buf, size_t len) {
    CFStringRef s = NULL;
    buf[0] = 0;
    if (MIDIObjectGetStringProperty(o, kMIDIPropertyDisplayName, &s) == noErr && s) {
        CFStringGetCString(s, buf, (CFIndex)len, kCFStringEncodingUTF8);
        CFRelease(s);
    }
}

int sxmidi_listen(double seconds, const char *sync_path, double sync_every_ms) {
    signal(SIGINT, on_sig);
    signal(SIGTERM, on_sig);
    setvbuf(stdout, NULL, _IOLBF, 0);
    MIDIClientRef client;
    if (MIDIClientCreateWithBlock(CFSTR("sxmidi-listen"), &client, ^(const MIDINotification *msg) {
          uint64_t now = sxmidi_now_ns();
          if (msg->messageID == kMIDIMsgObjectAdded || msg->messageID == kMIDIMsgObjectRemoved) {
              const MIDIObjectAddRemoveNotification *ar = (const MIDIObjectAddRemoveNotification *)msg;
              if (ar->childType != kMIDIObjectType_Source) return;
              int added = msg->messageID == kMIDIMsgObjectAdded;
              char nm[128] = "";
              if (added) {
                  name_of(ar->child, nm, sizeof nm);
                  MIDIPortConnectSource(g_lin, ar->child, NULL);
              }
              printf("{\"type\":\"%s\",\"host_ns\":%llu,\"source\":%u,\"name\":\"%s\"}\n",
                     added ? "source_added" : "source_removed", (unsigned long long)now, (unsigned)ar->child, nm);
          }
        }) != noErr)
        return 1;
    if (MIDIInputPortCreateWithProtocol(client, CFSTR("sxmidi-listen-in"), kMIDIProtocol_1_0, &g_lin,
                                        ^(const MIDIEventList *list, void *ref) {
                                          uint64_t now = sxmidi_now_ns();
                                          const MIDIEventPacket *p = &list->packet[0];
                                          for (UInt32 i = 0; i < list->numPackets; i++) {
                                              uint32_t w = p->words[0];
                                              unsigned status = (w >> 16) & 0xF0, note = (w >> 8) & 0x7F,
                                                       vel = w & 0x7F;
                                              if (((w >> 28) & 0xF) == 0x2 && (status == 0x90 || status == 0x80)) {
                                                  const char *t = (status == 0x90 && vel) ? "note_on" : "note_off";
                                                  printf("{\"type\":\"%s\",\"note\":%u,\"velocity\":%u,"
                                                         "\"host_ns\":%llu,\"driver_ns\":%llu,\"src\":%lu}\n",
                                                         t, note, vel, (unsigned long long)now,
                                                         (unsigned long long)ht_to_ns(p->timeStamp),
                                                         (unsigned long)(uintptr_t)ref);
                                              }
                                              p = MIDIEventPacketNext(p);
                                          }
                                        }) != noErr)
        return 1;
    connect_all();
    int fd = -1;
    if (sync_path && (fd = open(sync_path, O_WRONLY | O_NOCTTY)) < 0) {
        fprintf(stderr, "sxmidi: cannot open %s\n", sync_path);
        return 1;
    }
    uint64_t t0 = sxmidi_now_ns(), next_sync = t0;
    while (!g_stop && (double)(sxmidi_now_ns() - t0) / 1e9 < seconds) {
        if (fd >= 0 && sxmidi_now_ns() >= next_sync) {
            unsigned char b = 'S';
            if (write(fd, &b, 1) == 1)
                printf("{\"type\":\"sync\",\"host_ns\":%llu}\n", (unsigned long long)sxmidi_now_ns());
            next_sync += (uint64_t)(sync_every_ms * 1e6);
        }
        pump(0.005);
    }
    if (fd >= 0) close(fd);
    MIDIClientDispose(client);
    return 0;
}
