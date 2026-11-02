/* supervisor.h: the engine's fail-silent supervisor (VS-16; ARCHITECTURE 8.1; MACH-7, KIOSK-4).
 *
 * Checked in the render call, every period, in EMULATED time, so the speed knob never looks like a
 * fault (a slowed CPU reads the keyboard just as often per emulated second):
 *   program_stalled  the CPU stopped itself (HALT, a trap with stops on); or it sits in a wait
 *                    state with external interrupts off (it can never leave); or PC left the
 *                    program's code segment (wandered, e.g. after an illegal-instruction swap);
 *                    or no KEYS row read for liveness_ms = 50 ms of emulated time
 *   dsp_fault        non-finite audio caught 3 times within 1 s, or runaway DC at the voice
 *                    output (above 0.25 of full scale for 100 ms)
 * In SINGLE (and while halted by the panel) the CPU checks are suspended: emulated time is not
 * passing. A fault mutes through the safety chain's 5 ms ramp and stays latched until HOME, which
 * rigd sends to recover (8.1). No fault path makes any sound.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_SUPERVISOR_H
#define SX_SUPERVISOR_H

#include <stdint.h>

#include "clock.h"

#define SX_LIVENESS_MS 50u
#define SX_DC_LIMIT 0.25
#define SX_DC_MS 100u
#define SX_NONFINITE_REPEAT 3u

typedef struct sx_supervisor {
    uint16_t code_lo, code_hi; /* the program's code: [lo, hi) */
    uint64_t last_read_cycle;
    uint32_t last_reads;
    uint64_t liveness_cycles;
    double dc; /* one-pole low-pass of the voice output */
    double dc_coeff;
    uint32_t dc_run, dc_limit_frames; /* frames above the limit in a row */
    uint32_t nf_count;                /* non-finite catches in the current window */
    uint64_t nf_window_start;         /* frame */
    uint32_t rate;
    uint32_t faults; /* SX_FAULT_* bits, latched */
} sx_supervisor;

void sx_sup_init(sx_supervisor *s, uint32_t rate, uint32_t cycle_ns);
/* [RT] at load and HOME: the code range from the image, and a fresh start */
void sx_sup_reset(sx_supervisor *s, uint16_t code_lo, uint16_t code_hi);
/* [RT] after the CPU's period */
uint32_t sx_sup_check_cpu(sx_supervisor *s, const sx_clock *clk);
/* [RT] the voice output before the safety chain; `nonfinite` = catches this period */
uint32_t sx_sup_check_audio(sx_supervisor *s, const float *mono, uint32_t n, uint64_t frame0,
                            uint32_t nonfinite);

#endif
