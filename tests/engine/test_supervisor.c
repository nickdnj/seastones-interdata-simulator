/* test_supervisor.c: the fail-silent supervisor (VS-16; PRG-08, FLT-03, FLT-04, FLT-10, DSP-20).
 *
 * VS-16 AC: a program that halts, one that wanders and one that stops reading KEYS each silence
 * the offline render within 8 ms (of the supervisor declaring the fault); CRAWL and 1/3000 speeds
 * do not raise program_stalled. (The 10 s no-UI mute is rigd's, VS-14.)
 *
 * The programs share a prefix that raises gate 0, plays C4 and reads the keyboard 8,192 times
 * (about 74 ms), then:
 *   halting    LPSW into a wait state with interrupts off
 *   wandering  B X'7000' (outside the code: zeros, illegal instructions)
 *   deaf       loops writing the D/A, never reading the keyboard again
 *   live       keeps reading the keyboard for ever
 */
#include "seastones.h"
#include "sha256.h"

#include <stdio.h>
#include <string.h>

static int failures, checks;

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

#define PREFIX                                                                                     \
    0xC8A0, 0x0020,     /* 100 LHI R10,KEYS */                                                     \
        0xC8B0, 0x0021, /* 104 LHI R11,DAC */                                                      \
        0xC8C0, 0x0022, /* 108 LHI R12,GATE */                                                     \
        0xC830, 0x8000, /* 10C LHI R3,X'8000' */                                                   \
        0x98C3,         /* 110 WHR R12,R3   gate 0 up */                                           \
        0xC820, 0x6400, /* 112 LHI R2,X'6400' C4 */                                                \
        0x98B2,         /* 116 WHR R11,R2 */                                                       \
        0xC850, 0x2000, /* 118 LHI R5,8192 */                                                      \
        0x9BA4,         /* 11C RDR R10,R4   read the keyboard */                                   \
        0x2751,         /* 11E SIS R5,1 */                                                         \
        0x4230, 0x011C  /* 120 BNZ X'11C' */

static const uint16_t halting[] = {PREFIX, 0xC200, 0x0200};              /* 124 LPSW X'200' */
static const uint16_t wandering[] = {PREFIX, 0x4300, 0x7000};            /* 124 B X'7000' */
static const uint16_t deaf[] = {PREFIX, 0x2621, 0x98B2, 0x4300, 0x0124}; /* AIS, WHR, B */
static const uint16_t live[] = {PREFIX, 0x4300, 0x011C};                 /* 124 B X'11C' */
static const uint16_t wait_psw[] = {0x8000, 0x0124};                     /* X'200': wait, no EXI */

static sx_segment segs[2];

static void digest(sx_image *img)
{
    sx_sha256 h;
    sx_sha256_init(&h);
    for (uint32_t i = 0; i < img->nsegments; i++) {
        const sx_segment *s = &img->segments[i];
        uint8_t hd[4] = {(uint8_t)(s->addr >> 8), (uint8_t)s->addr, (uint8_t)(s->nwords >> 8),
                         (uint8_t)s->nwords};
        sx_sha256_update(&h, hd, 4);
        for (uint32_t k = 0; k < s->nwords; k++) {
            uint8_t w[2] = {(uint8_t)(s->words[k] >> 8), (uint8_t)s->words[k]};
            sx_sha256_update(&h, w, 2);
        }
    }
    sx_sha256_final(&h, img->sha256);
}

/* one voice on D/A 0 and gate line 0, as the test programs write them */
static const char latch_voice[] = "graph 1\nmodule osc vco\nmodule eg env\nmodule amp vca\n"
                                  "module o out\ncable dac.0 osc.pitch\ncable gate.0 eg.gate\n"
                                  "cable osc.saw amp.in\ncable eg.out amp.cv\ncable amp.out o.l\n";

static sx_engine *start(const uint16_t *p, uint16_t n)
{
    sx_config c = {SX_API_VERSION, 48000, 32768, 250, 12, 10.24f, 0, 4096, 0, 0, 0};
    sx_engine *e = sx_create(&c);
    CHECK(e && sx_patch_load(e, latch_voice, sizeof latch_voice - 1u, NULL, 0) == SX_OK);
    segs[0] = (sx_segment){0x100, n, p};
    segs[1] = (sx_segment){0x200, 2, wait_psw};
    sx_image img = {segs, 2, 0x100, 0, {0}};
    digest(&img);
    CHECK(e && sx_load_image(e, &img) == SX_OK);
    return e;
}

static float out[2 * 128];

static double peak(void)
{
    double p = 0;
    for (int i = 0; i < 256; i++)
        p = out[i] > p ? out[i] : (-out[i] > p ? -out[i] : p);
    return p;
}

/* Render until the fault; returns ms from the program leaving its reading loop to the fault,
 * and checks the tone sounded before and silence from 8 ms after the fault on. */
static double fault_case(const char *name, const uint16_t *p, uint16_t n)
{
    sx_engine *e = start(p, n);
    sx_snapshot s;
    long left = -1, fault = -1;
    double before = 0;
    int loud_after = 0;
    for (long per = 0; per < 1500; per++) { /* 4 s */
        sx_render(e, out, 128);
        sx_snapshot_read(e, &s);
        if (left < 0 && (s.pc < 0x11C || s.pc > 0x122) && per > 2)
            left = per;
        if (fault < 0 && (s.faults & SX_FAULT_PROGRAM_STALLED))
            fault = per;
        if (fault < 0)
            before = peak() > before ? peak() : before;
        else if (per >= fault + 3 && peak() > 0.0) /* 3 periods = 8.0 ms */
            loud_after = 1;
    }
    double ms = (double)(fault - left) * 128.0 / 48.0;
    printf("%-10s left its loop at %.1f ms, fault after %.2f ms more; peak before %.2f; %s 8 ms "
           "after\n",
           name, (double)left * 128.0 / 48.0, ms, before, loud_after ? "SOUND" : "silent");
    CHECK(fault >= 0 && before > 0.1 && !loud_after && s.muted);
    /* HOME recovers: faults clear and the tone returns through the fade-in */
    sx_cmd home = {SX_CMD_RESET_HOME, 0, 0, 0.0f};
    sx_command(e, &home);
    double again = 0;
    for (int per = 0; per < 15; per++) { /* 40 ms: still inside its 72 ms reading loop */
        sx_render(e, out, 128);
        again = peak() > again ? peak() : again;
    }
    sx_snapshot_read(e, &s);
    printf("  after HOME: pc %04X psw %04X faults %X muted %u peak %.3f\n", s.pc, s.psw, s.faults,
           s.muted, again);
    CHECK(!(s.faults & SX_FAULT_PROGRAM_STALLED) && !s.muted && again > 0.01);
    sx_destroy(e);
    return ms;
}

static void no_fault_at(uint32_t speed_cmd_a, uint32_t divisor, double seconds)
{
    sx_engine *e = start(live, sizeof live / 2);
    sx_cmd sp = {SX_CMD_SPEED, speed_cmd_a, divisor, 0.0f};
    CHECK(sx_command(e, &sp) == SX_OK);
    sx_snapshot s;
    uint32_t any = 0;
    for (long per = 0; per < (long)(seconds * 375.0); per++) {
        sx_render(e, out, 128);
        sx_snapshot_read(e, &s);
        any |= s.faults;
    }
    printf("live program, speed %u/%u, %.0f s: faults %X, emulated %.1f ms\n", speed_cmd_a, divisor,
           seconds, any, (double)s.cycles * 250e-6);
    CHECK(any == 0);
    sx_destroy(e);
}

int main(void)
{
    double h = fault_case("halting", halting, sizeof halting / 2);
    double w = fault_case("wandering", wandering, sizeof wandering / 2);
    double d = fault_case("deaf", deaf, sizeof deaf / 2);
    CHECK(h <= 128.0 / 48.0 && w <= 128.0 / 48.0); /* within the period it happened in */
    CHECK(d >= 45.0 && d <= 56.0);                 /* liveness: 50 ms of emulated time */
    no_fault_at(SX_SPEED_RUN, 0, 3.0);
    no_fault_at(SX_SPEED_CRAWL, 0, 3.0);
    no_fault_at(SX_SPEED_DIVISOR, 3000, 3.0);
    no_fault_at(SX_SPEED_SINGLE, 0, 1.0);
    printf("test_supervisor: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
