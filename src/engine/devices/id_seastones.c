/* id_seastones.c: the Seastones Rig's three I/O devices for SIMH's Interdata 16b CPU.
 *
 * ARCHITECTURE 5 (the device contract) and ADR-003. OUR design, not Lagin's: the exhibit
 * says so (PATCH-7). Written against SIMH's device interface only, so the SAME FILE builds
 * into the engine (with src/engine/shim) and into the `id16-seastones` oracle (stock SIMH
 * at the pin plus this file, VS-06). It must not include engine headers.
 *
 *   KEYS  X'20'  key-matrix input port: 8 rows x 8 keys (5.1)
 *   DAC   X'21'  16-channel D/A converter, 16-bit MSB-justified codes (5.2)
 *   GATE  X'22'  16-bit gate latch (5.3)
 *
 * Polled I/O only: no device ever requests an interrupt. Bit numbering is Interdata's
 * (bit 0 is the most significant bit), as everywhere in section 5: key k is row k >> 3,
 * bit 7 - (k & 7), i.e. mask 0x80 >> (k & 7); gate line i is bit i, mask 0x8000 >> i.
 *
 * Every D/A and gate write is reported through `sx_dev_event` with its emulated time
 * (sim_grtime: interval ticks, which patch 0001 makes cycles). The engine maps that to an
 * audio frame (sx_cycle_to_frame) and forwards it to the Phase 2 sink (P2-3). The oracle
 * build writes the same events to the file named by SX_DEV_TRACE, so the two traces can
 * be compared line for line (DEV-14).
 *
 * Copyright (c) 2026 Nick D. MIT licence:
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify, merge,
 * publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
 * to whom the Software is furnished to do so, subject to the following conditions: The above
 * copyright notice and this permission notice shall be included in all copies or substantial
 * portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
 * FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
 * CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
 * USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
#include "id_defs.h"

#if defined(SEASTONES_ENGINE)
#include "id_seastones.h" /* engine only: lets the compiler check the declarations */
#else
#include <stdlib.h>
#endif

/* --- the contract's constants (DEV-17 checks these against docs/device-spec) ------------ */

#define SX_D_KEYS 0x20u
#define SX_D_DAC 0x21u
#define SX_D_GATE 0x22u
#define SX_V_KEYS ((3u * 32u) + 0u) /* interrupt numbers: level 3 is free in id16, and */
#define SX_V_DAC ((3u * 32u) + 1u)  /* these devices never raise them (polled only) */
#define SX_V_GATE ((3u * 32u) + 2u)

#define SX_OC_AUTO 0x40u   /* auto-advance (KEYS) / auto-increment (DAC) */
#define SX_OC_NORMAL 0x80u /* no advance */
#define SX_OC_MODE 0xC0u
#define SX_STA_DU 0x1u /* device unavailable: KEYS with no key source ever attached */

#define SX_DAC_CH 16u
#define SX_KEY_ROWS 8u

/* --- state (globals: SIMH style; the engine reads them for the snapshot) ---------------- */

uint8 sx_keys_rows[SX_KEY_ROWS]; /* what RD returns now: sources ORed, latched per period */
uint8 sx_keys_seen[SX_KEY_ROWS]; /* the last value the program actually read, per row */
uint32 sx_keys_attached = 0;     /* nonzero once any key source has attached */
uint32 sx_keys_row = 0;          /* selected row, 0-7 */
uint32 sx_keys_auto = 0;         /* auto-advance after each read */
uint32 sx_keys_reads = 0;        /* row reads so far: the supervisor's liveness check (VS-16) */
uint16 sx_dac_code[SX_DAC_CH];   /* latched codes, after word-size truncation */
uint32 sx_dac_ch = 0;            /* selected channel, 0-15 */
uint32 sx_dac_auto = 0;          /* auto-increment after each write */
uint32 sx_dac_word_bits = 12;    /* converter resolution N (MACH-3), 1-16 */
uint32 sx_gate_latch = 0;        /* gate line i is bit i (mask 0x8000 >> i) */
uint16 sx_dac_rest[SX_DAC_CH];   /* codes the D/A holds after reset (DEV-13) */

/* Called for every D/A and gate write: dev, channel (gate: 0), value, emulated time. */
void (*sx_dev_event)(uint32 dev, uint32 ch, uint32 val, uint32 t) = NULL;

/* --- KEYS X'20' ---------------------------------------------------------------------- */

static uint32 keys_read_row(void)
{
    uint32 v = sx_keys_rows[sx_keys_row];
    sx_keys_seen[sx_keys_row] = (uint8)v;
    sx_keys_reads++;
    if (sx_keys_auto)
        sx_keys_row = (sx_keys_row + 1u) & 7u;
    return v;
}

uint32 sx_keys_io(uint32 dev, uint32 op, uint32 dat)
{
    (void)dev;
    switch (op) {
    case IO_ADR: /* select: halfword reads are supported */
        return HW;
    case IO_OC:
        if ((dat & SX_OC_MODE) == SX_OC_AUTO)
            sx_keys_auto = 1;
        else if ((dat & SX_OC_MODE) == SX_OC_NORMAL)
            sx_keys_auto = 0;
        sx_keys_row = dat & 7u; /* bits 5-7 */
        return 0;
    case IO_RD:
        return keys_read_row();
    case IO_RH: { /* row n in the high byte, n+1 in the low byte; advances by two */
        uint32 hi, lo;
        if (sx_keys_auto) {
            hi = keys_read_row();
            lo = keys_read_row();
        } else { /* normal mode: n and n+1 without moving the pointer */
            uint32 n = sx_keys_row;
            hi = keys_read_row();
            sx_keys_row = (n + 1u) & 7u;
            lo = keys_read_row();
            sx_keys_row = n;
        }
        return (hi << 8) | lo;
    }
    case IO_SS:
        return sx_keys_attached ? 0u : SX_STA_DU;
    default: /* WD, WH to an input port: ignored */
        return 0;
    }
}

/* --- DAC X'21' ----------------------------------------------------------------------- */

static uint32 dac_mask(void)
{
    uint32 n = sx_dac_word_bits < 1u ? 1u : (sx_dac_word_bits > 16u ? 16u : sx_dac_word_bits);
    return (0xFFFFu << (16u - n)) & 0xFFFFu;
}

static void dac_write(uint32 code)
{
    uint32 ch = sx_dac_ch;
    sx_dac_code[ch] = (uint16)(code & dac_mask()); /* N-bit converter, top of the bus */
    if (sx_dev_event)
        sx_dev_event(SX_D_DAC, ch, sx_dac_code[ch], sim_grtime());
    if (sx_dac_auto)
        sx_dac_ch = (sx_dac_ch + 1u) & 0xFu;
}

uint32 sx_dac_io(uint32 dev, uint32 op, uint32 dat)
{
    (void)dev;
    switch (op) {
    case IO_ADR:
        return HW;
    case IO_OC:
        if ((dat & SX_OC_MODE) == SX_OC_AUTO)
            sx_dac_auto = 1;
        else if ((dat & SX_OC_MODE) == SX_OC_NORMAL)
            sx_dac_auto = 0;
        sx_dac_ch = dat & 0xFu; /* bits 4-7 */
        return 0;
    case IO_WH:
        dac_write(dat & 0xFFFFu);
        return 0;
    case IO_WD: /* the 8-bit path: high byte, low byte cleared */
        dac_write((dat & 0xFFu) << 8);
        return 0;
    case IO_SS: /* never busy (honour_busy is off in v1) */
        return 0;
    default: /* RD, RH from an output port: zero */
        return 0;
    }
}

/* Volts for a latched code: V = (code >> (16 - N)) * range / 2^N (5.2). */
float sx_dac_volts(uint32 code, uint32 word_bits, float range_v)
{
    uint32 n = word_bits < 1u ? 1u : (word_bits > 16u ? 16u : word_bits);
    uint32 steps = (code & 0xFFFFu) >> (16u - n);
    return (float)steps * range_v / (float)(1u << n);
}

/* --- GATE X'22' ---------------------------------------------------------------------- */

static void gate_set(uint32 v)
{
    sx_gate_latch = v & 0xFFFFu;
    if (sx_dev_event)
        sx_dev_event(SX_D_GATE, 0, sx_gate_latch, sim_grtime());
}

uint32 sx_gate_io(uint32 dev, uint32 op, uint32 dat)
{
    (void)dev;
    switch (op) {
    case IO_ADR:
        return HW;
    case IO_WH:
        gate_set(dat);
        return 0;
    case IO_WD: /* bits 0-7 (the high byte) only; lines 8-15 keep their state */
        gate_set((sx_gate_latch & 0x00FFu) | ((dat & 0xFFu) << 8));
        return 0;
    default: /* OC, SS, RD, RH: nothing to do; status 0 */
        return 0;
    }
}

/* --- emulated time to audio frame (used by the engine; DEV-10) ----------------------- */

/* The audio frame on which an event at emulated cycle `cycle` takes effect:
 * floor(cycle * cycle_ns * rate / 1e9), in integers so it is exact and reproducible. */
t_uint64 sx_cycle_to_frame(t_uint64 cycle, uint32 cycle_ns, uint32 rate)
{
    t_uint64 per = (t_uint64)cycle_ns * (t_uint64)rate; /* frames x 1e9 per cycle */
    t_uint64 q = cycle / 1000000000u, r = cycle % 1000000000u;
    return q * per + (r * per) / 1000000000u;
}

/* --- SIMH device descriptors ----------------------------------------------------------- */

#if !defined(SEASTONES_ENGINE)
static FILE *trace_file;
static void trace_event(uint32 dev, uint32 ch, uint32 val, uint32 t)
{
    fprintf(trace_file, "W %02X %X %04X %u\n", dev, ch, val, t);
    fflush(trace_file);
}
#endif

static t_stat sx_keys_reset(DEVICE *dptr)
{
    (void)dptr;
    sx_keys_row = 0;
    sx_keys_auto = 0;
    for (uint32 i = 0; i < SX_KEY_ROWS; i++)
        sx_keys_seen[i] = 0;
#if !defined(SEASTONES_ENGINE)
    sx_keys_attached = 1; /* the oracle's keys come from deposits: count as attached */
#endif
    return SCPE_OK;
}

static t_stat sx_dac_reset(DEVICE *dptr)
{
    (void)dptr;
    sx_dac_ch = 0;
    sx_dac_auto = 0;
    for (uint32 i = 0; i < SX_DAC_CH; i++)
        sx_dac_code[i] = (uint16)(sx_dac_rest[i] & dac_mask());
#if !defined(SEASTONES_ENGINE)
    {
        const char *path = getenv("SX_DEV_TRACE");
        if (path && !trace_file && (trace_file = fopen(path, "w")) != NULL)
            sx_dev_event = &trace_event;
    }
#endif
    return SCPE_OK;
}

static t_stat sx_gate_reset(DEVICE *dptr)
{
    (void)dptr;
    sx_gate_latch = 0; /* power-on and HOME: all gates low (DEV-12) */
    return SCPE_OK;
}

DIB sx_keys_dib = {SX_D_KEYS, -1, SX_V_KEYS, NULL, &sx_keys_io, NULL};
DIB sx_dac_dib = {SX_D_DAC, -1, SX_V_DAC, NULL, &sx_dac_io, NULL};
DIB sx_gate_dib = {SX_D_GATE, -1, SX_V_GATE, NULL, &sx_gate_io, NULL};

UNIT sx_keys_unit = {.flags = 0};
UNIT sx_dac_unit = {.flags = 0};
UNIT sx_gate_unit = {.flags = 0};

/* SIMH's REG macros initialise a prefix of the struct; the rest is zero by design. SCP
 * sizes array elements by the register width, hence the uint8 and uint16 arrays above. */
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#endif

REG sx_keys_reg[] = {{BRDATA(ROWS, sx_keys_rows, 16, 8, SX_KEY_ROWS)},
                     {BRDATA(SEEN, sx_keys_seen, 16, 8, SX_KEY_ROWS)},
                     {HRDATA(ROW, sx_keys_row, 3)},
                     {FLDATA(AUTO, sx_keys_auto, 0)},
                     {FLDATA(ATTACHED, sx_keys_attached, 0)},
                     {NULL}};

REG sx_dac_reg[] = {{BRDATA(CODE, sx_dac_code, 16, 16, SX_DAC_CH)},
                    {HRDATA(CHAN, sx_dac_ch, 4)},
                    {FLDATA(AUTO, sx_dac_auto, 0)},
                    {DRDATA(WBITS, sx_dac_word_bits, 5)},
                    {NULL}};

REG sx_gate_reg[] = {{HRDATA(LATCH, sx_gate_latch, 16)}, {NULL}};

#define SX_DEVICE(nm, unit, regs, dw, rst, dib)                                                    \
    {.name = nm,                                                                                   \
     .units = &(unit),                                                                             \
     .registers = regs,                                                                            \
     .numunits = 1,                                                                                \
     .aradix = 16,                                                                                 \
     .awidth = 8,                                                                                  \
     .aincr = 1,                                                                                   \
     .dradix = 16,                                                                                 \
     .dwidth = dw,                                                                                 \
     .reset = rst,                                                                                 \
     .ctxt = &(dib)}

DEVICE sx_keys_dev = SX_DEVICE("KEYS", sx_keys_unit, sx_keys_reg, 8, &sx_keys_reset, sx_keys_dib);
DEVICE sx_dac_dev = SX_DEVICE("DAC", sx_dac_unit, sx_dac_reg, 16, &sx_dac_reset, sx_dac_dib);
DEVICE sx_gate_dev = SX_DEVICE("GATE", sx_gate_unit, sx_gate_reg, 16, &sx_gate_reset, sx_gate_dib);
