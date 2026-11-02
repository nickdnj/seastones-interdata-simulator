/* scp_shim.c: the minimal SCP that lets SIMH's Interdata 16b CPU run inside the engine.
 *
 * ARCHITECTURE 4.2 and ADR-001. Replaces scp.c, sim_timer.c, sim_console.c, sim_fio.c and
 * sim_sock.c for the vendored files id16_cpu.c, id_io.c, id_uvc.c, id16_sys.c and id_fp.c.
 * Everything here is our code, written against SCP's documented behaviour at the pin
 * (v3.12-3), and is kept to what those files actually call (the list in SP-S3B):
 *
 *   interval and event queue  sim_interval, sim_activate, sim_cancel, sim_is_active,
 *                             sim_process_event, sim_grtime
 *   clocks                    sim_rtcn_init, sim_rtcn_calb: emulated time, never the host
 *   idle                      sim_idle (stock "idle disabled": one tick per pass),
 *                             sim_set_idle, sim_clr_idle, sim_show_idle
 *   breakpoints               sim_brk_summ/types/dflt (always none), sim_brk_test
 *   helpers                   sim_printf, fprint_val, get_glyph, get_uint, get_yn,
 *                             find_dev_from_unit, find_reg, sim_int_char
 *
 * Determinism: nothing here reads a host clock, sleeps, or depends on the host. The event
 * queue is a fixed array (no allocation). The queue keeps SCP's ordering rules: an event
 * is due when the interval reaches zero, and events due at the same time run in the order
 * they were scheduled.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "scp_shim.h"

#include <ctype.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

extern DEVICE *sim_devices[];
extern const char *sim_stop_messages[];
extern DEVICE cpu_dev;
extern UNIT cpu_unit;
extern t_stat sim_instr(void);
extern t_stat fprint_sym(FILE *of, t_addr addr, t_value *val, UNIT *uptr, int32 sw);

/* --- globals SCP owns ------------------------------------------------------------- */

int32 sim_interval = 0;
uint32 sim_brk_types = 0;
uint32 sim_brk_dflt = 0;
uint32 sim_brk_summ = 0; /* no breakpoints, ever: the engine has no console */
int32 sim_int_char = 005;

/* --- the event queue --------------------------------------------------------------
 *
 * Absolute emulated times, in interval ticks. sim_interval always holds "ticks until the
 * first event"; the CPU counts it down. `q_base` is the time at which sim_interval was
 * last loaded with `q_loaded`, so the current time is q_base + (q_loaded - sim_interval).
 */
#define SX_QMAX 16

static UNIT *q_unit[SX_QMAX];
static uint64_t q_when[SX_QMAX];
static int q_n;
static uint64_t q_base;
static int32 q_loaded;

static uint64_t q_now(void)
{
    return q_base + (uint64_t)((int64_t)q_loaded - (int64_t)sim_interval);
}

static void q_reload(void)
{
    uint64_t t = q_now();
    q_base = t;
    if (q_n == 0) {
        q_loaded = NOQUEUE_WAIT;
    } else {
        int64_t d = (int64_t)(q_when[0] - t);
        q_loaded = (int32)(d > INT32_MAX ? INT32_MAX : d);
    }
    sim_interval = q_loaded;
}

static int q_find(const UNIT *uptr)
{
    for (int i = 0; i < q_n; i++)
        if (q_unit[i] == uptr)
            return i;
    return -1;
}

static void q_remove(int i)
{
    memmove(&q_unit[i], &q_unit[i + 1], (size_t)(q_n - i - 1) * sizeof q_unit[0]);
    memmove(&q_when[i], &q_when[i + 1], (size_t)(q_n - i - 1) * sizeof q_when[0]);
    q_n--;
}

t_stat sim_activate(UNIT *uptr, int32 event_time)
{
    if (event_time < 0)
        return SCPE_IERR;
    if (q_find(uptr) >= 0) /* already active: SCP leaves it alone */
        return SCPE_OK;
    if (q_n == SX_QMAX)
        return SCPE_IERR;
    uint64_t when = q_now() + (uint64_t)event_time;
    int i = q_n;
    while (i > 0 && q_when[i - 1] > when) /* after every event due no later */
        i--;
    memmove(&q_unit[i + 1], &q_unit[i], (size_t)(q_n - i) * sizeof q_unit[0]);
    memmove(&q_when[i + 1], &q_when[i], (size_t)(q_n - i) * sizeof q_when[0]);
    q_unit[i] = uptr;
    q_when[i] = when;
    q_n++;
    uptr->time = event_time;
    q_reload();
    return SCPE_OK;
}

t_stat sim_activate_abs(UNIT *uptr, int32 event_time)
{
    sim_cancel(uptr);
    return sim_activate(uptr, event_time);
}

t_stat sim_cancel(UNIT *uptr)
{
    int i = q_find(uptr);
    if (i >= 0) {
        q_remove(i);
        uptr->time = 0;
        q_reload();
    }
    return SCPE_OK;
}

/* Activation time + 1, or 0 if not queued (SCP's convention). */
t_bool sim_is_active(UNIT *uptr)
{
    int i = q_find(uptr);
    if (i < 0)
        return 0;
    int64_t d = (int64_t)(q_when[i] - q_now());
    return (t_bool)((d < 0 ? 0 : d) + 1);
}

t_stat sim_process_event(void)
{
    t_stat reason = SCPE_OK;
    q_reload();
    while (reason == SCPE_OK && q_n > 0 && sim_interval <= 0) {
        UNIT *uptr = q_unit[0];
        q_remove(0);
        uptr->time = 0;
        q_reload();
        reason = uptr->action ? uptr->action(uptr) : SCPE_OK;
    }
    return reason;
}

uint32 sim_grtime(void)
{
    return (uint32)q_now();
}

uint32 sx_shim_time(void)
{
    return sim_grtime();
}

uint64_t sx_shim_now64(void)
{
    return q_now();
}

/* --- clocks: emulated time only ---------------------------------------------------
 *
 * Stock SCP returns the initial interval until one emulated second of ticks has passed,
 * then recalibrates against the host clock. The engine never reads the host clock, so
 * the PIC and LFC tick at their initial interval for ever: emulated time, deterministic
 * (this is what patch 0002 was planned to do; no patch is needed because id_uvc.c only
 * calibrates through these two calls).
 *
 * In cycle mode (VS-02, sx_shim_set_cycle_ns) a tick is one emulated cycle, so calibration
 * answers exactly: `ticksper` ticks per emulated second is 1e9 / cycle_ns / ticksper cycles.
 */
#define SX_NTIMERS 8

static int32 rtc_interval[SX_NTIMERS];
static uint32 shim_cycle_ns; /* 0: instruction mode (stock SCP ticks) */

void sx_shim_set_cycle_ns(uint32 cycle_ns)
{
    shim_cycle_ns = cycle_ns;
}

int32 sim_rtcn_init(int32 time, int32 tmr)
{
    if (time == 0)
        time = 1;
    if (tmr >= 0 && tmr < SX_NTIMERS)
        rtc_interval[tmr] = time;
    return time;
}

int32 sim_rtcn_calb(int32 ticksper, int32 tmr)
{
    if (shim_cycle_ns && ticksper > 0)
        return (int32)(1000000000u / shim_cycle_ns / (uint32)ticksper);
    if (tmr < 0 || tmr >= SX_NTIMERS)
        return 10000;
    return rtc_interval[tmr];
}

/* --- idle ---------------------------------------------------------------------------
 *
 * Instruction mode: stock behaviour with idling disabled (one tick per idle pass).
 * Cycle mode: the wait state does nothing until an event, and only an event can end it, so
 * emulated time jumps straight to the next one (the PIC or LFC tick, or the end of the render
 * slice). This is what patch 0003 was planned to do; it needs no CPU change. The host never
 * sleeps for the CPU.
 */

t_bool sim_idle(uint32 tmr, t_bool sin_cyc)
{
    (void)tmr;
    if (shim_cycle_ns) {
        if (sim_interval > 0)
            sim_interval = 0;
    } else if (sin_cyc) {
        sim_interval = sim_interval - 1;
    }
    return FALSE;
}

t_stat sim_set_idle(UNIT *uptr, int32 val, char *cptr, void *desc)
{
    (void)uptr, (void)val, (void)cptr, (void)desc;
    return SCPE_NOFNC; /* the engine owns time; the host never sleeps for the CPU */
}

t_stat sim_clr_idle(UNIT *uptr, int32 val, char *cptr, void *desc)
{
    (void)uptr, (void)val, (void)cptr, (void)desc;
    return SCPE_OK;
}

t_stat sim_show_idle(FILE *st, UNIT *uptr, int32 val, void *desc)
{
    (void)uptr, (void)val, (void)desc;
    fprintf(st, "idle disabled");
    return SCPE_OK;
}

uint32 sim_brk_test(t_addr bloc, uint32 btyp)
{
    (void)bloc, (void)btyp;
    return 0;
}

/* --- helpers ----------------------------------------------------------------------- */

void sim_printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
}

t_stat get_yn(char *ques, t_stat deflt)
{
    (void)ques;
    return deflt; /* no console: always the default answer */
}

char *get_glyph(char *iptr, char *optr, char mchar)
{
    while (*iptr != 0 && !isspace((unsigned char)*iptr) && *iptr != mchar)
        *optr++ = (char)toupper((unsigned char)*iptr++);
    *optr = 0;
    if (mchar && *iptr == mchar)
        iptr++;
    while (isspace((unsigned char)*iptr))
        iptr++;
    return iptr;
}

/* SCP's get_uint: digits in `radix`, nothing but spaces after, value at most `max`. */
t_value get_uint(char *cptr, uint32 radix, t_value max, t_stat *status)
{
    const char *p = cptr;
    t_value val = 0;
    int digits = 0;
    *status = SCPE_ARG;
    if (radix < 2 || radix > 36)
        return 0;
    while (isspace((unsigned char)*p))
        p++;
    for (; isalnum((unsigned char)*p); p++) {
        int c = toupper((unsigned char)*p);
        uint32 d;
        if (isdigit(c))
            d = (uint32)(c - '0');
        else if (radix <= 10)
            break;
        else
            d = (uint32)(c - 'A' + 10);
        if (d >= radix)
            return 0;
        val = val * radix + d;
        digits++;
    }
    if (!digits)
        return 0;
    while (isspace((unsigned char)*p))
        p++;
    if (*p == 0 && val <= max)
        *status = SCPE_OK;
    return val;
}

/* SCP's fprint_val: PV_RZRO and PV_RSPC pad to the digits `width` bits need in `radix`. */
t_stat fprint_val(FILE *stream, t_value val, uint32 radix, uint32 width, uint32 format)
{
    enum { MAXW = (int)(8 * sizeof(t_value)) };
    char buf[MAXW + 1];
    int d = MAXW;
    memset(buf, format == PV_RZRO ? '0' : ' ', MAXW);
    buf[MAXW] = 0;
    do {
        uint32 digit = (uint32)(val % radix);
        val /= radix;
        buf[--d] = (char)(digit <= 9 ? '0' + digit : 'A' + digit - 10);
    } while (d > 0 && val != 0);
    if (format != PV_LEFT) {
        uint64_t mask = width >= 64 ? UINT64_MAX : (((uint64_t)1 << width) - 1);
        uint64_t w = radix, ow = radix;
        int ndigits = 1;
        while (w < mask && w >= ow) {
            ow = w;
            w *= radix;
            ndigits++;
        }
        if (MAXW - ndigits < d)
            d = MAXW - ndigits;
    }
    return fputs(&buf[d], stream) == EOF ? SCPE_IOERR : SCPE_OK;
}

DEVICE *find_dev_from_unit(UNIT *uptr)
{
    if (uptr == NULL)
        return NULL;
    for (int i = 0; sim_devices[i] != NULL; i++) {
        DEVICE *dptr = sim_devices[i];
        for (uint32 j = 0; j < dptr->numunits; j++)
            if (uptr == dptr->units + j)
                return dptr;
    }
    return NULL;
}

REG *find_reg(char *cptr, char **optr, DEVICE *dptr)
{
    size_t n = 0;
    if (cptr == NULL || dptr == NULL || dptr->registers == NULL)
        return NULL;
    while (isalnum((unsigned char)cptr[n]) || cptr[n] == '*' || cptr[n] == '_')
        n++;
    for (REG *r = dptr->registers; r->name != NULL; r++) {
        size_t k = 0;
        while (k < n && r->name[k] && toupper((unsigned char)cptr[k]) == r->name[k])
            k++;
        if (k == n && r->name[k] == 0) {
            if (optr)
                *optr = cptr + n;
            return r;
        }
    }
    return NULL;
}

/* --- engine entry points ----------------------------------------------------------- */

static t_stat step_svc(UNIT *uptr)
{
    (void)uptr;
    return SCPE_STEP;
}

static UNIT step_unit = {.action = &step_svc};

t_stat sx_shim_reset_all(void)
{
    q_n = 0;
    q_base = 0;
    q_loaded = sim_interval = 0;
    for (int i = 0; sim_devices[i] != NULL; i++) {
        DEVICE *dptr = sim_devices[i];
        if (dptr->reset != NULL) {
            t_stat r = dptr->reset(dptr);
            if (r != SCPE_OK)
                return r;
        }
    }
    return SCPE_OK;
}

t_stat sx_shim_run(int32 ticks)
{
    t_stat r;
    if (ticks <= 0)
        return SCPE_ARG;
    sim_activate(&step_unit, ticks);
    r = sim_instr();
    sim_cancel(&step_unit);
    return r;
}

size_t sx_shim_disasm(uint32 addr, char *buf, size_t n)
{
    t_value v[2] = {0, 0};
    FILE *f;
    t_stat r;
    long len;
    if (n < 32)
        return 0;
    cpu_dev.examine(&v[0], addr, &cpu_unit, 0);
    cpu_dev.examine(&v[1], (addr + 2) & 0xFFFF, &cpu_unit, 0);
    f = fmemopen(buf, n, "w");
    if (f == NULL)
        return 0;
    r = fprint_sym(f, addr, v, &cpu_unit, SWMASK('M'));
    if (r > 0) /* not an instruction: SCP prints the word */
        fprint_val(f, v[0], cpu_dev.dradix, cpu_dev.dwidth, PV_RZRO);
    fflush(f);
    len = ftell(f);
    fclose(f);
    buf[len < 0 ? 0 : (size_t)len < n ? (size_t)len : n - 1] = 0;
    return r > 0 ? 2 : (size_t)(1 - r); /* SCP: fprint_sym returns -(extra bytes) */
}

const char *sx_shim_reason(t_stat r)
{
    if (r > 0 && r < SCPE_BASE)
        return sim_stop_messages[r];
    switch (r) {
    case SCPE_OK:
        return "ok";
    case SCPE_STEP:
        return "Step expired";
    case SCPE_STOP:
        return "Stopped";
    case SCPE_IERR:
        return "Internal error";
    default:
        return "SCP error";
    }
}
