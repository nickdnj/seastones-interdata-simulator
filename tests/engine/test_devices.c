/* test_devices.c: KEYS X'20', DAC X'21', GATE X'22' (VS-03, VS-04, VS-05).
 *
 * DEV-01..DEV-13 and DEV-16 (docs/TEST-PLAN.md 4.2), driving the DIB functions directly
 * and, for the integration cases, through the CPU with real I/O instructions.
 * Provisional on the S-3 decision (SP-S3D).
 */
#include "id_seastones.h"
#include "keys.h"
#include "scp_shim.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern UNIT cpu_unit;
extern DEVICE cpu_dev;
extern uint32 PC, PSW, GREG[16];
extern t_bool devtab_init(void);
extern uint32 (*dev_tab[DEVNO])(uint32 dev, uint32 op, uint32 datout);

static int failures, checks;
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(x)) {                                                                                \
            failures++;                                                                            \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #x);                  \
        }                                                                                          \
    } while (0)

/* --- event capture (the seam the Phase 2 sink and the renderer hang off) ------------- */

#define MAXEV 4096
static uint32 ev_dev[MAXEV], ev_ch[MAXEV], ev_val[MAXEV], ev_t[MAXEV];
static int nev;
static void capture(uint32 dev, uint32 ch, uint32 val, uint32 t)
{
    if (nev < MAXEV) {
        ev_dev[nev] = dev, ev_ch[nev] = ch, ev_val[nev] = val, ev_t[nev] = t;
        nev++;
    }
}

static void reset(void)
{
    sx_keys_reset_sources();
    for (uint32 i = 0; i < SX_DAC_CH; i++)
        sx_dac_rest[i] = 0;
    sx_dac_word_bits = 12;
    sx_shim_reset_all();
    sx_keys_latch();
    nev = 0;
    sx_dev_event = &capture;
}

/* --- KEYS ------------------------------------------------------------------------------ */

static void test_keys_mapping(void) /* DEV-01 */
{
    for (uint32 k = 0; k < 64; k++) {
        uint8_t rows[8];
        sx_keys_bits_to_rows((uint64_t)1 << k, rows);
        for (uint32 r = 0; r < 8; r++)
            CHECK(rows[r] == (r == (k >> 3) ? (0x80u >> (k & 7)) : 0));
        reset();
        sx_keys_source_set(0, (uint64_t)1 << k);
        sx_keys_latch();
        sx_keys_io(SX_D_KEYS, IO_OC, 0x80u | (k >> 3)); /* normal mode, select the row */
        CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == (0x80u >> (k & 7)));
        CHECK(sx_keys_row == (k >> 3)); /* normal: never advances */
    }
}

static void test_keys_advance(void) /* DEV-02 */
{
    reset();
    for (uint32 r = 0; r < 8; r++)
        sx_keys_rows[r] = (uint8)(0x10 + r);
    sx_keys_io(SX_D_KEYS, IO_OC, 0x40u | 5u);
    for (uint32 i = 0; i < 40; i++)
        CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == 0x10u + ((5u + i) & 7u));
    sx_keys_io(SX_D_KEYS, IO_OC, 0x80u | 3u);
    for (uint32 i = 0; i < 40; i++)
        CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == 0x13u);
    sx_keys_io(SX_D_KEYS, IO_OC, 6u); /* mode bits 00: mode unchanged, row selected */
    CHECK(sx_keys_auto == 0 && sx_keys_row == 6);
}

static void test_keys_rh(void) /* DEV-03 */
{
    reset();
    for (uint32 r = 0; r < 8; r++)
        sx_keys_rows[r] = (uint8)(0xA0 + r);
    sx_keys_io(SX_D_KEYS, IO_OC, 0x40u | 7u); /* odd row: wraps 7 -> 0 */
    CHECK(sx_keys_io(SX_D_KEYS, IO_RH, 0) == 0xA7A0u);
    CHECK(sx_keys_row == 1);
    CHECK(sx_keys_io(SX_D_KEYS, IO_RH, 0) == 0xA1A2u);
    sx_keys_io(SX_D_KEYS, IO_OC, 0x80u | 7u);
    CHECK(sx_keys_io(SX_D_KEYS, IO_RH, 0) == 0xA7A0u);
    CHECK(sx_keys_row == 7);
    CHECK(sx_keys_io(SX_D_KEYS, IO_ADR, 0) == HW);
}

static void test_keys_status_and_sources(void) /* DEV-04, DEV-05 */
{
    reset();
    CHECK(sx_keys_io(SX_D_KEYS, IO_SS, 0) == 0x1u); /* DU: no source has ever attached */
    sx_keys_source_set(1, 0);                       /* touch attaches, no keys down */
    sx_keys_latch();
    CHECK(sx_keys_io(SX_D_KEYS, IO_SS, 0) == 0);
    sx_keys_source_set(0, 0x0Full);  /* MIDI keys 0-3 */
    sx_keys_source_set(1, 0x0F0ull); /* touch keys 4-7 */
    CHECK(sx_keys_raw_bits() == 0xFFull);
    sx_keys_source_clear(0); /* the MIDI port vanished */
    CHECK(sx_keys_raw_bits() == 0xF0ull);
    sx_keys_source_clear(1);
    CHECK(sx_keys_raw_bits() == 0);
}

static void test_keys_seen_and_latch(void) /* DEV-06, DEV-07, INPUT-1 AC */
{
    reset();
    sx_keys_source_set(1, 1ull << 9); /* row 1 */
    sx_keys_latch();
    sx_keys_io(SX_D_KEYS, IO_OC, 0x80u | 1u);
    CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == 0x40u);
    CHECK(sx_keys_seen[1] == 0x40u);
    sx_keys_source_set(1, 1ull << 8); /* mid-period change, then another: level semantics */
    sx_keys_source_set(1, 1ull << 15);
    CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == 0x40u); /* not visible before the boundary */
    uint8_t raw[8];
    sx_keys_bits_to_rows(sx_keys_raw_bits(), raw);
    CHECK(raw[1] == 0x01u && sx_keys_seen[1] == 0x40u); /* raw moved, seen did not */
    sx_keys_latch();
    CHECK(sx_keys_seen[1] == 0x40u); /* still the old value until the program reads */
    CHECK(sx_keys_io(SX_D_KEYS, IO_RD, 0) == 0x01u && sx_keys_seen[1] == 0x01u);
    /* With no program reading, key changes move nothing but keys_raw (INPUT-1). */
    uint16 dac_before[SX_DAC_CH];
    memcpy(dac_before, sx_dac_code, sizeof dac_before);
    uint32 gate_before = sx_gate_latch;
    uint8 seen_before[8];
    memcpy(seen_before, sx_keys_seen, sizeof seen_before);
    nev = 0;
    for (uint32 k = 0; k < 37; k++) {
        sx_keys_source_set(0, (1ull << k) | (1ull << 36));
        sx_keys_latch();
    }
    CHECK(memcmp(dac_before, sx_dac_code, sizeof dac_before) == 0);
    CHECK(gate_before == sx_gate_latch && nev == 0);
    CHECK(memcmp(seen_before, sx_keys_seen, sizeof seen_before) == 0);
}

/* --- DAC ------------------------------------------------------------------------------- */

static void test_dac_select(void) /* DEV-08 */
{
    reset();
    for (uint32 c = 0; c < 16; c++) {
        sx_dac_io(SX_D_DAC, IO_OC, 0x80u | c);
        sx_dac_io(SX_D_DAC, IO_WH, 0x1000u * c + 0x10u);
        CHECK(sx_dac_ch == c);
    }
    sx_dac_io(SX_D_DAC, IO_OC, 0x40u | 14u);
    sx_dac_io(SX_D_DAC, IO_WH, 0xFFF0u); /* ch 14 */
    sx_dac_io(SX_D_DAC, IO_WH, 0xEEE0u); /* ch 15 */
    sx_dac_io(SX_D_DAC, IO_WH, 0xDDD0u); /* wraps to ch 0 */
    CHECK(sx_dac_code[14] == 0xFFF0u && sx_dac_code[15] == 0xEEE0u && sx_dac_code[0] == 0xDDD0u);
    CHECK(sx_dac_ch == 1);
    CHECK(sx_dac_io(SX_D_DAC, IO_SS, 0) == 0); /* DEV-11: never busy in v1 */
    CHECK(sx_dac_io(SX_D_DAC, IO_ADR, 0) == HW);
}

static void test_dac_word_format(void) /* DEV-09, VS-04 AC 1 */
{
    const uint32 widths[] = {8, 10, 12, 14, 16};
    for (uint32 w = 0; w < 5; w++) {
        reset();
        uint32 n = widths[w];
        sx_dac_word_bits = n;
        sx_dac_io(SX_D_DAC, IO_OC, 0x80u | 3u);
        sx_dac_io(SX_D_DAC, IO_WH, 0xABCDu);
        uint32 mask = (0xFFFFu << (16u - n)) & 0xFFFFu;
        CHECK(sx_dac_code[3] == (0xABCDu & mask));
        float v = sx_dac_volts(sx_dac_code[3], n, 10.24f);
        float want = (float)((0xABCDu & 0xFFFFu) >> (16u - n)) * 10.24f / (float)(1u << n);
        CHECK(fabsf(v - want) < 1e-6f);
        CHECK(sx_dac_code[2] == 0 && sx_dac_code[4] == 0); /* channels are independent */
        sx_dac_io(SX_D_DAC, IO_WD, 0x5Au); /* 8-bit path: high byte, low byte cleared */
        CHECK(sx_dac_code[3] == (0x5A00u & mask));
    }
    /* 12-bit LSB is 2.5 mV; 8-bit LSB is 40 mV (MACH-3). */
    CHECK(fabsf(sx_dac_volts(0x0010u, 12, 10.24f) - 0.0025f) < 1e-7f);
    CHECK(fabsf(sx_dac_volts(0x0100u, 8, 10.24f) - 0.040f) < 1e-7f);
    CHECK(fabsf(sx_dac_volts(0xFFF0u, 12, 10.24f) - (10.24f - 0.0025f)) < 1e-5f);
    CHECK(sx_dac_volts(0, 12, 10.24f) == 0.0f);
}

static void test_cycle_to_frame(void) /* DEV-10 (mapping half) */
{
    srand(1974);
    for (int i = 0; i < 10000; i++) {
        t_uint64 c = ((t_uint64)(unsigned)rand() << 20) ^ (t_uint64)(unsigned)rand();
        t_uint64 exact = c * 3u / 250u; /* c x 250 x 48000 / 10^9, reduced: c < 2^51 fits */
        CHECK(sx_cycle_to_frame(c, 250, 48000) == exact);
    }
    CHECK(sx_cycle_to_frame(0, 250, 48000) == 0);
    CHECK(sx_cycle_to_frame(83, 250, 48000) == 0);          /* 83 cycles = 20.75 us < 1 frame */
    CHECK(sx_cycle_to_frame(84, 250, 48000) == 1);          /* 21 us >= 20.833 us */
    CHECK(sx_cycle_to_frame(4000000, 250, 48000) == 48000); /* 1 s of cycles */
}

/* --- GATE ------------------------------------------------------------------------------ */

static void test_gate(void) /* DEV-12, VS-05 */
{
    reset();
    CHECK(sx_gate_latch == 0);
    sx_gate_io(SX_D_GATE, IO_WH, 0xA5C3u);
    CHECK(sx_gate_latch == 0xA5C3u);
    sx_gate_io(SX_D_GATE, IO_WD, 0x0Fu); /* lines 0-7 (high byte) only */
    CHECK(sx_gate_latch == 0x0FC3u);
    sx_gate_io(SX_D_GATE, IO_OC, 0xFFu); /* nothing else changes it */
    sx_gate_io(SX_D_GATE, IO_RD, 0);
    CHECK(sx_gate_latch == 0x0FC3u);
    CHECK(nev == 2 && ev_dev[0] == SX_D_GATE && ev_val[1] == 0x0FC3u);
    CHECK(sx_gate_io(SX_D_GATE, IO_ADR, 0) == HW);
}

static void test_reset_state(void) /* DEV-13 */
{
    reset();
    for (uint32 i = 0; i < SX_DAC_CH; i++)
        sx_dac_rest[i] = (uint16)(0x1000u * i + 0x0123u);
    sx_dac_word_bits = 12;
    sx_keys_io(SX_D_KEYS, IO_OC, 0x40u | 5u);
    sx_gate_io(SX_D_GATE, IO_WH, 0xFFFFu);
    sx_shim_reset_all();
    CHECK(sx_gate_latch == 0 && sx_keys_row == 0 && sx_keys_auto == 0);
    for (uint32 i = 0; i < SX_DAC_CH; i++)
        CHECK(sx_dac_code[i] == ((0x1000u * i + 0x0123u) & 0xFFF0u));
    CHECK(sx_dac_ch == 0 && sx_dac_auto == 0);
}

static void test_address_hygiene(void) /* DEV-16 */
{
    reset();
    CHECK(devtab_init() == FALSE); /* no device-number conflict */
    CHECK(dev_tab[0x20] != NULL && dev_tab[0x21] != NULL && dev_tab[0x22] != NULL);
    for (uint32 d = 0x23; d <= 0x2F; d++)
        CHECK(dev_tab[d] == NULL);
    CHECK(dev_tab[0x01] != NULL && dev_tab[0x6C] != NULL && dev_tab[0x6D] != NULL);
    for (uint32 d = 0x10; d <= 0x1F; d++)
        CHECK(dev_tab[d] == NULL);                         /* no PAS in the engine */
    CHECK(dev_tab[0x02] == NULL && dev_tab[0x03] == NULL); /* no Teletype, no tape */
}

/* --- through the CPU: real I/O instructions -------------------------------------------- */

static void load(const uint16 *w, uint32 n, uint32 at)
{
    for (uint32 i = 0; i < n; i++)
        cpu_dev.deposit(w[i], at + 2 * i, &cpu_unit, 0);
}

static void test_program_io(void) /* VS-04 AC 2/3: timing and the event seam */
{
    reset();
    sx_keys_source_set(1, 1ull << 12); /* key 12: row 1, 0x08 */
    sx_keys_latch();
    /* X'100' LHI R1,X'20' / OC R1,X'200' (=X'81': normal, row 1) / RD R1,X'202'
     * LHI R1,X'21' / OC R1,X'204' (=X'45': auto, ch 5) / LH R2,X'206' / WHR R1,R2
     * WHR R1,R2 / LHI R1,X'22' / WH R1,X'208' / B X'100' */
    const uint16 prog[] = {0xC810, 0x0020, 0xDE10, 0x0200, 0xDB10, 0x0202, 0xC810, 0x0021,
                           0xDE10, 0x0204, 0xC820, 0x0206, 0x4820, 0x0206, 0x9812, 0x9812,
                           0xC810, 0x0022, 0xD810, 0x0208, 0x4300, 0x0100};
    load(prog, sizeof prog / sizeof prog[0], 0x100);
    const uint16 data[] = {0x8100, 0x0000, 0x4500, 0xABCD, 0x8000};
    load(data, 5, 0x200);
    PC = 0x100;
    PSW = 0;
    uint32 t0 = sx_shim_time();
    CHECK(sx_shim_run(11) == SCPE_STEP);
    CHECK((cpu_dev.examine(&(t_value){0}, 0x202, &cpu_unit, 0), 1));
    t_value w = 0;
    cpu_dev.examine(&w, 0x202, &cpu_unit, 0);
    CHECK((w >> 8) == 0x08u && sx_keys_seen[1] == 0x08u); /* RD stored the row byte */
    CHECK(nev == 3);
    CHECK(ev_dev[0] == SX_D_DAC && ev_ch[0] == 5 && ev_val[0] == 0xABC0u);
    CHECK(ev_dev[1] == SX_D_DAC && ev_ch[1] == 6 && ev_val[1] == 0xABC0u); /* auto-increment */
    CHECK(ev_dev[2] == SX_D_GATE && ev_val[2] == 0x8000u);                 /* gate line 0 */
    /* Instruction k (1-based) is stamped k ticks after the start: WHR is the 8th and 9th,
     * WH the 11th. At one cycle per instruction (patch 0001 stub) ticks are cycles. */
    CHECK(ev_t[0] - t0 == 8 && ev_t[1] - t0 == 9 && ev_t[2] - t0 == 11);
    CHECK(sx_cycle_to_frame(ev_t[2] - t0, 250, 48000) == 0); /* 11 cycles: still frame 0 */
}

int main(void)
{
    test_keys_mapping();
    test_keys_advance();
    test_keys_rh();
    test_keys_status_and_sources();
    test_keys_seen_and_latch();
    test_dac_select();
    test_dac_word_format();
    test_cycle_to_frame();
    test_gate();
    test_reset_state();
    test_address_hygiene();
    test_program_io();
    printf("test_devices: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
