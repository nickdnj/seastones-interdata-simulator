/* spectrum.h: test-only spectral analysis (DSP-08 as ADR-010 specifies it). Header-only, so each
 * test that needs it includes it. Not engine code: it may use libm.
 * Copyright (c) 2026 Nick D. MIT licence. */
#ifndef SX_TEST_SPECTRUM_H
#define SX_TEST_SPECTRUM_H

#include <math.h>
#include <stdint.h>

#define SPEC_MAXN 65536
#define SPEC_PI 3.14159265358979323846

static double spec_re[SPEC_MAXN], spec_im[SPEC_MAXN], spec_mag[SPEC_MAXN / 2 + 1];

static void spec_fft(double *re, double *im, uint32_t n)
{
    for (uint32_t i = 1, j = 0; i < n; i++) {
        uint32_t bit = n >> 1;
        for (; j & bit; bit >>= 1)
            j ^= bit;
        j ^= bit;
        if (i < j) {
            double t = re[i];
            re[i] = re[j];
            re[j] = t;
            t = im[i];
            im[i] = im[j];
            im[j] = t;
        }
    }
    for (uint32_t len = 2; len <= n; len <<= 1) {
        double ang = -2.0 * SPEC_PI / (double)len;
        for (uint32_t i = 0; i < n; i += len) {
            for (uint32_t k = 0; k < len / 2; k++) {
                double wr = cos(ang * (double)k), wi = sin(ang * (double)k);
                double ur = re[i + k], ui = im[i + k];
                double vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi;
                double vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
                re[i + k] = ur + vr;
                im[i + k] = ui + vi;
                re[i + k + len / 2] = ur - vr;
                im[i + k + len / 2] = ui - vi;
            }
        }
    }
}

/* 4-term Blackman-Harris window, then |X| for bins 0..n/2. */
static void spec_mag_of(const float *x, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        double t = 2.0 * SPEC_PI * (double)i / (double)(n - 1);
        double w = 0.35875 - 0.48829 * cos(t) + 0.14128 * cos(2 * t) - 0.01168 * cos(3 * t);
        spec_re[i] = (double)x[i] * w;
        spec_im[i] = 0.0;
    }
    spec_fft(spec_re, spec_im, n);
    for (uint32_t k = 0; k <= n / 2; k++)
        spec_mag[k] = sqrt(spec_re[k] * spec_re[k] + spec_im[k] * spec_im[k]);
}

/* The DSP-08 value: highest unmasked bin between 20 Hz and 20 kHz in dBc. DC and every harmonic
 * k x f below fs/2 are masked +/- 8 bins; for a sweep, harmonic k is masked from k x f_lo to
 * k x f_hi. The reference is the fundamental's peak. */
static double spec_residual_band(uint32_t n, double fs, double f_lo, double f_hi, double band_lo,
                                 double band_hi);

static double spec_residual_dbc(uint32_t n, double fs, double f_lo, double f_hi)
{
    return spec_residual_band(n, fs, f_lo, f_hi, 20.0, 20000.0);
}

/* The same over another band (the self-check reproduces a 0 to fs/2 measurement). */
static double spec_residual_band(uint32_t n, double fs, double f_lo, double f_hi, double band_lo,
                                 double band_hi)
{
    static uint8_t mask[SPEC_MAXN / 2 + 1];
    double bin = fs / (double)n;
    uint32_t half = n / 2;
    for (uint32_t k = 0; k <= half; k++)
        mask[k] = k <= 8;
    double ref = 0.0;
    for (uint32_t h = 1; h * f_lo < fs / 2; h++) {
        long a = (long)floor((double)h * f_lo / bin) - 8,
             b = (long)ceil((double)h * f_hi / bin) + 8;
        for (long k = a < 0 ? 0 : a; k <= b && k <= (long)half; k++) {
            mask[k] = 1;
            if (h == 1 && spec_mag[k] > ref)
                ref = spec_mag[k];
        }
    }
    double worst = 0.0;
    uint32_t lo = (uint32_t)ceil(band_lo / bin), hi = (uint32_t)floor(band_hi / bin);
    for (uint32_t k = lo; k <= hi && k <= half; k++)
        if (!mask[k] && spec_mag[k] > worst)
            worst = spec_mag[k];
    if (ref <= 0.0)
        return 0.0;
    return worst > 0.0 ? 20.0 * log10(worst / ref) : -400.0;
}

#endif
