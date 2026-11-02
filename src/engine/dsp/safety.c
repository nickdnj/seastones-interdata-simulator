/* safety.c: the output safety chain (VS-11; see safety.h). Copyright (c) 2026 Nick D. MIT licence.
 */
#include "safety.h"

#include "sx_math.h"

#define LN2 0.69314718055994531
#define TWO_PI 6.283185307179586
#define LOG2_10_OVER_20 0.16609640474436813 /* log2(10) / 20 */
#define KNEE 0.70794578438413791            /* -3 dBFS */
#define RELEASE_S 0.05
#define TINY 1e-30

double sx_db_to_lin(double db)
{
    return sx_exp2(db * LOG2_10_OVER_20);
}

static double tanh_pos(double u) /* tanh for u >= 0, no libm */
{
    if (u > 20.0)
        return 1.0;
    double e = sx_exp2(2.0 * u / LN2);
    return 1.0 - 2.0 / (e + 1.0);
}

double sx_softclip(double x)
{
    double a = x < 0.0 ? -x : x;
    if (a <= KNEE)
        return x;
    double y = KNEE + (1.0 - KNEE) * tanh_pos((a - KNEE) / (1.0 - KNEE));
    return x < 0.0 ? -y : y;
}

void sx_biquad_hpf(sx_biquad *b, double fs, double fc)
{
    double p = fc / fs;
    double sn = sx_sin_cycles(p), cs = sx_sin_cycles(p + 0.25);
    double alpha = sn / (2.0 * 0.70710678118654752); /* Q = 1/sqrt 2: Butterworth */
    double a0 = 1.0 + alpha;
    b->b0 = (1.0 + cs) / 2.0 / a0;
    b->b1 = -(1.0 + cs) / a0;
    b->b2 = b->b0;
    b->a1 = -2.0 * cs / a0;
    b->a2 = (1.0 - alpha) / a0;
    b->x1 = b->x2 = b->y1 = b->y2 = 0.0;
}

static double flush(double v)
{
    return (v < TINY && v > -TINY) ? 0.0 : v;
}

double sx_biquad_run(sx_biquad *b, double x)
{
    double y = b->b0 * x + b->b1 * b->x1 + b->b2 * b->x2 - b->a1 * b->y1 - b->a2 * b->y2;
    b->x2 = b->x1;
    b->x1 = x;
    b->y2 = b->y1;
    b->y1 = flush(y);
    return y;
}

static void make_fir(sx_safety *s);

static void reset_filters(sx_safety *s)
{
    s->dc_x1 = s->dc_y1 = 0.0;
    s->hpf.x1 = s->hpf.x2 = s->hpf.y1 = s->hpf.y2 = 0.0;
}

void sx_safety_init(sx_safety *s, double fs)
{
    s->fs = fs > 0.0 ? fs : 48000.0;
    s->dc_r = sx_exp2(-TWO_PI * 5.0 / s->fs / LN2);
    sx_biquad_hpf(&s->hpf, s->fs, 25.0);
    reset_filters(s);
    for (uint32_t i = 0; i < SX_SAFETY_LOOKAHEAD; i++)
        s->delay[i] = 0.0f;
    for (uint32_t i = 0; i < SX_LIM_W; i++) {
        s->hold[i] = 1.0f;
        s->box[i] = 1.0;
    }
    for (uint32_t i = 0; i <= SX_TP_TAPS; i++)
        s->hist[i] = 0.0;
    make_fir(s);
    s->wpos = 0;
    s->gain = 1.0;
    s->rel = sx_exp2(-1.0 / (RELEASE_S * s->fs) / LN2);
    s->pos = 0;
    s->volume = 1.0;
    sx_safety_set_ceiling(s, SX_HARD_MAX_DBFS, SX_HARD_MAX_DBFS);
    s->out_gain = 0.0;
    s->mute_step = 1.0 / (SX_MUTE_RAMP_S * s->fs);
    s->fade_step = 1.0 / (SX_FADE_IN_S * s->fs);
    s->muted = 1; /* silent until the device is open */
    s->nonfinite = 0;
}

void sx_safety_clear(sx_safety *s)
{
    reset_filters(s);
    for (uint32_t i = 0; i < SX_SAFETY_LOOKAHEAD; i++)
        s->delay[i] = 0.0f;
    for (uint32_t i = 0; i < SX_LIM_W; i++) {
        s->hold[i] = 1.0f;
        s->box[i] = 1.0;
    }
    for (uint32_t i = 0; i <= SX_TP_TAPS; i++)
        s->hist[i] = 0.0;
    s->gain = 1.0;
    s->out_gain = 0.0; /* the 200 ms fade-in starts again */
}

void sx_safety_start(sx_safety *s)
{
    s->muted = 0;
}

void sx_safety_set_ceiling(sx_safety *s, double staff_dbfs, double quiet_dbfs)
{
    s->staff_dbfs = staff_dbfs;
    s->quiet_dbfs = quiet_dbfs;
    double c = SX_HARD_MAX_DBFS;
    if (staff_dbfs == staff_dbfs && staff_dbfs < c)
        c = staff_dbfs;
    if (quiet_dbfs == quiet_dbfs && quiet_dbfs < c)
        c = quiet_dbfs;
    s->ceiling = sx_db_to_lin(c);
    s->detect = sx_db_to_lin(c - 0.05); /* detection margin for the interpolator's error */
}

double sx_safety_ceiling_dbfs(const sx_safety *s)
{
    double c = SX_HARD_MAX_DBFS;
    if (s->staff_dbfs < c)
        c = s->staff_dbfs;
    if (s->quiet_dbfs < c)
        c = s->quiet_dbfs;
    return c;
}

void sx_safety_set_volume(sx_safety *s, double db)
{
    s->volume = db >= 0.0 || !(db == db) ? 1.0 : sx_db_to_lin(db);
}

void sx_safety_mute(sx_safety *s, int on)
{
    s->muted = on != 0;
}

/* The 8x interpolator: value at m + p/8 from x[m-15 .. m+16], Hann-windowed sinc over +/-17.
 * (PM-08: 4x with 16 taps under-read alias-rich patches by up to 5 dB near Nyquist.) */
static void make_fir(sx_safety *s)
{
    const int half = (int)SX_TP_DELAY - 1; /* 15: taps before m */
    for (int p = 1; p < (int)SX_TP_OS; p++) {
        double sum = 0.0;
        for (int k = 0; k < (int)SX_TP_TAPS; k++) {
            double u = (double)p / (double)SX_TP_OS - (double)(k - half); /* to x[m-15+k] */
            double sinc = sx_sin_cycles(u / 2.0) / (3.14159265358979323846 * u);
            double w = 0.5 + 0.5 * sx_sin_cycles(u / 34.0 + 0.25); /* Hann over +/- 17 */
            s->fir[p - 1][k] = sinc * w;
            sum += sinc * w;
        }
        for (int k = 0; k < (int)SX_TP_TAPS; k++)
            s->fir[p - 1][k] /= sum; /* unit DC gain */
    }
}

/* Peak of sample x[n-16] and the interpolated eighth points on both sides of it. hist[32] is
 * the newest sample x[n], hist[0] is x[n-32]. */
static double peak_tp(const sx_safety *s)
{
    double c = s->hist[SX_TP_TAPS - SX_TP_DELAY];
    double pk = c < 0 ? -c : c;
    for (int side = 0; side < 2; side++) { /* segment [n-17, n-16], then [n-16, n-15] */
        const double *x = s->hist + side;  /* x[m-15] for m = n-17+side */
        for (int p = 0; p < (int)SX_TP_OS - 1; p++) {
            double v = 0.0;
            for (uint32_t k = 0; k < SX_TP_TAPS; k++)
                v += s->fir[p][k] * x[k];
            v = v < 0 ? -v : v;
            pk = v > pk ? v : pk;
        }
    }
    return pk;
}

void sx_safety_process(sx_safety *s, float *buf, uint32_t n)
{
    const uint32_t L = SX_SAFETY_LOOKAHEAD;
    for (uint32_t i = 0; i < n; i++) {
        double x = (double)buf[i];
        if (!(x - x == 0.0)) { /* NaN or Inf */
            s->nonfinite++;
            reset_filters(s);
            x = 0.0;
        }
        /* DC blocker, then the 25 Hz high-pass */
        double d = x - s->dc_x1 + s->dc_r * s->dc_y1;
        s->dc_x1 = x;
        s->dc_y1 = flush(d);
        x = sx_biquad_run(&s->hpf, d);
        x = sx_softclip(x);

        /* limiter: the required gain for sample x[n-8] and its neighbourhood */
        for (uint32_t k = 0; k < SX_TP_TAPS; k++)
            s->hist[k] = s->hist[k + 1u];
        s->hist[SX_TP_TAPS] = x;
        double pk = peak_tp(s);
        float req = pk > s->detect ? (float)(s->detect / pk) : 1.0f;
        s->delay[s->pos] = (float)x;
        s->hold[s->wpos] = req;
        double h = 1.0;
        for (uint32_t k = 0; k < SX_LIM_W; k++)
            h = s->hold[k] < h ? s->hold[k] : h;
        s->box[s->wpos] = h;
        s->wpos = (s->wpos + 1u) % SX_LIM_W;
        double sum = 0.0;
        for (uint32_t k = 0; k < SX_LIM_W; k++)
            sum += s->box[k];
        double m = sum / (double)SX_LIM_W;
        s->gain = m < s->gain ? m : m + (s->gain - m) * s->rel;
        if (s->gain > m)
            s->gain = m;                 /* never above the box average: the guarantee */
        uint32_t rd = (s->pos + 1u) % L; /* written L - 1 samples ago */
        s->pos = rd;
        double y = (double)s->delay[rd] * s->gain;
        if (y > s->ceiling) /* rounding only: the gain already bounds it */
            y = s->ceiling;
        if (y < -s->ceiling)
            y = -s->ceiling;

        /* visitor volume, then mute ramp or fade-in */
        y *= s->volume;
        if (s->muted)
            s->out_gain = s->out_gain > s->mute_step ? s->out_gain - s->mute_step : 0.0;
        else if (s->out_gain < 1.0)
            s->out_gain = s->out_gain + s->fade_step < 1.0 ? s->out_gain + s->fade_step : 1.0;
        buf[i] = (float)(y * s->out_gain);
    }
}
