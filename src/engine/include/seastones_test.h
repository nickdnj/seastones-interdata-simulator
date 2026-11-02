/* seastones_test.h: the TEST profile's hooks (VS-27, QA requests 3 and 4; VS-26, QA request 1).
 *
 * These exist only when the engine is built with SX_PROFILE=test (the default for development
 * and CI): -DSX_TEST_HOOKS. The production profile (SX_PROFILE=production) compiles none of them
 * in, so a production binary has no sx_test_* symbol and no research-only feature; the release
 * gate checks for the string "SEASTONES_PROFILE=production" in the binary and for the absence of
 * these symbols. Hosts must not call them unless sx_profile() returns "test".
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SEASTONES_TEST_H
#define SEASTONES_TEST_H

#include "seastones.h"

#ifdef __cplusplus
extern "C" {
#endif

/* One D/A or gate write as the DSP received it, with its absolute frame (VS-26 traces). */
typedef struct sx_trace_ev {
    uint64_t frame;
    uint8_t dev; /* 0x21 DAC, 0x22 GATE */
    uint8_t ch;
    uint16_t val;
} sx_trace_ev;

typedef void (*sx_event_tap)(void *ctx, const sx_trace_ev *ev);

enum sx_inject { SX_INJECT_NAN = 1, SX_INJECT_INF = 2 };

/* Fault injection (DSP-20, FLT-10): the next period's voice output carries a NaN or an Inf. */
void sx_test_inject(sx_engine *e, uint32_t what); /* [any thread] */

/* Every write the DSP applies, as it applies it (the devices-to-DSP seam, ARCHITECTURE 12.1).
 * Called on the render thread: record into memory only. */
void sx_test_set_event_tap(sx_engine *e, sx_event_tap tap, void *ctx); /* [non-RT] */

/* Replay mode (VS-26): the CPU does not run; the trace's writes are applied to the DSP at their
 * frames through the same seam. The array must stay valid while replaying; NULL ends it. */
void sx_test_replay(sx_engine *e, const sx_trace_ev *trace, uint32_t n); /* [non-RT] */

#ifdef __cplusplus
}
#endif

#endif /* SEASTONES_TEST_H */
