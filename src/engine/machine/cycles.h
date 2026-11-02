/* cycles.h: instruction cost in emulated cycles (VS-02, MACH-5, ARCHITECTURE 4.2).
 *
 * The table (cycles_table.c) is generated from tools/cycles/cycles-716.tsv, whose STATUS is
 * ESTIMATE: Model 74 times used as a proxy for the 7/16 (SP-S4B). sx_cycles_status names it,
 * and every report that prints a time from it must print that word too (QA CNF-08).
 *
 * Two modes:
 *   instruction mode (cycle_ns 0, the power-up default): every instruction costs one tick,
 *     exactly as stock SIMH. The S-3 lockstep and the device-trace oracle run in this mode.
 *   cycle mode (cycle_ns > 0): one tick is one emulated cycle of cycle_ns, and an instruction
 *     costs round(time / cycle_ns) cycles, at least 1.
 *
 * Patch 0001 charges SX_CYC(op) when the opcode is fetched and SX_CYC_X(...) after the
 * operand is decoded (taken branches, shift counts, registers moved), both before the
 * instruction executes, so a device write sees the time at which its instruction completes.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_CYCLES_H
#define SX_CYCLES_H

#include <stdint.h>

enum sx_cyc_kind {
    SX_CK_PLAIN = 0,
    SX_CK_BT,     /* taken when (cc & R1) != 0 */
    SX_CK_BF,     /* taken when (cc & R1) == 0 */
    SX_CK_N_R2,   /* n = R2 field */
    SX_CK_N_SH16, /* n = operand & 0xF */
    SX_CK_N_SH32, /* n = operand & 0x1F */
    SX_CK_N_REGS  /* n = 16 - R1 */
};

typedef struct sx_cyc_row {
    uint32_t base_ns;  /* not-taken time for branches; 0 = opcode not in the table */
    uint32_t per_n_ns; /* extra per unit of n */
    uint32_t taken_ns; /* branch taken, or 0 */
    uint32_t kind;     /* enum sx_cyc_kind */
} sx_cyc_row;

extern const sx_cyc_row sx_cyc_table[256];
extern const char sx_cycles_status[]; /* "ESTIMATE" until a 7/16 source is cited */
extern const unsigned sx_cycles_rows;

/* Charged by patch 0001 (hot path: plain array and one call). */
extern uint16_t sx_cyc_base1[256]; /* base cost - 1, so all-zero (never configured) is stock */
uint32_t sx_cyc_extra(uint32_t op, uint32_t r1, uint32_t r2, uint32_t opnd, uint32_t cc);

/* [non-RT] Select the mode: 0 = instruction mode, else the emulated cycle in ns. Also sets
 * the PIC and LFC to emulated time in the same unit (shim and id_uvc.c). */
void sx_cycles_configure(uint32_t cycle_ns);
uint32_t sx_cycles_cycle_ns(void); /* 0 in instruction mode */

/* The full cost of one execution, in cycles, as the CPU is charged (tests, tools). */
uint32_t sx_cycles_cost(uint32_t op, uint32_t r1, uint32_t r2, uint32_t opnd, uint32_t cc);

/* Patch 0001's hooks (the vendored file includes this header under SEASTONES_ENGINE). */
#define SX_CYC(op) (1 + (int32)sx_cyc_base1[(op) & 0xFFu])
#define SX_CYC_X(op, r1, r2, opnd, cc) ((int32)sx_cyc_extra((op), (r1), (r2), (opnd), (cc)))

#endif
