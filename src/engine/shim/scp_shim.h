/* scp_shim.h: the engine's side of the minimal SCP (ARCHITECTURE 4.2, ADR-001, SP-S3B).
 *
 * SIMH's control program (scp.c, sim_timer.c, sim_console.c ...) is not linked into the
 * engine. scp_shim.c implements only the SCP surface that the vendored Interdata files
 * call: the interval and event queue, emulated-time clock calibration, idle, breakpoint
 * flags, a few parse and print helpers, and device lookup. This header adds the handful
 * of entry points the engine uses to drive the CPU.
 *
 * Copyright (c) 2026 Nick D. MIT licence (see THIRD-PARTY-NOTICES for SIMH's).
 */
#ifndef SX_SCP_SHIM_H
#define SX_SCP_SHIM_H

#include "sim_defs.h"

/* Power-up reset of every device in sim_devices, in table order (SCP reset_all_p). */
t_stat sx_shim_reset_all(void);

/* Run the CPU for at most `ticks` interval ticks (SCP's STEP: one tick is one instruction
 * at the stock cost of patch 0001, or one idle pass in the wait state). Returns the stop
 * reason: SCPE_STEP when the ticks ran out, otherwise the CPU's own reason. */
t_stat sx_shim_run(int32 ticks);

/* Emulated time in interval ticks since the last sx_shim_reset_all (SCP sim_grtime). */
uint32 sx_shim_time(void);
uint64_t sx_shim_now64(void); /* the same, without SCP's 32-bit wrap */

/* Tick unit (VS-02): 0 = one tick per instruction, as stock SCP (S-3, oracle traces);
 * otherwise one emulated cycle of `cycle_ns`, with clock calibration and the wait state in
 * emulated time. Set through sx_cycles_configure (machine/cycles.c). */
void sx_shim_set_cycle_ns(uint32 cycle_ns);

/* Disassemble the instruction at byte address `addr` with SIMH's fprint_sym, exactly as
 * `ex -m` prints it after the "addr:\t" prefix. Returns the number of bytes consumed
 * (2 or 4), or 0 if `n` is too small. Non-RT. */
size_t sx_shim_disasm(uint32 addr, char *buf, size_t n);

/* Text for a stop reason (SCP's stop messages for simulator codes). */
const char *sx_shim_reason(t_stat r);

#endif
