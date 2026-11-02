/* supervisor.c: the fail-silent supervisor (VS-16; see supervisor.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "supervisor.h"

#include "id_seastones.h"
#include "scp_shim.h"
#include "seastones.h"
#include "sx_math.h"

extern uint32 PC, PSW;

/* PSW_WAIT (X'8000') and PSW_EXI (X'4000', external interrupts enabled) are id_defs.h's */

void sx_sup_init(sx_supervisor *s, uint32_t rate, uint32_t cycle_ns)
{
    *s = (sx_supervisor){0};
    s->rate = rate;
    s->liveness_cycles = (uint64_t)SX_LIVENESS_MS * 1000000u / (cycle_ns ? cycle_ns : 250u);
    /* DC detector: a 5 Hz one-pole low-pass, exp(-2 pi 5 / rate) */
    s->dc_coeff = sx_exp2(-6.283185307179586 * 5.0 / (double)rate / 0.69314718055994531);
    s->dc_limit_frames = rate * SX_DC_MS / 1000u;
}

void sx_sup_reset(sx_supervisor *s, uint16_t code_lo, uint16_t code_hi)
{
    s->code_lo = code_lo;
    s->code_hi = code_hi;
    s->last_read_cycle = sx_shim_now64();
    s->last_reads = sx_keys_reads;
    s->dc = 0.0;
    s->dc_run = 0;
    s->nf_count = 0;
    s->nf_window_start = 0;
    s->faults = 0;
}

uint32_t sx_sup_check_cpu(sx_supervisor *s, const sx_clock *c)
{
    uint64_t now = sx_shim_now64();
    if (sx_keys_reads != s->last_reads) {
        s->last_reads = sx_keys_reads;
        s->last_read_cycle = now;
    }
    if (c->stop) /* the CPU stopped itself: not a deliberate panel HALT */
        s->faults |= SX_FAULT_PROGRAM_STALLED | SX_FAULT_CPU_STOPPED;
    if (!c->running || c->divisor == 0)
        return s->faults; /* panel HALT or SINGLE: no emulated time passes, nothing to judge */
    uint32_t pc = PC & 0xFFFFu;
    if (pc < s->code_lo || pc >= s->code_hi) /* wandered */
        s->faults |= SX_FAULT_PROGRAM_STALLED;
    if ((PSW & PSW_WAIT) && !(PSW & PSW_EXI)) /* waiting with no way out: halted */
        s->faults |= SX_FAULT_PROGRAM_STALLED;
    if (now - s->last_read_cycle > s->liveness_cycles) /* stopped reading the keyboard */
        s->faults |= SX_FAULT_PROGRAM_STALLED;
    return s->faults;
}

uint32_t sx_sup_check_audio(sx_supervisor *s, const float *mono, uint32_t n, uint64_t frame0,
                            uint32_t nonfinite)
{
    if (nonfinite) {
        if (s->nf_count == 0 || frame0 - s->nf_window_start > s->rate) {
            s->nf_window_start = frame0;
            s->nf_count = 0;
        }
        s->nf_count += nonfinite;
        if (s->nf_count >= SX_NONFINITE_REPEAT)
            s->faults |= SX_FAULT_DSP;
    }
    for (uint32_t i = 0; i < n; i++) {
        double x = (double)mono[i];
        if (!(x - x == 0.0))
            continue; /* counted by the safety chain */
        s->dc = x + (s->dc - x) * s->dc_coeff;
        if (s->dc > SX_DC_LIMIT || s->dc < -SX_DC_LIMIT) {
            if (++s->dc_run >= s->dc_limit_frames)
                s->faults |= SX_FAULT_DSP;
        } else {
            s->dc_run = 0;
        }
    }
    return s->faults;
}
