/* keys.h: key sources for KEYS X'20' (see keys.c). Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SX_KEYS_H
#define SX_KEYS_H

#include <stdint.h>

#define SX_KEY_SOURCES 3u /* MIDI, TOUCH, DEV_QWERTY (sx_key_source in seastones.h) */

void sx_keys_source_set(uint32_t src, uint64_t bits); /* [any thread] */
void sx_keys_source_clear(uint32_t src);              /* [any thread] a vanished port */
uint64_t sx_keys_raw_bits(void);                      /* [any thread] OR of all sources */
void sx_keys_bits_to_rows(uint64_t bits, uint8_t rows[8]);
void sx_keys_latch(void);         /* [RT] once per period */
void sx_keys_reset_sources(void); /* [non-RT] */

#endif
