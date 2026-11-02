/* clock.h: the emulated clock, driven by the audio sample count (VS-02; ARCHITECTURE 4.2, 7).
 *
 * One render period of N frames is N / rate seconds of audio. At RUN that is the same span of
 * emulated time; at a slower speed it is that span divided by the speed's divisor. The CPU is
 * run, in cycle mode (cycles.h), until it reaches the cycle that corresponds to the end of the
 * period. Nothing reads a host clock: emulated time is a pure function of the frames rendered
 * and the commands applied, so the same inputs always give the same outputs.
 *
 * Cycle costs come from the cycle table, whose STATUS is ESTIMATE (Model 74 proxy, SP-S4B).
 * "RUN" therefore means "as fast as the ESTIMATE says a 7/16 ran", and says so wherever it is
 * shown (sx_cycles_status).
 *
 * Arithmetic is exact integers: the cycles due after F frames are
 *     base_cycle + floor((F - base_frame) * 1e9 / (rate * cycle_ns * divisor))
 * kept as a running quotient and remainder, rebased whenever the remainder is zero (and at
 * every speed change), so nothing drifts and nothing overflows however long the engine runs.
 *
 * D/A and gate writes are stamped with the frame of the period on which they take effect (the
 * inverse mapping), clamped to the period, and collected in a caller-owned buffer: the
 * devices-to-DSP seam of ARCHITECTURE 12.1, `(frame, line, value)` per period.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_CLOCK_H
#define SX_CLOCK_H

#include <stdint.h>

#include "seastones.h"

/* Speed positions: enum sx_speed in seastones.h (PANEL-2, ARCHITECTURE 7). */
#define SX_SPEED_MAX_DIVISOR 100000u

uint32_t sx_speed_divisor(uint32_t position); /* SX_SPEED_NPOS or above: UINT32_MAX */

/* One device write as the DSP sees it (ARCHITECTURE 12.1). */
typedef struct sx_dev_ev {
    uint32_t frame; /* offset in the period, 0 .. frames-1 */
    uint8_t dev;    /* 0x21 DAC or 0x22 GATE */
    uint8_t ch;     /* D/A channel; 0 for the gate latch */
    uint16_t val;   /* latched code (after word-size truncation) or gate bits */
} sx_dev_ev;

/* Called for every write with its 64-bit emulated cycle (the Phase 2 seam, P2-3). */
typedef void (*sx_clock_sink)(void *ctx, uint64_t emu_cycle, uint8_t dev, uint8_t ch, uint16_t val);

typedef struct sx_clock {
    uint32_t rate;     /* frames per second */
    uint32_t cycle_ns; /* emulated cycle length */
    uint32_t divisor;  /* 1 = RUN, 10, 100 ...; 0 = SINGLE */
    uint32_t running;  /* 0 after HALT or a CPU stop */
    uint32_t steps;    /* STEP commands not yet executed (SINGLE) */
    int32_t stop;      /* the CPU's last stop reason other than "slice done" (0 = none) */
    uint64_t frame;    /* frames rendered since init */
    uint64_t target;   /* the cycle the CPU is due to have reached */
    uint64_t acc;      /* remainder numerator, < den */
    uint64_t base_cycle, base_frame;
    uint64_t instructions; /* executed in SINGLE (tests) */
    /* the current period's writes */
    sx_dev_ev *ev;
    uint32_t ev_cap, ev_n;
    uint32_t ev_lost; /* writes that did not fit (never expected: see sx_clock_ev_capacity) */
    uint32_t period_frames;
    sx_clock_sink sink;
    void *sink_ctx;
} sx_clock;

/* [non-RT] Initialise; selects cycle mode in the CPU (sx_cycles_configure) and installs the
 * device-event handler. `ev` holds `ev_cap` writes per period. The machine starts halted at
 * RUN speed; RUN starts it. */
void sx_clock_init(sx_clock *c, uint32_t rate, uint32_t cycle_ns, sx_dev_ev *ev, uint32_t ev_cap);

/* The number of writes one period of `max_frames` can produce at RUN (the slowest instruction
 * that writes is the cheapest instruction in the table): size `ev` with this. */
uint32_t sx_clock_ev_capacity(uint32_t rate, uint32_t cycle_ns, uint32_t max_frames);

/* [RT] Commands, applied by the caller at a period boundary. */
void sx_clock_run(sx_clock *c);
void sx_clock_halt(sx_clock *c);
void sx_clock_step(sx_clock *c);                         /* queue one STEP (meaningful in SINGLE) */
int sx_clock_set_divisor(sx_clock *c, uint32_t divisor); /* 0 = SINGLE; -1 if out of range */
int sx_clock_set_speed(sx_clock *c, uint32_t position);  /* -1 if not a position */
void sx_clock_rebase(sx_clock *c); /* after a reset of the CPU's time (HOME) */

/* [RT] Run one period of `frames`: the CPU advances to the period's end (or executes the
 * pending STEPs in SINGLE). The period's writes are in c->ev[0 .. c->ev_n). Returns the
 * cycles the CPU advanced. */
uint64_t sx_clock_period(sx_clock *c, uint32_t frames);

/* The frame (since init) on which a write at emulated `cycle` takes effect, at the current
 * speed mapping. */
uint64_t sx_clock_frame_of(const sx_clock *c, uint64_t cycle);

#endif
