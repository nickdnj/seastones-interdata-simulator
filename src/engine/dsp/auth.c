/* auth.c: strobed and research-only jitter re-timing of D/A writes (PM-07; see auth.h).
 * Copyright (c) 2026 Nick D. MIT licence. */
#include "auth.h"

#include "mods.h"

#define DEV_DAC 0x21u

static uint64_t strobe_frame(const sx_authst *a, uint64_t k)
{
    return (uint64_t)((double)k * (double)a->rate / a->strobe_hz);
}

void sx_auth_init(sx_authst *a, uint32_t rate, double strobe_hz, double jitter_ms)
{
    a->mode = SX_AUTH_AUTHENTIC;
    a->rate = rate ? rate : 48000u;
    a->strobe_hz = strobe_hz > 1.0 ? strobe_hz : 1000.0;
    if (a->strobe_hz > (double)a->rate)
        a->strobe_hz = (double)a->rate;
    a->strobe_k = 0;
    a->next_strobe = 0;
    a->held_mask = 0;
#if !defined(SX_PROFILE_PRODUCTION)
    a->jitter_frames = (jitter_ms > 0.0 ? jitter_ms : 1.0) * (double)a->rate / 1000.0;
    a->rng = 0x5EA570E5u;
    a->qn = a->lost = 0;
    for (int i = 0; i < 17; i++)
        a->last[i] = 0;
#else
    (void)jitter_ms;
#endif
}

void sx_auth_set_mode(sx_authst *a, uint32_t mode, uint64_t now)
{
    a->mode = mode;
    a->held_mask = 0;
    /* the strobe clock free-runs from frame 0: find the first strobe at or after now */
    uint64_t k = (uint64_t)((double)now * a->strobe_hz / (double)a->rate);
    while (strobe_frame(a, k) < now)
        k++;
    a->strobe_k = k;
    a->next_strobe = strobe_frame(a, k);
#if !defined(SX_PROFILE_PRODUCTION)
    a->qn = 0;
#endif
}

static uint32_t put(sx_dev_ev *out, uint32_t no, uint32_t cap, uint64_t f, uint64_t frame0,
                    uint8_t dev, uint8_t ch, uint16_t val)
{
    if (no < cap)
        out[no++] = (sx_dev_ev){(uint32_t)(f - frame0), dev, ch, val};
    return no;
}

static uint32_t strobed(sx_authst *a, const sx_dev_ev *in, uint32_t nin, uint64_t frame0,
                        uint32_t n, sx_dev_ev *out, uint32_t cap)
{
    uint32_t i = 0, no = 0;
    uint64_t end = frame0 + n;
    while (a->next_strobe < end) {
        uint64_t s = a->next_strobe;
        for (; i < nin && frame0 + in[i].frame <= s; i++) {
            if (in[i].dev == DEV_DAC && in[i].ch < 16u) {
                a->held[in[i].ch] = in[i].val;
                a->held_mask |= 1u << in[i].ch;
            } else {
                no =
                    put(out, no, cap, frame0 + in[i].frame, frame0, in[i].dev, in[i].ch, in[i].val);
            }
        }
        for (uint32_t ch = 0; ch < 16u; ch++)
            if (a->held_mask & (1u << ch))
                no = put(out, no, cap, s, frame0, DEV_DAC, (uint8_t)ch, a->held[ch]);
        a->held_mask = 0;
        a->next_strobe = strobe_frame(a, ++a->strobe_k);
    }
    for (; i < nin; i++) { /* after the period's last strobe: held until the next */
        if (in[i].dev == DEV_DAC && in[i].ch < 16u) {
            a->held[in[i].ch] = in[i].val;
            a->held_mask |= 1u << in[i].ch;
        } else {
            no = put(out, no, cap, frame0 + in[i].frame, frame0, in[i].dev, in[i].ch, in[i].val);
        }
    }
    return no;
}

#if !defined(SX_PROFILE_PRODUCTION)
static double sx_auth_jitter_gauss(sx_authst *a) /* Irwin-Hall: 4 uniforms, unit variance */
{
    double s = 0.0;
    for (int k = 0; k < 4; k++)
        s += (double)sx_xorshift32(&a->rng) / 4294967296.0 - 0.5;
    return s * 1.7320508075688772; /* sqrt(12 / 4) */
}

static uint32_t sx_auth_jitter_run(sx_authst *a, const sx_dev_ev *in, uint32_t nin, uint64_t frame0,
                                   uint32_t n, sx_dev_ev *out, uint32_t cap)
{
    double sig = a->jitter_frames;
    for (uint32_t i = 0; i < nin; i++) {
        double d = 3.0 * sig + sig * sx_auth_jitter_gauss(a);
        if (d < 0.0)
            d = 0.0;
        if (d > 6.0 * sig)
            d = 6.0 * sig;
        uint64_t f = frame0 + in[i].frame + (uint64_t)d;
        uint32_t lane = in[i].dev == DEV_DAC && in[i].ch < 16u ? in[i].ch : 16u;
        if (f < a->last[lane])
            f = a->last[lane]; /* a channel's writes keep their order */
        a->last[lane] = f;
        if (a->qn >= SX_AUTH_QUEUE) {
            a->lost++;
            continue;
        }
        uint32_t j = a->qn++; /* insert, stable, ordered by frame */
        while (j > 0 && a->q[j - 1].frame > f) {
            a->q[j] = a->q[j - 1];
            j--;
        }
        a->q[j] = (sx_auth_ev){f, in[i].dev, in[i].ch, in[i].val};
    }
    uint32_t take = 0, no = 0;
    while (take < a->qn && a->q[take].frame < frame0 + n) {
        uint64_t f = a->q[take].frame < frame0 ? frame0 : a->q[take].frame;
        no = put(out, no, cap, f, frame0, a->q[take].dev, a->q[take].ch, a->q[take].val);
        take++;
    }
    for (uint32_t j = take; j < a->qn; j++)
        a->q[j - take] = a->q[j];
    a->qn -= take;
    return no;
}
#endif

uint32_t sx_auth_process(sx_authst *a, const sx_dev_ev *in, uint32_t nin, uint64_t frame0,
                         uint32_t n, sx_dev_ev *out, uint32_t cap)
{
    if (a->mode == SX_AUTH_STROBED)
        return strobed(a, in, nin, frame0, n, out, cap);
#if !defined(SX_PROFILE_PRODUCTION)
    if (a->mode == SX_AUTH_JITTER)
        return sx_auth_jitter_run(a, in, nin, frame0, n, out, cap);
#endif
    uint32_t no = nin < cap ? nin : cap;
    for (uint32_t i = 0; i < no; i++)
        out[i] = in[i];
    return no;
}
