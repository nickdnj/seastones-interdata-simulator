/* auth.h: authenticity modes that re-time D/A writes (PM-07; ARCHITECTURE 6.4; NFR-2, DSP-21).
 *
 *   authentic  each write reaches the synth at its own frame, unchanged (the default; the
 *              zipper and the loop's timing are the program's own)
 *   analog     the same frames; the graph smooths each D/A channel through the converter's
 *              output low-pass at dac.output_hz (graph.h), so nothing here
 *   strobed    a double-buffered board updated by a clock at dac.strobe_hz: D/A writes are held,
 *              and every channel written since the last strobe is transferred together at the
 *              next strobe frame (the first strobe at or after the write); only the last write
 *              to a channel survives. Gate-latch writes are digital and pass straight through.
 *   jitter     RESEARCH ONLY, compiled out of the production profile (VS-27): each write is
 *              delayed by 3 sigma + sigma x N(0, 1) frames (N from a seeded Irwin-Hall sum of
 *              four uniforms; clamped to 0 .. 6 sigma), keeping each channel's writes in order.
 *              For "is this zipper consistent with a jittery loop" tests, never the floor.
 *
 * Strobe frames are floor(k x rate / strobe_hz), k = 0, 1, 2 ... from engine start, so the
 * schedule does not depend on the period size. Real-time safe. Copyright (c) 2026 Nick D. MIT.
 */
#ifndef SX_AUTH_H
#define SX_AUTH_H

#include <stdint.h>

#include "clock.h"

#define SX_AUTH_QUEUE 4096u

typedef struct sx_auth_ev {
    uint64_t frame;
    uint8_t dev, ch;
    uint16_t val;
} sx_auth_ev;

typedef struct sx_authst {
    uint32_t mode; /* enum sx_auth */
    uint32_t rate;
    double strobe_hz;
    uint64_t strobe_k, next_strobe;
    uint16_t held[16];
    uint32_t held_mask;
#if !defined(SX_PROFILE_PRODUCTION)
    double jitter_frames; /* sigma */
    uint32_t rng;
    sx_auth_ev q[SX_AUTH_QUEUE];
    uint32_t qn, lost;
    uint64_t last[17]; /* per D/A channel and the gate latch: the last frame sent */
#endif
} sx_authst;

void sx_auth_init(sx_authst *a, uint32_t rate, double strobe_hz, double jitter_ms);
void sx_auth_set_mode(sx_authst *a, uint32_t mode, uint64_t frame_now); /* [RT] */

/* [RT] One period: `in` (frames relative to frame0, in order) becomes `out` (same form), at
 * most `cap` events. Authentic and analog copy. Returns the number written. */
uint32_t sx_auth_process(sx_authst *a, const sx_dev_ev *in, uint32_t nin, uint64_t frame0,
                         uint32_t n, sx_dev_ev *out, uint32_t cap);

#endif
