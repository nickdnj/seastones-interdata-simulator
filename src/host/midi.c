/* midi.c: MIDI keys for the engine, independent of the backend (VS-13, VS-18; ARCHITECTURE 5.1,
 * 8.1; INPUT-1, INPUT-3).
 *
 * Every connected source has a slot with its own 64-bit key bitmap. After any change the OR of
 * all slots, less the held-key mask, becomes the engine's MIDI source (sx_keys_set is level, not
 * edge, so a lost event cannot stick a note past the next change). A source that vanishes has
 * its slot cleared at once: all its notes are off, and the program releases them on its next
 * scan. The other sources and the touch keys are untouched (DEV-05).
 *
 * The mask (sxh_midi_mask) holds keys down-but-ignored until each is released on every source:
 * HOME and the 60 s held-key rule (PLAY-8) use it, so a key held through HOME does not sound
 * again until it is pressed again.
 *
 * These run on the backends' MIDI threads (CoreMIDI's receive thread, or our ALSA thread) and on
 * the control thread, never on the audio thread, so a short mutex orders them.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "midi_int.h"

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static struct {
    int used;
    uint64_t key;
    uint64_t bits;
} slots[SXH_MIDI_SLOTS];

static sx_engine *eng;
static int32_t base = 48;
static uint32_t nkeys = 37;
static uint64_t mask, physical;
static int running;
static uint32_t nsources;
static _Atomic uint64_t events, ignored, plugs, unplugs, last_unplug_ns, last_on_ns;
static _Atomic int32_t last_on = -1;
static _Atomic uint32_t gen;
static char filter[128];

void sxh_midi_filter(const char *part)
{
    pthread_mutex_lock(&mu);
    snprintf(filter, sizeof filter, "%s", part ? part : "");
    pthread_mutex_unlock(&mu);
}

int sxh_midi_name_ok(const char *name)
{
    pthread_mutex_lock(&mu);
    int ok = filter[0] == 0 || (name && strstr(name, filter) != NULL);
    pthread_mutex_unlock(&mu);
    return ok;
}

static uint64_t key_range(void)
{
    return nkeys >= 64u ? UINT64_MAX : (((uint64_t)1 << nkeys) - 1u);
}

/* under mu */
static void publish(void)
{
    uint64_t all = 0;
    for (int i = 0; i < SXH_MIDI_SLOTS; i++)
        if (slots[i].used)
            all |= slots[i].bits;
    physical = all;
    mask &= all; /* a masked key released everywhere is free again */
    if (eng)
        sx_keys_set(eng, SX_KEYS_MIDI, all & ~mask & key_range());
}

int sxh_midi_slot_open(uint64_t key)
{
    pthread_mutex_lock(&mu);
    int slot = -1;
    for (int i = 0; i < SXH_MIDI_SLOTS; i++) {
        if (slots[i].used && slots[i].key == key) {
            slot = i; /* already connected */
            break;
        }
    }
    for (int i = 0; slot < 0 && i < SXH_MIDI_SLOTS; i++) {
        if (!slots[i].used) {
            slots[i].used = 1;
            slots[i].key = key;
            slots[i].bits = 0;
            slot = i;
            nsources++;
            atomic_fetch_add(&plugs, 1u);
            atomic_fetch_add(&gen, 1u);
        }
    }
    pthread_mutex_unlock(&mu);
    return slot;
}

void sxh_midi_slot_close(int slot)
{
    if (slot < 0 || slot >= SXH_MIDI_SLOTS)
        return;
    pthread_mutex_lock(&mu);
    if (slots[slot].used) {
        slots[slot].used = 0;
        slots[slot].bits = 0;
        nsources--;
        publish(); /* all of its notes off, now */
        atomic_fetch_add(&unplugs, 1u);
        atomic_store(&last_unplug_ns, sxh_now_ns());
        atomic_fetch_add(&gen, 1u);
    }
    pthread_mutex_unlock(&mu);
}

int sxh_midi_slot_find(uint64_t key)
{
    pthread_mutex_lock(&mu);
    int slot = -1;
    for (int i = 0; i < SXH_MIDI_SLOTS; i++)
        if (slots[i].used && slots[i].key == key)
            slot = i;
    pthread_mutex_unlock(&mu);
    return slot;
}

void sxh_midi_ignored(void)
{
    atomic_fetch_add(&ignored, 1u);
}

void sxh_midi_message(int slot, uint8_t status, uint8_t d1, uint8_t d2, uint64_t ns)
{
    if (slot < 0 || slot >= SXH_MIDI_SLOTS)
        return;
    uint8_t kind = status & 0xF0u;
    int on = kind == 0x90u && d2 != 0u; /* note-on with velocity 0 is note-off */
    int off = kind == 0x80u || (kind == 0x90u && d2 == 0u);
    int all_off = kind == 0xB0u && (d1 == 120u || d1 == 123u); /* all sound / all notes off */
    if (!on && !off && !all_off) {
        atomic_fetch_add(&ignored, 1u);
        return;
    }
    int32_t k = (int32_t)d1 - base;
    if (!all_off && (k < 0 || k >= (int32_t)nkeys)) {
        atomic_fetch_add(&ignored, 1u); /* outside the keyboard (VS-29 default, PRG-09) */
        return;
    }
    pthread_mutex_lock(&mu);
    if (slots[slot].used) {
        if (all_off)
            slots[slot].bits = 0;
        else if (on)
            slots[slot].bits |= (uint64_t)1 << k;
        else
            slots[slot].bits &= ~((uint64_t)1 << k);
        publish();
    }
    pthread_mutex_unlock(&mu);
    if (!all_off)
        atomic_fetch_add(&events, 1u);
    if (on) {
        atomic_store(&last_on_ns, ns);
        atomic_store(&last_on, (int32_t)d1);
    }
}

void sxh_midi_mask(uint64_t bits)
{
    pthread_mutex_lock(&mu);
    mask |= bits & physical;
    publish();
    pthread_mutex_unlock(&mu);
}

void sxh_midi_status_read(sxh_midi_status *s)
{
    if (s == NULL)
        return;
    memset(s, 0, sizeof *s);
    pthread_mutex_lock(&mu);
    s->running = (uint32_t)running;
    s->sources = nsources;
    s->bits = physical;
    s->masked = mask;
    pthread_mutex_unlock(&mu);
    s->events = atomic_load(&events);
    s->ignored = atomic_load(&ignored);
    s->plugs = atomic_load(&plugs);
    s->unplugs = atomic_load(&unplugs);
    s->last_unplug_ns = atomic_load(&last_unplug_ns);
    s->last_note_on_ns = atomic_load(&last_on_ns);
    s->last_note_on = atomic_load(&last_on);
    s->gen = atomic_load(&gen);
}

int sxh_midi_start(sx_engine *e, int32_t base_note, uint32_t keys)
{
    if (e == NULL || keys == 0u || keys > 64u || base_note < 0 || base_note > 127)
        return SXH_E_ARG;
    pthread_mutex_lock(&mu);
    if (running) {
        pthread_mutex_unlock(&mu);
        return SXH_E_STATE;
    }
    memset(slots, 0, sizeof slots);
    eng = e;
    base = base_note;
    nkeys = keys;
    mask = physical = 0;
    nsources = 0;
    running = 1;
    pthread_mutex_unlock(&mu);
    int rc = sxh_midi_backend_start();
    if (rc != SXH_OK) {
        pthread_mutex_lock(&mu);
        running = 0;
        eng = NULL;
        pthread_mutex_unlock(&mu);
    }
    return rc;
}

void sxh_midi_stop(void)
{
    pthread_mutex_lock(&mu);
    int was = running;
    pthread_mutex_unlock(&mu);
    if (!was)
        return;
    sxh_midi_backend_stop();
    pthread_mutex_lock(&mu);
    for (int i = 0; i < SXH_MIDI_SLOTS; i++)
        slots[i].used = 0;
    nsources = 0;
    publish();
    eng = NULL;
    running = 0;
    pthread_mutex_unlock(&mu);
}
