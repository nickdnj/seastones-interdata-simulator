/* vcf.h: the voltage-controlled filter (PM-02; ARCHITECTURE 6.2 `vcf`; QA DSP-04, DSP-12).
 *
 *   lp  4-pole ladder, zero-delay feedback (topology-preserving transform), the input stage
 *       saturating through a fixed rational tanh, 2x oversampled
 *   hp, bp  2-pole state-variable filter (TPT), at the same oversampled rate
 *
 * The 2x up- and down-sampling is an 8-tap polyphase halfband (windowed sinc, flat to 0.02 dB at
 * 6 kHz and 0.2 dB at 16 kHz, both ways together), at the cost of SX_VCF_DELAY samples of
 * latency through the filter.
 *
 * Cutoff is 1 V/oct: fc = 16.352 Hz x 2^V (0 V is C0, as for the VCO), clamped to 20 Hz ..
 * 20 kHz. The ladder's pole frequency is fc; four identical poles put the low-pass's -3 dB point
 * at 0.435 fc (sqrt(2^(1/4) - 1)), which is what DSP-04's "1 V/oct prediction" compares against.
 * Resonance 0..1 sets the ladder feedback k = 3.6 x res, clamped below the linear ladder's
 * runaway limit of 4 (AUDIO-2), so the filter rings but never sustains oscillation on its own.
 * The SVF's damping is 2 - 1.9 res (Q from 0.5 to 10).
 *
 * Coefficients come from sx_sin_cycles (no libm) and are recomputed only when the cutoff
 * changes. Real-time safe. Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SX_VCF_H
#define SX_VCF_H

#include <stdint.h>

#define SX_VCF_F0_HZ 16.351597831287414
#define SX_VCF_FMIN_HZ 20.0
#define SX_VCF_FMAX_HZ 20000.0
#define SX_VCF_KMAX 3.6
#define SX_VCF_DELAY 7u /* samples, through the halfband up and down */
#define SX_VCF_HB 8u

typedef struct sx_vcf {
    double fs2;                 /* the oversampled rate */
    double volts, res;          /* as last applied */
    double g, G, k;             /* ladder: tan(pi fc / fs2), g / (1 + g), feedback */
    double s[4];                /* ladder stage states */
    double R2, h;               /* SVF: damping, 1 / (1 + R2 g + g^2) */
    double s1, s2;              /* SVF states */
    double xh[SX_VCF_HB];       /* input history, for the upsampler */
    double yh[3][2][SX_VCF_HB]; /* lp, hp, bp at the 2x rate: even and odd phases */
    uint32_t pos;
    double drive;
} sx_vcf;

void sx_vcf_init(sx_vcf *f, double fs);
void sx_vcf_reset(sx_vcf *f);
void sx_vcf_set(sx_vcf *f, double cutoff_volts, double res); /* [RT] */
double sx_vcf_hz(double cutoff_volts);                       /* the clamped pole frequency */

/* [RT] n samples; any output may be NULL (not computed: lp alone skips the SVF, and so on). */
void sx_vcf_render(sx_vcf *f, uint32_t n, const float *in, float *lp, float *hp, float *bp);
/* [RT] one sample, cutoff and resonance per sample (the graph's modulated path) */
void sx_vcf_tick(sx_vcf *f, double x, int want_lp, int want_svf, float *lp, float *hp, float *bp);

double sx_sat(double x); /* the fixed rational tanh: x (27 + x^2) / (27 + 9 x^2), +/-1 beyond 3 */

#endif
