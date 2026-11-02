/* test_clock.c: unit tests for the emulated clock and cycle costs (VS-02; CNF-09, CNF-10,
 * CNF-11, DSP-14).
 *
 * The cycle table is an ESTIMATE (Model 74 proxy, SP-S4B): these tests check that the engine
 * charges what the table says, not that the table is right. Plain asserts, no framework.
 */
#include "clock.h"
#include "cycles.h"
#include "id_seastones.h"
#include "scp_shim.h"

#include <stdio.h>
#include <string.h>

extern UNIT cpu_unit;
extern DEVICE cpu_dev;
extern uint32 PC, PSW, GREG[16];

static int failures;
static int checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

#define RATE 48000u
#define PERIOD 128u
#define EVCAP 4096u

static sx_dev_ev evbuf[EVCAP];
static sx_clock clk;

static void load(const uint16 *w, uint32 n, uint32 at)
{
    for (uint32 i = 0; i < n; i++)
        cpu_dev.deposit(w[i], at + 2 * i, &cpu_unit, 0);
    PC = at;
    PSW = 0;
    for (int r = 0; r < 16; r++)
        GREG[r] = 0;
}

static void fresh(void)
{
    sx_clock_init(&clk, RATE, 250u, evbuf, EVCAP);
    sx_shim_reset_all();
    sx_clock_rebase(&clk);
}

/* ns of one execution, straight from the table rows (cycle-calc.py's model) */
static uint32_t ns_of(uint32_t op, int taken, uint32_t n)
{
    const sx_cyc_row *r = &sx_cyc_table[op];
    return (taken && r->taken_ns ? r->taken_ns : r->base_ns) + r->per_n_ns * n;
}

static void test_costs(void)
{
    CHECK(strcmp(sx_cycles_status, "ESTIMATE") == 0); /* the label travels with the table */
    CHECK(sx_cycles_rows == 113u);
    sx_cycles_configure(0); /* instruction mode: stock */
    CHECK(sx_cycles_cost(0x08, 1, 2, 0, 0) == 1u);
    CHECK(sx_cycles_cost(0x43, 0, 0, 0x100, 0) == 1u);
    CHECK(sx_cycles_cost(0xCD, 4, 0, 5, 0) == 1u);
    sx_cycles_configure(250u);
    CHECK(sx_cycles_cycle_ns() == 250u);
    CHECK(sx_cycles_cost(0x08, 1, 2, 0, 0) == 6u);                 /* LHR 1.5 us */
    CHECK(sx_cycles_cost(0x48, 1, 0, 0, 0) == 13u);                /* LH 3.25 us */
    CHECK(sx_cycles_cost(0x43, 0, 0, 0x100, 0xF) == 14u);          /* B (BFC 0): taken, 3.5 */
    CHECK(sx_cycles_cost(0x42, 0x8, 0, 0x100, 0x7) == 13u);        /* BTC not taken, 3.25 */
    CHECK(sx_cycles_cost(0x42, 0x8, 0, 0x100, 0x8) == 14u);        /* BTC taken */
    CHECK(sx_cycles_cost(0x21, 0x4, 3, 0, 0x4) == 15u);            /* BTFS taken, 3.75 */
    CHECK(sx_cycles_cost(0x23, 0x4, 3, 0, 0x4) == 9u);             /* BFFS not taken, 2.25 */
    CHECK(sx_cycles_cost(0xCD, 4, 0, 0x35, 0) == 17u + 5u * 5u);   /* SLHL n = opnd & F */
    CHECK(sx_cycles_cost(0xED, 4, 0, 0x35, 0) == 24u + 21u * 6u);  /* SLL n = opnd & 1F */
    CHECK(sx_cycles_cost(0x91, 4, 3, 3, 0) == 13u + 3u * 5u);      /* SLLS n = R2 */
    CHECK(sx_cycles_cost(0xD0, 14, 0, 0x200, 0) == 20u + 2u * 5u); /* STM R14: 2 registers */
    CHECK(sx_cycles_cost(0x00, 0, 0, 0, 0) == 1u); /* not in the table: the trap costs 1 */
    /* Every plain row costs round(base / 250 ns). All but the borrowed Model 70 floating-point
     * rows (outside the portable subset) are whole cycles already. */
    uint32_t fractional = 0;
    for (uint32_t op = 0; op < 256; op++) {
        const sx_cyc_row *r = &sx_cyc_table[op];
        if (r->base_ns == 0 || r->kind != SX_CK_PLAIN || r->per_n_ns)
            continue;
        CHECK(sx_cycles_cost(op, 0, 0, 0, 0) == (r->base_ns + 125u) / 250u);
        fractional += r->base_ns % 250u != 0;
    }
    CHECK(fractional == 4u); /* AE SE ME DE */
}

/* VS-02 AC 1: a known loop's iteration count over 1 s of emulated audio equals the
 * cycle-table calculation within 1 percent. */
static void test_loop_over_one_second(void)
{
    /* X'100' AIS R1,1 / MHR R2,R3 / SLHL R4,5 / BTFS 0,+1 (never taken) / B X'100' */
    const uint16 prog[] = {0x2611, 0x0C23, 0xCD40, 0x0005, 0x2101, 0x4300, 0x0100};
    fresh();
    load(prog, 7, 0x100);
    sx_clock_run(&clk);
    for (uint32_t f = 0; f < RATE; f += PERIOD)
        sx_clock_period(&clk, f + PERIOD <= RATE ? PERIOD : RATE - f);
    uint32_t iter_ns = ns_of(0x26, 0, 0) + ns_of(0x0C, 0, 0) + ns_of(0xCD, 0, 5) +
                       ns_of(0x21, 0, 0) + ns_of(0x43, 1, 0);
    double expect = 1e9 / (double)iter_ns;
    double got = (double)GREG[1];
    printf("loop: %u ns per iteration (ESTIMATE), expected %.1f, counted %.0f in 1 s\n", iter_ns,
           expect, got);
    CHECK(iter_ns == 61750u);
    CHECK(got > expect * 0.99 && got < expect * 1.01);
    CHECK(clk.frame == RATE);
    CHECK(clk.target == 4000000u); /* exactly 1 s of 250 ns cycles */
    CHECK(sx_shim_now64() >= clk.target && sx_shim_now64() < clk.target + 200u);
}

/* SINGLE: exactly one instruction per STEP, whatever its cost. */
static void test_single_and_halt(void)
{
    const uint16 prog[] = {0x2611, 0x0C23, 0xCD40, 0x0005, 0x2101, 0x4300, 0x0100};
    fresh();
    load(prog, 7, 0x100);
    sx_clock_set_speed(&clk, SX_SPEED_SINGLE);
    sx_clock_run(&clk);
    CHECK(sx_clock_period(&clk, PERIOD) == 0u); /* no STEP: nothing runs */
    CHECK(PC == 0x100);
    sx_clock_step(&clk);
    sx_clock_period(&clk, PERIOD);
    CHECK(PC == 0x102 && GREG[1] == 1);
    sx_clock_step(&clk);
    sx_clock_step(&clk);
    sx_clock_period(&clk, PERIOD);
    CHECK(PC == 0x108 && clk.instructions == 3);
    for (int i = 0; i < 4; i++)
        sx_clock_step(&clk);
    sx_clock_period(&clk, PERIOD);
    CHECK(PC == 0x104 && GREG[1] == 2 && clk.instructions == 7); /* round the loop once */

    sx_clock_set_speed(&clk, SX_SPEED_RUN);
    sx_clock_period(&clk, PERIOD);
    uint32 r1 = GREG[1];
    CHECK(r1 > 2);
    sx_clock_halt(&clk);
    CHECK(sx_clock_period(&clk, PERIOD) == 0u && GREG[1] == r1);
    sx_clock_period(&clk, PERIOD * 10u);
    sx_clock_run(&clk); /* no catch-up burst after a halt */
    uint64_t adv = sx_clock_period(&clk, PERIOD);
    CHECK(adv >= 10666u && adv < 10666u + 200u); /* 128 frames = 10666.7 cycles */
    CHECK(sx_clock_set_speed(&clk, SX_SPEED_NPOS) == -1);
    CHECK(sx_clock_set_divisor(&clk, SX_SPEED_MAX_DIVISOR + 1u) == -1);
}

/* Speeds divide emulated time; a long run does not drift. */
static void test_speeds_and_drift(void)
{
    const uint16 prog[] = {0x2611, 0x4300, 0x0100}; /* AIS R1,1 / B X'100' */
    static const uint32_t pos[] = {SX_SPEED_RUN, SX_SPEED_SLOW1, SX_SPEED_SLOW2, SX_SPEED_SLOW3,
                                   SX_SPEED_CRAWL};
    for (uint32_t i = 0; i < 5; i++) {
        fresh();
        load(prog, 3, 0x100);
        CHECK(sx_clock_set_speed(&clk, pos[i]) == 0);
        sx_clock_run(&clk);
        for (uint32_t p = 0; p < RATE / PERIOD; p++) /* 1 s = 375 periods */
            sx_clock_period(&clk, PERIOD);
        CHECK(clk.target == 4000000u / sx_speed_divisor(pos[i]));
    }
    CHECK(sx_speed_divisor(SX_SPEED_SINGLE) == 0u && sx_speed_divisor(99) == UINT32_MAX);

    /* 1/3000 (VS-16 names it): 4e6 / 3000 = 1333.3 cycles per second */
    fresh();
    load(prog, 3, 0x100);
    sx_clock_set_divisor(&clk, 3000u);
    sx_clock_run(&clk);
    for (uint32_t p = 0; p < 3u * RATE / PERIOD; p++)
        sx_clock_period(&clk, PERIOD);
    CHECK(clk.target == 4000u);

    /* About 40 s at RUN in odd period sizes, which exercise the remainder: cycles are exactly
     * frames * 1e9 / (rate * cycle_ns), with no drift. */
    fresh();
    load(prog, 3, 0x100);
    sx_clock_run(&clk);
    uint64_t frames = 0;
    for (uint32_t p = 0; p < 20000; p++) {
        uint32_t n = 61u + (p % 7u) * 13u;
        sx_clock_period(&clk, n);
        frames += n;
    }
    CHECK(clk.target == frames * 1000000000u / (RATE * 250u));
}

/* D/A writes: stamped on the right frame, and identical over two runs (VS-02 AC 3). */
static uint32_t trace_f[20000], trace_v[20000];
static uint32_t ntrace;

static void record_run(void)
{
    /* X'100' LHI R11,X'21' / X'104' AIS R2,3 / WHR R11,R2 / MHR R4,R5 / B X'104' */
    const uint16 prog[] = {0xC8B0, 0x0021, 0x2623, 0x98B2, 0x0C45, 0x4300, 0x0104};
    fresh();
    load(prog, 7, 0x100);
    sx_clock_run(&clk);
    ntrace = 0;
    for (uint32_t p = 0; p < 150; p++) {
        uint64_t f0 = clk.frame;
        sx_clock_period(&clk, PERIOD);
        for (uint32_t i = 0; i < clk.ev_n && ntrace < 20000; i++) {
            CHECK(clk.ev[i].frame < PERIOD && clk.ev[i].dev == 0x21 && clk.ev[i].ch == 0);
            trace_f[ntrace] = (uint32_t)(f0 + clk.ev[i].frame);
            trace_v[ntrace++] = clk.ev[i].val;
        }
    }
    CHECK(clk.ev_lost == 0);
}

static void test_write_stamps_and_determinism(void)
{
    static uint32_t f1[20000], v1[20000];
    record_run();
    uint32_t n1 = ntrace;
    memcpy(f1, trace_f, sizeof f1);
    memcpy(v1, trace_v, sizeof v1);
    record_run();
    CHECK(n1 == ntrace && n1 > 1000);
    CHECK(memcmp(f1, trace_f, n1 * sizeof f1[0]) == 0);
    CHECK(memcmp(v1, trace_v, n1 * sizeof v1[0]) == 0);
    /* one write per 3.5 + 2.25 + 3.75 + 43.5 = 53.0 us loop: frames advance by 2 or 3 */
    for (uint32_t i = 1; i < n1; i++)
        CHECK(trace_f[i] - trace_f[i - 1] >= 2 && trace_f[i] - trace_f[i - 1] <= 3);
    /* at RUN, the stamp is the absolute mapping (ARCHITECTURE 5.2 timing, DEV-10) */
    CHECK(sx_clock_frame_of(&clk, 4000000u) == sx_cycle_to_frame(4000000u, 250u, RATE));
    for (uint64_t cyc = clk.base_cycle; cyc < clk.base_cycle + 1000u; cyc += 7)
        CHECK(sx_clock_frame_of(&clk, cyc) ==
              clk.base_frame + sx_cycle_to_frame(cyc - clk.base_cycle, 250u, RATE));
    CHECK(sx_clock_ev_capacity(RATE, 250u, PERIOD) >= 1778u); /* 2.67 ms / 1.5 us */
}

/* The wait state at any speed: the CPU idles to the period's end exactly (no overshoot), so
 * emulated time is exactly the frames rendered divided by the speed. */
static void test_wait_state(void)
{
    static const uint32_t divs[] = {1u, 10u, 1000u};
    const uint16 prog[] = {0x4300, 0x0100};
    for (uint32_t i = 0; i < 3; i++) {
        fresh();
        load(prog, 2, 0x100);
        PSW = 0x8000;
        sx_clock_set_divisor(&clk, divs[i]);
        sx_clock_run(&clk);
        for (uint32_t p = 0; p < RATE / PERIOD; p++) {
            sx_clock_period(&clk, PERIOD);
            CHECK(sx_shim_now64() == clk.target);
        }
        CHECK(clk.target == 4000000u / divs[i]);
        CHECK(PC == 0x100); /* still waiting */
    }
}

int main(void)
{
    test_costs();
    test_loop_over_one_second();
    test_single_and_halt();
    test_speeds_and_drift();
    test_write_stamps_and_determinism();
    test_wait_state();
    printf("test_clock: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
