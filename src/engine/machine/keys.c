/* keys.c: key sources for the KEYS device X'20' (ARCHITECTURE 5.1, VS-03; DEV-05..07).
 *
 * MIDI, touch and the developer QWERTY mapping each own a 64-bit bitmap (bit k = key k).
 * Hosts set them from any thread (lock-free atomics). Once per render period the engine
 * latches their OR into the device's rows, so a key change posted mid-period becomes
 * visible to the program at the next period boundary and two changes in one period collapse
 * to the last level (level semantics, never edges: a lost message cannot stick a note).
 * Velocity never reaches here (INPUT-1).
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "keys.h"

#include "id_seastones.h"

#include <stdatomic.h>

static _Atomic uint64_t sources[SX_KEY_SOURCES];
static _Atomic uint32_t attached;

void sx_keys_source_set(uint32_t src, uint64_t bits)
{
    if (src >= SX_KEY_SOURCES)
        return;
    atomic_store_explicit(&sources[src], bits, memory_order_release);
    atomic_store_explicit(&attached, 1u, memory_order_release);
}

void sx_keys_source_clear(uint32_t src)
{
    if (src < SX_KEY_SOURCES)
        atomic_store_explicit(&sources[src], 0, memory_order_release);
}

uint64_t sx_keys_raw_bits(void)
{
    uint64_t all = 0;
    for (uint32_t i = 0; i < SX_KEY_SOURCES; i++)
        all |= atomic_load_explicit(&sources[i], memory_order_acquire);
    return all;
}

void sx_keys_bits_to_rows(uint64_t bits, uint8_t rows[8])
{
    for (uint32_t r = 0; r < 8; r++) {
        uint8_t v = 0;
        for (uint32_t b = 0; b < 8; b++)
            if (bits & ((uint64_t)1 << (r * 8 + b)))
                v = (uint8_t)(v | (0x80u >> b)); /* key k: row k >> 3, bit 7 - (k & 7) */
        rows[r] = v;
    }
}

void sx_keys_latch(void) /* [RT] once per period, before the CPU runs */
{
    uint8_t rows[8];
    sx_keys_bits_to_rows(sx_keys_raw_bits(), rows);
    for (uint32_t r = 0; r < 8; r++)
        sx_keys_rows[r] = rows[r];
    sx_keys_attached = atomic_load_explicit(&attached, memory_order_acquire);
}

void sx_keys_reset_sources(void) /* [non-RT] */
{
    for (uint32_t i = 0; i < SX_KEY_SOURCES; i++)
        atomic_store_explicit(&sources[i], 0, memory_order_relaxed);
    atomic_store_explicit(&attached, 0u, memory_order_relaxed);
}
