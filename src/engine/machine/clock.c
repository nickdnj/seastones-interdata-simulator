/* clock.c: the emulated clock driven by the audio sample count (VS-02; see clock.h).
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "clock.h"

#include "cycles.h"
#include "id_seastones.h"
#include "scp_shim.h"

static const uint32_t speed_div[SX_SPEED_NPOS] = {1u, 10u, 100u, 1000u, 10000u, 0u};

/* The engine is single-instance (SIMH globals), so the device callback finds its clock here. */
static sx_clock *active;

/* Cycles per frame at the current speed is P / Q, a reduced fraction:
 * 1e9 / (rate * cycle_ns * divisor) = P / Q with P = 1e9 / g and Q = rate * cycle_ns * div / g. */
static uint64_t frac_p, frac_q;

uint32_t sx_speed_divisor(uint32_t position)
{
    return position < SX_SPEED_NPOS ? speed_div[position] : UINT32_MAX;
}

static uint64_t gcd64(uint64_t a, uint64_t b)
{
    while (b) {
        uint64_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

static void set_fraction(const sx_clock *c)
{
    uint64_t den = (uint64_t)c->rate * c->cycle_ns * (c->divisor ? c->divisor : 1u);
    uint64_t g = gcd64(1000000000u, den);
    frac_p = 1000000000u / g;
    frac_q = den / g;
}

uint64_t sx_clock_frame_of(const sx_clock *c, uint64_t cycle)
{
    if (c->divisor == 0 || !c->running)
        return c->frame; /* SINGLE or halted: the write lands at the start of the period */
    if (cycle <= c->base_cycle)
        return c->base_frame;
    /* frames = floor((cycle - base) * Q / P), split so it cannot overflow */
    uint64_t d = cycle - c->base_cycle;
    uint64_t q = d / frac_p, r = d % frac_p;
    return c->base_frame + q * frac_q + (r * frac_q) / frac_p;
}

static void on_write(uint32 dev, uint32 ch, uint32 val, uint32 t32)
{
    (void)t32; /* SCP's 32-bit time wraps after ~18 minutes of emulated time: use 64 bits */
    sx_clock *c = active;
    if (c == NULL)
        return;
    uint64_t now = sx_shim_now64();
    if (c->sink)
        c->sink(c->sink_ctx, now, (uint8_t)dev, (uint8_t)ch, (uint16_t)val);
    if (c->ev_n >= c->ev_cap) {
        c->ev_lost++;
        return;
    }
    uint64_t f = sx_clock_frame_of(c, now);
    uint64_t off = f > c->frame ? f - c->frame : 0u;
    uint32_t last = c->period_frames ? c->period_frames - 1u : 0u;
    sx_dev_ev *e = &c->ev[c->ev_n++];
    e->frame = off > last ? last : (uint32_t)off; /* an instruction that ends past the period */
    e->dev = (uint8_t)dev;
    e->ch = (uint8_t)ch;
    e->val = (uint16_t)val;
}

void sx_clock_rebase(sx_clock *c)
{
    /* Called only at period boundaries, where the CPU has reached its target (now >= target)
     * or is stopped, or after its time was reset (HOME, now < target). Either way the new
     * origin is "now": a halt or a slow stretch is never caught up in a burst. */
    c->target = sx_shim_now64();
    c->base_cycle = c->target;
    c->base_frame = c->frame;
    c->acc = 0;
    set_fraction(c);
}

void sx_clock_init(sx_clock *c, uint32_t rate, uint32_t cycle_ns, sx_dev_ev *ev, uint32_t ev_cap)
{
    *c = (sx_clock){0};
    c->rate = rate ? rate : 48000u;
    c->cycle_ns = cycle_ns ? cycle_ns : 250u;
    c->divisor = 1u;
    c->ev = ev;
    c->ev_cap = ev ? ev_cap : 0u;
    sx_cycles_configure(c->cycle_ns);
    active = c;
    sx_dev_event = &on_write;
    sx_clock_rebase(c);
}

uint32_t sx_clock_ev_capacity(uint32_t rate, uint32_t cycle_ns, uint32_t max_frames)
{
    uint32_t cheapest = UINT32_MAX;
    for (uint32_t op = 0; op < 256; op++)
        if (sx_cyc_table[op].base_ns && sx_cyc_table[op].base_ns < cheapest)
            cheapest = sx_cyc_table[op].base_ns;
    if (rate == 0 || cycle_ns == 0 || cheapest == UINT32_MAX)
        return 0;
    uint64_t ns = (uint64_t)max_frames * 1000000000u / rate + 1u;
    return (uint32_t)(ns / cheapest + 64u); /* + the overshoot of the period's last writes */
}

void sx_clock_run(sx_clock *c)
{
    if (!c->running) {
        c->running = 1;
        c->stop = 0;
        sx_clock_rebase(c);
    }
}

void sx_clock_halt(sx_clock *c)
{
    c->running = 0;
    c->steps = 0;
}

void sx_clock_step(sx_clock *c)
{
    if (c->steps < UINT32_MAX)
        c->steps++;
}

int sx_clock_set_divisor(sx_clock *c, uint32_t divisor)
{
    if (divisor > SX_SPEED_MAX_DIVISOR)
        return -1;
    c->divisor = divisor;
    c->steps = 0;
    sx_clock_rebase(c);
    return 0;
}

int sx_clock_set_speed(sx_clock *c, uint32_t position)
{
    if (position >= SX_SPEED_NPOS)
        return -1;
    return sx_clock_set_divisor(c, speed_div[position]);
}

static void cpu_stopped(sx_clock *c, t_stat r)
{
    if (r != SCPE_STEP && r != SCPE_OK) {
        c->running = 0; /* HALT instruction, trap with stops enabled, internal error */
        c->stop = (int32_t)r;
    }
}

uint64_t sx_clock_period(sx_clock *c, uint32_t frames)
{
    uint64_t start = sx_shim_now64();
    c->ev_n = 0;
    c->period_frames = frames;
    active = c;
    if (c->running && c->divisor == 0) {
        while (c->running && c->steps) { /* SINGLE: one instruction per STEP, stamped frame 0 */
            c->steps--;
            t_stat r = sx_shim_run(1);
            c->instructions++;
            cpu_stopped(c, r);
        }
        c->target = sx_shim_now64();
    } else if (c->running) {
        c->acc += (uint64_t)frames * frac_p;
        c->target += c->acc / frac_q;
        c->acc %= frac_q;
        uint64_t now;
        while (c->running && (now = sx_shim_now64()) < c->target) {
            uint64_t want = c->target - now;
            cpu_stopped(c, sx_shim_run((int32)(want > INT32_MAX ? INT32_MAX : want)));
        }
    }
    c->frame += frames;
    if (c->running && c->divisor && c->acc == 0) {
        c->base_cycle = c->target; /* an exact point: rebase so the products stay small */
        c->base_frame = c->frame;
    }
    return sx_shim_now64() - start;
}
