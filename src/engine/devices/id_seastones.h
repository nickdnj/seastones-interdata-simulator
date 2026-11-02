/* id_seastones.h: the engine's view of the device file (src/engine/devices/id_seastones.c).
 *
 * The device file is shared with the `id16-seastones` oracle and must not include engine
 * headers, so its state is plain SIMH-style globals; this header declares them for the
 * engine and its tests. ARCHITECTURE 5, ADR-003.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_ID_SEASTONES_H
#define SX_ID_SEASTONES_H

#include "id_defs.h"

#define SX_D_KEYS 0x20u
#define SX_D_DAC 0x21u
#define SX_D_GATE 0x22u
#define SX_DAC_CH 16u
#ifndef SX_KEY_ROWS /* also in seastones.h */
#define SX_KEY_ROWS 8u
#endif

extern uint8 sx_keys_rows[SX_KEY_ROWS];
extern uint8 sx_keys_seen[SX_KEY_ROWS];
extern uint32 sx_keys_attached, sx_keys_row, sx_keys_auto, sx_keys_reads;
extern uint16 sx_dac_code[SX_DAC_CH];
extern uint16 sx_dac_rest[SX_DAC_CH];
extern uint32 sx_dac_ch, sx_dac_auto, sx_dac_word_bits;
extern uint32 sx_gate_latch;
extern void (*sx_dev_event)(uint32 dev, uint32 ch, uint32 val, uint32 t);
extern DEVICE sx_keys_dev, sx_dac_dev, sx_gate_dev;

uint32 sx_keys_io(uint32 dev, uint32 op, uint32 dat);
uint32 sx_dac_io(uint32 dev, uint32 op, uint32 dat);
uint32 sx_gate_io(uint32 dev, uint32 op, uint32 dat);
float sx_dac_volts(uint32 code, uint32 word_bits, float range_v);
t_uint64 sx_cycle_to_frame(t_uint64 cycle, uint32 cycle_ns, uint32 rate);

#endif
