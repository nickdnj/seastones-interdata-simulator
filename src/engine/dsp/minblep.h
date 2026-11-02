/* minblep.h: the VCO's band-limiting kernels (VS-30, ADR-010); generated data in
 * minblep_tables.c (tools/dsp/gen-minblep.py). Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SX_MINBLEP_H
#define SX_MINBLEP_H

#define SX_BLEP_SPAN 32   /* output samples the residual lasts: the ring length */
#define SX_BLEP_PHASES 64 /* sub-sample positions per output sample */
#define SX_BLEP_ROWS (SX_BLEP_SPAN + 1)
#define SX_BLEP_COLS (SX_BLEP_PHASES + 1)

/* value at x = k + j/64 samples after a unit step (minBLEP) or unit slope change (minBLAMP) */
extern const float sx_minblep[SX_BLEP_ROWS][SX_BLEP_COLS];
extern const float sx_minblamp[SX_BLEP_ROWS][SX_BLEP_COLS];
extern const float sx_minblamp_tail; /* the minBLAMP residual's final value (-centroid) */

#endif
