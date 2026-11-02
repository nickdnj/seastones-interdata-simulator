/* midi_coremidi.c: the CoreMIDI backend (macOS developer Macs; the station uses ALSA) (VS-13,
 * VS-18).
 *
 * One thread owns the MIDI client: CoreMIDI delivers add and remove notifications on the run
 * loop of the thread that created the client, so that thread creates it, connects every source
 * and then runs its run loop until stopped. Events arrive on CoreMIDI's own receive thread as
 * MIDI 1.0 Universal MIDI Packets; each connection's refCon is its slot + 1.
 *
 * S-2a found CoreMIDI reports an unplug about 250 ms late on this Mac (M1/S2A.md); the station's
 * ALSA announce port is the one INPUT-3 is measured on.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "midi_int.h"

#include <CoreFoundation/CoreFoundation.h>
#include <CoreMIDI/CoreMIDI.h>
#include <pthread.h>
#include <stdatomic.h>

static pthread_t thr;
static CFRunLoopRef loop;
static MIDIClientRef client;
static MIDIPortRef in_port;
static pthread_mutex_t ready_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready_cv = PTHREAD_COND_INITIALIZER;
static int ready, failed;
static _Atomic uint32_t stopping;

static void connect_source(MIDIEndpointRef src)
{
    CFStringRef cf = NULL;
    char name[128] = "";
    if (MIDIObjectGetStringProperty(src, kMIDIPropertyDisplayName, &cf) == noErr && cf) {
        CFStringGetCString(cf, name, (CFIndex)sizeof name, kCFStringEncodingUTF8);
        CFRelease(cf);
    }
    if (!sxh_midi_name_ok(name))
        return;
    int slot = sxh_midi_slot_open((uint64_t)src);
    if (slot < 0)
        return;
    if (MIDIPortConnectSource(in_port, src, (void *)(uintptr_t)(slot + 1)) != noErr)
        sxh_midi_slot_close(slot);
}

static void receive(const MIDIEventList *list, void *conn_ref)
{
    uint64_t now = sxh_now_ns();
    int slot = (int)(uintptr_t)conn_ref - 1;
    const MIDIEventPacket *p = &list->packet[0];
    /* UMP message size in words, by message type (the top nibble) */
    static const uint8_t words_of[16] = {1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4};
    for (UInt32 i = 0; i < list->numPackets; i++) {
        for (UInt32 w = 0; w < p->wordCount; w += words_of[p->words[w] >> 28]) {
            uint32_t word = p->words[w];
            if ((word >> 28) == 0x2u) /* MIDI 1.0 channel voice */
                sxh_midi_message(slot, (uint8_t)(word >> 16), (uint8_t)((word >> 8) & 0x7Fu),
                                 (uint8_t)(word & 0x7Fu), now);
            else
                sxh_midi_ignored(); /* system, SysEx, utility, MIDI 2.0 */
        }
        p = MIDIEventPacketNext(p);
    }
}

static void notify(const MIDINotification *msg)
{
    if (msg->messageID != kMIDIMsgObjectAdded && msg->messageID != kMIDIMsgObjectRemoved)
        return;
    const MIDIObjectAddRemoveNotification *ar = (const MIDIObjectAddRemoveNotification *)msg;
    if (ar->childType != kMIDIObjectType_Source)
        return;
    MIDIEndpointRef src = (MIDIEndpointRef)ar->child;
    if (msg->messageID == kMIDIMsgObjectAdded)
        connect_source(src);
    else
        sxh_midi_slot_close(sxh_midi_slot_find((uint64_t)src)); /* all its notes off */
}

static void signal_ready(int ok)
{
    pthread_mutex_lock(&ready_mu);
    ready = 1;
    failed = !ok;
    pthread_cond_signal(&ready_cv);
    pthread_mutex_unlock(&ready_mu);
}

static void *run(void *arg)
{
    (void)arg;
    loop = CFRunLoopGetCurrent();
    if (MIDIClientCreateWithBlock(CFSTR("seastones-rigd"), &client,
                                  ^(const MIDINotification *msg) {
                                    notify(msg);
                                  }) != noErr ||
        MIDIInputPortCreateWithProtocol(client, CFSTR("seastones-keys"), kMIDIProtocol_1_0,
                                        &in_port, ^(const MIDIEventList *l, void *ref) {
                                          receive(l, ref);
                                        }) != noErr) {
        signal_ready(0);
        return NULL;
    }
    ItemCount n = MIDIGetNumberOfSources();
    for (ItemCount i = 0; i < n; i++)
        connect_source(MIDIGetSource(i));
    signal_ready(1);
    while (!atomic_load(&stopping)) /* bounded waits, so a stop before we got here still ends */
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.25, false);
    MIDIPortDispose(in_port);
    MIDIClientDispose(client);
    return NULL;
}

int sxh_midi_backend_start(void)
{
    ready = failed = 0;
    atomic_store(&stopping, 0u);
    if (pthread_create(&thr, NULL, run, NULL) != 0)
        return SXH_E_STATE;
    pthread_mutex_lock(&ready_mu);
    while (!ready)
        pthread_cond_wait(&ready_cv, &ready_mu);
    pthread_mutex_unlock(&ready_mu);
    if (failed) {
        pthread_join(thr, NULL);
        return SXH_E_DEVICE;
    }
    return SXH_OK;
}

void sxh_midi_backend_stop(void)
{
    atomic_store(&stopping, 1u);
    CFRunLoopStop(loop);
    CFRunLoopWakeUp(loop);
    pthread_join(thr, NULL);
}
