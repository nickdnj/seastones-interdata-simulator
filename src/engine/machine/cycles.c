/* cycles.c: instruction cost in emulated cycles (VS-02; see cycles.h).
 *
 * The cost model is tools/cycle-calc.py's: one execution costs
 * (taken ? taken_ns : base_ns) + per_n_ns * n, converted to cycles of cycle_ns. The table's
 * STATUS is ESTIMATE (Model 74 proxy, SP-S4B); so is every time computed from it.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "cycles.h"

#include "scp_shim.h"

extern uint16 pic_time[4]; /* id_uvc.c: interval ticks per PIC unit of 1, 10, 100, 1000 us */
extern UNIT lfc_unit;      /* id_uvc.c: line clock; .wait is its initial interval */
extern int32 lfc_tps;      /* id_uvc.c: line clock ticks per second (120 = 60 Hz mains) */

uint16_t sx_cyc_base1[256]; /* cost - 1: zero (stock, one tick) until configured */

static uint32_t cyc_ns;         /* 0 = instruction mode */
static uint16_t cyc_per_n[256]; /* cycles per unit of n */
static uint16_t cyc_taken[256]; /* extra cycles when a branch is taken */
static uint8_t cyc_kind[256];   /* enum sx_cyc_kind */
static const uint16_t stock_pic_time[4] = {1, 10, 100, 1000};

static uint16_t to_cycles(uint32_t ns, uint32_t per)
{
    uint32_t c = (ns + per / 2u) / per; /* round to nearest; every TSV value is a multiple of 250 */
    return (uint16_t)(c > 0xFFFFu ? 0xFFFFu : c);
}

void sx_cycles_configure(uint32_t cycle_ns)
{
    cyc_ns = cycle_ns;
    for (uint32_t op = 0; op < 256; op++) {
        const sx_cyc_row *r = &sx_cyc_table[op];
        if (cycle_ns == 0 || r->base_ns == 0) {
            /* stock cost, and the trap cost of an opcode not in the table: one tick */
            sx_cyc_base1[op] = 0;
            cyc_per_n[op] = cyc_taken[op] = 0;
            cyc_kind[op] = SX_CK_PLAIN;
            continue;
        }
        uint16_t base = to_cycles(r->base_ns, cycle_ns);
        base = base ? base : 1u;
        sx_cyc_base1[op] = (uint16_t)(base - 1u);
        cyc_per_n[op] = to_cycles(r->per_n_ns, cycle_ns);
        uint16_t taken = r->taken_ns ? to_cycles(r->taken_ns, cycle_ns) : base;
        cyc_taken[op] = (uint16_t)(taken > base ? (unsigned)(taken - base) : 0u);
        cyc_kind[op] = (uint8_t)r->kind;
    }
    /* The clocks in the same unit: PIC intervals of 1, 10, 100, 1000 us, and the line clock
     * at lfc_tps per emulated second. The shim's calibration answers in emulated time too. */
    uint32_t per_us = cycle_ns ? 1000u / cycle_ns : 0u;
    for (uint32_t i = 0; i < 4; i++)
        pic_time[i] =
            cycle_ns ? (uint16)(stock_pic_time[i] * (per_us ? per_us : 1u)) : stock_pic_time[i];
    sx_shim_set_cycle_ns(cycle_ns);
    if (cycle_ns)
        lfc_unit.wait = (int32)(1000000000u / cycle_ns / (uint32_t)(lfc_tps > 0 ? lfc_tps : 120));
    else
        lfc_unit.wait = 8000; /* id_uvc.c's power-up value */
}

uint32_t sx_cycles_cycle_ns(void)
{
    return cyc_ns;
}

uint32_t sx_cyc_extra(uint32_t op, uint32_t r1, uint32_t r2, uint32_t opnd, uint32_t cc)
{
    op &= 0xFFu;
    switch (cyc_kind[op]) {
    case SX_CK_BT:
        return (cc & r1) ? cyc_taken[op] : 0u;
    case SX_CK_BF:
        return (cc & r1) == 0 ? cyc_taken[op] : 0u;
    case SX_CK_N_R2:
        return cyc_per_n[op] * (r2 & 0xFu);
    case SX_CK_N_SH16:
        return cyc_per_n[op] * (opnd & 0xFu);
    case SX_CK_N_SH32:
        return cyc_per_n[op] * (opnd & 0x1Fu);
    case SX_CK_N_REGS:
        return cyc_per_n[op] * (16u - (r1 & 0xFu));
    default:
        return 0;
    }
}

uint32_t sx_cycles_cost(uint32_t op, uint32_t r1, uint32_t r2, uint32_t opnd, uint32_t cc)
{
    return 1u + sx_cyc_base1[op & 0xFFu] + sx_cyc_extra(op, r1, r2, opnd, cc);
}
