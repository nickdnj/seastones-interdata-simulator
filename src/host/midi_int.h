/* midi_int.h: what the MIDI backends share (VS-13, VS-18). See midi.c.
 * Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SXH_MIDI_INT_H
#define SXH_MIDI_INT_H

#include <stdint.h>

#include "sxhost.h"

#define SXH_MIDI_SLOTS 32 /* sources connected at once */

/* a source appeared: returns its slot, or -1 when all are taken; `key` identifies it */
int sxh_midi_slot_open(uint64_t key);
/* that source vanished: its keys are released at once (INPUT-3) */
void sxh_midi_slot_close(int slot);
int sxh_midi_slot_find(uint64_t key);
/* does a source of this name pass the filter (sxh_midi_filter)? */
int sxh_midi_name_ok(const char *name);
/* one MIDI 1.0 channel message from a source's slot, arrived at host time `ns` */
void sxh_midi_message(int slot, uint8_t status, uint8_t d1, uint8_t d2, uint64_t ns);
void sxh_midi_ignored(void);

/* backends: start their thread, connect every source, follow hot-plug; stop joins it */
int sxh_midi_backend_start(void);
void sxh_midi_backend_stop(void);

#endif
