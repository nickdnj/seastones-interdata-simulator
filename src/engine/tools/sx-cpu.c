/* sx-cpu: run the engine's CPU (vendored SIMH id16 CPU + scp_shim) from a command script.
 *
 * SP-S3B / SP-S3C test instrument, not part of the shipped engine. It reads commands on
 * stdin, one per line, and prints results in the same text formats stock `id16` uses, so
 * tests/conformance/lockstep.py can drive the engine and the oracle with one script and
 * compare their outputs. Each command maps to one SCP command:
 *
 *   model 716|i4         set cpu 716 | set cpu i4
 *   mem N                set cpu Nk (N in bytes, decimal)
 *   hist N               set cpu history=N
 *   reset                (power-up reset of every device; SCP does this at start)
 *   dep A V              dep A V              (hex byte address, hex halfword)
 *   reg NAME V           dep NAME V           (PC PSW R0..R15 SR DR DRX DRMOD DRPOS SRPOS)
 *   step N               step N               (prints the stop line; N instructions,
 *                                             also in cycle mode)
 *   showhist N           show cpu history=N
 *   ex NAME[,NAME...]    ex NAME,...          (also CC)
 *   exmem A B            ex A-B
 *   disasm A B           ex -m A-B
 *   echo TEXT            echo TEXT
 *   keys HEX64           (key bitmap, bit k = key k, latched into KEYS X'20' at once:
 *                        the oracle's `dep keys rows[r] v` between steps)
 *   trace on             print every D/A and gate write as `W dd c vvvv t`, the format
 *                        id16-seastones writes to $SX_DEV_TRACE (DEV-14)
 *
 * The emulated clock (VS-02; engine only, no SCP equivalent; decimal arguments):
 *   cycles NS            cost instructions from the cycle table (ESTIMATE) in cycles of NS
 *                        ns; 0 = stock, one tick per instruction (the default)
 *   clock RATE NS        drive the CPU from the audio sample count (machine/clock.c) at RATE
 *                        frames/s and NS ns cycles; implies `cycles NS`. Starts halted.
 *   speed P | divisor D  speed position (0 RUN .. 4 CRAWL, 5 SINGLE) or a raw divisor
 *   run | halt           RUN and HALT
 *   frames N P           render N frames in periods of P (prints `frames: cycles C`); with
 *                        `trace on`, writes print as `F frame dd c vvvv`
 *   single N             N STEP commands in SINGLE, one per period, each printing the stop
 *                        line `step 1` prints
 *   period A N           execute N instructions one at a time and print the shortest and
 *                        longest time between arrivals at address A (hex), in ticks
 *   status               print the cycle table's STATUS (ESTIMATE until a 7/16 source)
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "clock.h"
#include "cycles.h"
#include "id_seastones.h"
#include "keys.h"
#include "scp_shim.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern UNIT cpu_unit;
extern DEVICE cpu_dev;
extern uint32 PC, PSW, SR, DR, DRX, drmod, drpos, srpos, GREG[16];
extern t_stat cpu_set_size(UNIT *uptr, int32 val, char *cptr, void *desc);
extern t_stat cpu_set_hist(UNIT *uptr, int32 val, char *cptr, void *desc);
extern t_stat cpu_show_hist(FILE *st, UNIT *uptr, int32 val, void *desc);

/* UNIT_716 and UNIT_ID4 as id16_cpu.c defines them (UNIT_V_UF + 2 and + 1). */
#define SX_UNIT_ID4 (1u << (UNIT_V_UF + 1))
#define SX_UNIT_716 (1u << (UNIT_V_UF + 2))
#define SX_UNIT_TYPE (0xFu << (UNIT_V_UF + 1))

struct reg {
    const char *name;
    uint32 *loc;
    uint32 digits;
};

static struct reg regs[] = {
    {"PC", &PC, 4},        {"PSW", &PSW, 4},      {"SR", &SR, 4},        {"DR", &DR, 8},
    {"DRX", &DRX, 2},      {"DRMOD", &drmod, 1},  {"DRPOS", &drpos, 1},  {"SRPOS", &srpos, 1},
    {"R0", &GREG[0], 4},   {"R1", &GREG[1], 4},   {"R2", &GREG[2], 4},   {"R3", &GREG[3], 4},
    {"R4", &GREG[4], 4},   {"R5", &GREG[5], 4},   {"R6", &GREG[6], 4},   {"R7", &GREG[7], 4},
    {"R8", &GREG[8], 4},   {"R9", &GREG[9], 4},   {"R10", &GREG[10], 4}, {"R11", &GREG[11], 4},
    {"R12", &GREG[12], 4}, {"R13", &GREG[13], 4}, {"R14", &GREG[14], 4}, {"R15", &GREG[15], 4},
};

static struct reg *find(const char *name)
{
    for (size_t i = 0; i < sizeof regs / sizeof regs[0]; i++)
        if (strcmp(regs[i].name, name) == 0)
            return &regs[i];
    return NULL;
}

static uint32 mask_for(uint32 digits)
{
    return digits >= 8 ? 0xFFFFFFFFu : ((1u << (4 * digits)) - 1u);
}

static void ex_regs(char *list)
{
    for (char *n = strtok(list, ","); n != NULL; n = strtok(NULL, ",")) {
        struct reg *r = find(n);
        if (strcmp(n, "CC") == 0)
            printf("CC:\t%X\n", PSW & 0xFu);
        else if (r == NULL)
            printf("%s:\t?\n", n);
        else
            printf("%s:\t%0*X\n", n, (int)r->digits, *r->loc & mask_for(r->digits));
    }
}

static void trace_event(uint32 dev, uint32 ch, uint32 val, uint32 t)
{
    printf("W %02X %X %04X %u\n", dev, ch, val, t);
}

#define EV_CAP 65536u
static sx_dev_ev evbuf[EV_CAP];
static sx_clock clk;
static int clock_on, trace_on;

static void print_period(void)
{
    if (!trace_on)
        return;
    for (uint32_t i = 0; i < clk.ev_n; i++) {
        unsigned long long f = clk.frame - clk.period_frames + clk.ev[i].frame;
        printf("F %llu %02X %X %04X\n", f, clk.ev[i].dev, clk.ev[i].ch, clk.ev[i].val);
    }
}

/* The clock commands; -1 if `cmd` is not one of them. */
static int clock_cmd(const char *cmd, uint32 x, uint32 y)
{
    if (strcmp(cmd, "cycles") == 0) {
        sx_cycles_configure(x);
    } else if (strcmp(cmd, "clock") == 0) {
        sx_clock_init(&clk, x, y, evbuf, EV_CAP);
        clock_on = 1;
    } else if (strcmp(cmd, "status") == 0) {
        printf("cycle table: %s, %u rows\n", sx_cycles_status, sx_cycles_rows);
    } else if (strcmp(cmd, "speed") != 0 && strcmp(cmd, "divisor") != 0 &&
               strcmp(cmd, "run") != 0 && strcmp(cmd, "halt") != 0 && strcmp(cmd, "frames") != 0 &&
               strcmp(cmd, "single") != 0) {
        return -1;
    } else if (!clock_on) {
        fprintf(stderr, "sx-cpu: %s needs `clock` first\n", cmd);
        return 1;
    } else if (strcmp(cmd, "speed") == 0) {
        return sx_clock_set_speed(&clk, x) != 0;
    } else if (strcmp(cmd, "divisor") == 0) {
        return sx_clock_set_divisor(&clk, x) != 0;
    } else if (strcmp(cmd, "run") == 0) {
        sx_clock_run(&clk);
    } else if (strcmp(cmd, "halt") == 0) {
        sx_clock_halt(&clk);
    } else if (strcmp(cmd, "frames") == 0) {
        unsigned long long cycles = 0;
        if (y == 0)
            return 1;
        for (uint32 f = 0; f < x; f += y) {
            cycles += sx_clock_period(&clk, f + y <= x ? y : x - f);
            print_period();
        }
        printf("frames: cycles %llu\n", cycles);
    } else {
        for (uint32 i = 0; i < x; i++) {
            sx_clock_step(&clk);
            sx_clock_period(&clk, 1);
            print_period();
            printf("%s, PC: %04X\n", sx_shim_reason(SCPE_STEP), PC & 0xFFFFu);
        }
    }
    return 0;
}

static int run_line(char *line)
{
    char cmd[16] = "", a[64] = "", b[64] = "";
    char *nl = strchr(line, '\n');
    if (nl)
        *nl = 0;
    if (strncmp(line, "echo ", 5) == 0) {
        printf("%s\n", line + 5);
        return 0;
    }
    if (sscanf(line, "%15s %63s %63s", cmd, a, b) < 1 || cmd[0] == '#')
        return 0;
    uint32 x = (uint32)strtoul(a, NULL, 16), y = (uint32)strtoul(b, NULL, 16);
    int cr = clock_cmd(cmd, (uint32)strtoul(a, NULL, 10), (uint32)strtoul(b, NULL, 10));
    if (cr >= 0)
        return cr;
    if (strcmp(cmd, "model") == 0) {
        uint32 m = strcmp(a, "i4") == 0 ? SX_UNIT_ID4 : SX_UNIT_716;
        cpu_unit.flags = (cpu_unit.flags & ~SX_UNIT_TYPE) | m;
    } else if (strcmp(cmd, "mem") == 0) {
        return cpu_set_size(&cpu_unit, (int32)strtol(a, NULL, 10), NULL, NULL) != SCPE_OK;
    } else if (strcmp(cmd, "hist") == 0) {
        return cpu_set_hist(&cpu_unit, 0, a, NULL) != SCPE_OK;
    } else if (strcmp(cmd, "reset") == 0) {
        return sx_shim_reset_all() != SCPE_OK;
    } else if (strcmp(cmd, "dep") == 0) {
        return cpu_dev.deposit(y, x, &cpu_unit, 0) != SCPE_OK;
    } else if (strcmp(cmd, "reg") == 0) {
        struct reg *r = find(a);
        if (r == NULL)
            return 1;
        *r->loc = y & mask_for(r->digits);
    } else if (strcmp(cmd, "step") == 0) {
        int32 n = (int32)strtol(a, NULL, 10);
        t_stat r = SCPE_STEP;
        if (sx_cycles_cycle_ns() == 0) /* one tick per instruction: SCP's step */
            r = sx_shim_run(n);
        else /* cycle mode: still N instructions (one tick each would be N cycles) */
            for (int32 i = 0; i < n && r == SCPE_STEP; i++)
                r = sx_shim_run(1);
        printf("%s, PC: %04X\n", sx_shim_reason(r), PC & 0xFFFFu);
    } else if (strcmp(cmd, "showhist") == 0) {
        return cpu_show_hist(stdout, &cpu_unit, 0, a) != SCPE_OK;
    } else if (strcmp(cmd, "ex") == 0) {
        ex_regs(line + 3); /* the whole list: it can be longer than `a` holds */
    } else if (strcmp(cmd, "exmem") == 0) {
        for (uint32 p = x & ~1u; p <= y; p += 2) {
            t_value v = 0;
            cpu_dev.examine(&v, p, &cpu_unit, 0);
            printf("%X:\t%04X\n", p, v & 0xFFFFu);
        }
    } else if (strcmp(cmd, "disasm") == 0) {
        char buf[128];
        for (uint32 p = x & ~1u; p <= y;) {
            size_t used = sx_shim_disasm(p, buf, sizeof buf);
            printf("%X:\t%s\n", p, buf);
            p += (uint32)(used ? used : 2);
        }
    } else if (strcmp(cmd, "keys") == 0) {
        uint8_t rows[8];
        sx_keys_bits_to_rows(strtoull(a, NULL, 16), rows);
        for (uint32 r = 0; r < 8; r++)
            sx_keys_rows[r] = rows[r];
        sx_keys_attached = 1;
    } else if (strcmp(cmd, "trace") == 0) {
        trace_on = strcmp(a, "on") == 0;
        if (!clock_on) /* with the clock, its own handler stamps frames (print_period) */
            sx_dev_event = trace_on ? &trace_event : NULL;
    } else if (strcmp(cmd, "period") == 0) {
        unsigned long long last = 0, lo = ~0ull, hi = 0, visits = 0;
        uint32 n = (uint32)strtoul(b, NULL, 10);
        for (uint32 i = 0; i < n; i++) {
            if ((PC & 0xFFFFu) == x) {
                unsigned long long now = sx_shim_now64();
                if (visits++) {
                    lo = now - last < lo ? now - last : lo;
                    hi = now - last > hi ? now - last : hi;
                }
                last = now;
            }
            sx_shim_run(1);
        }
        printf("period %X: visits %llu min %llu max %llu\n", x, visits, visits > 1 ? lo : 0ull, hi);
    } else {
        fprintf(stderr, "sx-cpu: unknown command: %s\n", cmd);
        return 1;
    }
    return 0;
}

int main(void)
{
    char line[512];
    unsigned long n = 0;
    if (sx_shim_reset_all() != SCPE_OK) {
        fprintf(stderr, "sx-cpu: reset failed\n");
        return 2;
    }
    while (fgets(line, sizeof line, stdin) != NULL) {
        n++;
        if (run_line(line)) {
            fprintf(stderr, "sx-cpu: line %lu failed: %s\n", n, line);
            return 1;
        }
    }
    return 0;
}
