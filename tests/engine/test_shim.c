/* test_shim.c: unit tests for src/engine/shim/scp_shim.c (VS-01; CNF-12 short form).
 *
 * Plain asserts, no framework. Built and run by `make test-engine`, and under ASan and
 * UBSan by `make sanitize`. Each CHECK prints the failing expression and line.
 */
#include "cycles.h"
#include "scp_shim.h"

#include <stdio.h>
#include <string.h>

extern UNIT cpu_unit;
extern DEVICE cpu_dev;
extern uint32 PC, PSW;
extern UNIT lfc_unit, pic_unit;
extern int32 pic_ric, pic_cic;
extern uint16 pic_time[4];
extern void pic_sched(t_bool strt);

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

static int order[8];
static int norder;

static t_stat svc_a(UNIT *u)
{
    (void)u;
    order[norder++] = 1;
    return SCPE_OK;
}

static t_stat svc_b(UNIT *u)
{
    (void)u;
    order[norder++] = 2;
    return SCPE_OK;
}

static t_stat svc_c(UNIT *u)
{
    (void)u;
    order[norder++] = 3;
    return SCPE_OK;
}

static UNIT ua = {.action = &svc_a};
static UNIT ub = {.action = &svc_b};
static UNIT uc = {.action = &svc_c};

/* Count interval ticks the way the CPU does, firing events when due. */
static void tick(int32 n)
{
    while (n-- > 0) {
        if (sim_interval <= 0)
            sim_process_event();
        sim_interval--;
    }
    if (sim_interval <= 0)
        sim_process_event();
}

static void test_event_queue(void)
{
    sx_shim_reset_all();
    CHECK(sim_is_active(&lfc_unit) > 0); /* power-up reset starts the line clock, as SCP */
    sim_cancel(&lfc_unit);               /* an empty queue for the ordering checks */
    sim_cancel(&ua);                     /* not queued: harmless */
    norder = 0;
    uint32 t0 = sim_grtime();
    CHECK(sim_activate(&ua, 10) == SCPE_OK);
    CHECK(sim_activate(&ub, 5) == SCPE_OK);
    CHECK(sim_activate(&uc, 10) == SCPE_OK); /* same time as ua: runs after it */
    CHECK(sim_activate(&ua, 1) == SCPE_OK);  /* already active: left alone, like SCP */
    CHECK(sim_is_active(&ub) == 6);          /* time to go + 1 */
    CHECK(sim_is_active(&ua) == 11);
    CHECK(sim_activate(&ua, -1) == SCPE_IERR);
    tick(4);
    CHECK(norder == 0);
    tick(1);
    CHECK(norder == 1 && order[0] == 2);
    tick(5);
    CHECK(norder == 3 && order[1] == 1 && order[2] == 3);
    CHECK(sim_is_active(&ua) == 0);
    CHECK(sim_grtime() - t0 == 10);

    sim_activate(&ua, 3);
    sim_activate(&ub, 7);
    sim_cancel(&ua);
    CHECK(sim_is_active(&ua) == 0 && sim_is_active(&ub) == 8);
    norder = 0;
    tick(7);
    CHECK(norder == 1 && order[0] == 2);
    CHECK(sim_interval == NOQUEUE_WAIT); /* empty queue: SCP's idle wait */
}

static void test_rtc_and_idle(void)
{
    CHECK(sim_rtcn_init(0, 0) == 1);
    CHECK(sim_rtcn_init(8000, 0) == 8000);
    for (int i = 0; i < 200; i++) /* stock would recalibrate against the host here */
        CHECK(sim_rtcn_calb(60, 0) == 8000);
    CHECK(sim_rtcn_calb(60, 99) == 10000);
    int32 before = sim_interval;
    CHECK(sim_idle(0, TRUE) == FALSE);
    CHECK(sim_interval == before - 1);
    CHECK(sim_idle(0, FALSE) == FALSE);
    CHECK(sim_interval == before - 1);
    CHECK(sim_set_idle(NULL, 0, NULL, NULL) == SCPE_NOFNC);
    CHECK(sim_clr_idle(NULL, 0, NULL, NULL) == SCPE_OK);
    CHECK(sim_brk_test(0x100, SWMASK('E')) == 0);
}

static void test_parse_and_print(void)
{
    t_stat r;
    char in[32], out[32];
    strcpy(in, "1f");
    CHECK(get_uint(in, 16, 0xFFFF, &r) == 0x1F && r == SCPE_OK);
    strcpy(in, "1G");
    get_uint(in, 16, 0xFFFF, &r);
    CHECK(r == SCPE_ARG);
    strcpy(in, "70000");
    get_uint(in, 10, 65536, &r);
    CHECK(r == SCPE_ARG);
    strcpy(in, " 42 ");
    CHECK(get_uint(in, 10, 100, &r) == 42 && r == SCPE_OK);
    strcpy(in, "");
    get_uint(in, 10, 100, &r);
    CHECK(r == SCPE_ARG);

    strcpy(in, "abc,def");
    char *rest = get_glyph(in, out, ',');
    CHECK(strcmp(out, "ABC") == 0 && strcmp(rest, "def") == 0);

    char buf[64];
    FILE *f = fmemopen(buf, sizeof buf, "w");
    fprint_val(f, 0xA5, 16, 16, PV_RZRO);
    fputc('|', f);
    fprint_val(f, 0xA5, 16, 16, PV_LEFT);
    fputc('|', f);
    fprint_val(f, 0xA5, 16, 16, PV_RSPC);
    fputc('|', f);
    fprint_val(f, 7, 16, 4, PV_RZRO);
    fputc('|', f);
    fprint_val(f, 0, 8, 16, PV_RZRO);
    fputc(0, f);
    fclose(f);
    CHECK(strcmp(buf, "00A5|A5|  A5|7|000000") == 0);

    char name[8];
    strcpy(name, "PC");
    CHECK(find_reg(name, NULL, &cpu_dev) != NULL);
    strcpy(name, "NOPE");
    CHECK(find_reg(name, NULL, &cpu_dev) == NULL);
    CHECK(find_reg(NULL, NULL, &cpu_dev) == NULL);
    CHECK(find_dev_from_unit(&cpu_unit) == &cpu_dev);
    CHECK(find_dev_from_unit(&ua) == NULL);
    CHECK(find_dev_from_unit(NULL) == NULL);
    char q[8] = "Q?";
    CHECK(get_yn(q, TRUE) == TRUE);
}

static void test_run_and_disasm(void)
{
    sx_shim_reset_all();
    /* X'100': LHI R1,1 / AIS R1,1 / B X'104' (a tight counting loop) */
    const uint16 prog[] = {0xC810, 0x0001, 0x2611, 0x4300, 0x0104};
    for (uint32 i = 0; i < 5; i++)
        cpu_dev.deposit(prog[i], 0x100 + 2 * i, &cpu_unit, 0);
    PC = 0x100;
    PSW = 0;
    uint32 t0 = sx_shim_time();
    CHECK(sx_shim_run(1001) == SCPE_STEP);
    CHECK(sx_shim_time() - t0 == 1001);
    CHECK(sx_shim_run(0) == SCPE_ARG);
    CHECK(strcmp(sx_shim_reason(SCPE_STEP), "Step expired") == 0);
    CHECK(strcmp(sx_shim_reason(4), "Wait state") == 0);
    CHECK(strcmp(sx_shim_reason(SCPE_OK), "ok") == 0);

    char buf[64];
    CHECK(sx_shim_disasm(0x100, buf, sizeof buf) == 4 && strcmp(buf, "LHI R1,1") == 0);
    CHECK(sx_shim_disasm(0x104, buf, sizeof buf) == 2 && strcmp(buf, "AIS R1,1") == 0);
    CHECK(sx_shim_disasm(0x106, buf, sizeof buf) == 4 && strcmp(buf, "B 104") == 0);
    cpu_dev.deposit(0x0000, 0x200, &cpu_unit, 0);
    CHECK(sx_shim_disasm(0x200, buf, sizeof buf) == 2 && strcmp(buf, "0000") == 0);
    CHECK(sx_shim_disasm(0x100, buf, 8) == 0); /* buffer too small */

    /* Wait state with interrupts off: idle passes count ticks and the run returns. */
    PSW = 0x8000;
    t0 = sx_shim_time();
    CHECK(sx_shim_run(500) == SCPE_STEP);
    CHECK(sx_shim_time() - t0 == 500);
}

/* ADR-008 condition 3 / CNF-11 (shim half): in cycle mode the PIC and LFC tick in emulated
 * time, never host time, and the wait state jumps to the next event. */
static void test_cycle_mode_clocks(void)
{
    sx_cycles_configure(250u); /* 4 cycles per microsecond */
    CHECK(pic_time[0] == 4 && pic_time[1] == 40 && pic_time[2] == 400 && pic_time[3] == 4000);
    CHECK(sim_rtcn_calb(1000, 1) == 4000); /* PIC 1 ms mode: 1000 ticks per second */
    CHECK(sim_rtcn_calb(120, 0) == 33333); /* LFC: 120 per second (60 Hz mains) */
    CHECK(lfc_unit.wait == 33333);
    for (int i = 0; i < 50; i++) /* calibration never drifts: no host clock */
        CHECK(sim_rtcn_calb(120, 0) == 33333);
    sx_shim_reset_all();
    CHECK(sim_is_active(&lfc_unit) == 33333 + 1); /* first LFC tick after 1/120 s */

    /* PIC intervals: rate field bit 1, 2, 4 or 8 selects 1, 10, 100 or 1000 us units
     * (id_uvc.c pic_map); a count of 7 units is 7 x that in cycles. */
    static const int32 rate_bits[4] = {1, 2, 4, 8};
    /* 1 ms mode (a whole number of ms) runs on the calibrated timer: one tick per 1 ms. */
    static const int32 expect[4] = {28, 280, 2800, 4000};
    for (int r = 0; r < 4; r++) {
        sim_cancel(&pic_unit);
        pic_ric = (rate_bits[r] << 12) | 7;
        pic_cic = 7;
        pic_sched(TRUE);
        CHECK(sim_is_active(&pic_unit) == expect[r] + 1);
    }
    sim_cancel(&pic_unit);

    /* The wait state: time jumps to the next event, and the LFC keeps its 33333-cycle period
     * (100000 cycles in: ticks at 33333, 66666, 99999, next at 133332). */
    const uint16 wait[] = {0x4300, 0x0100}; /* B X'100' (never reached while waiting) */
    for (uint32 i = 0; i < 2; i++)
        cpu_dev.deposit(wait[i], 0x100 + 2 * i, &cpu_unit, 0);
    PC = 0x100;
    PSW = 0x8000; /* wait, interrupts off */
    uint64_t t0 = sx_shim_now64();
    CHECK(sx_shim_run(100000) == SCPE_STEP);
    CHECK(sx_shim_now64() - t0 == 100000u); /* exactly: idle never overshoots an event */
    CHECK(sim_is_active(&lfc_unit) == 133332 - 100000 + 1);
    sx_cycles_configure(0); /* back to instruction mode for the other tests */
    CHECK(pic_time[0] == 1 && pic_time[3] == 1000 && lfc_unit.wait == 8000);
}

int main(void)
{
    test_event_queue();
    test_rtc_and_idle();
    test_parse_and_print();
    test_run_and_disasm();
    test_cycle_mode_clocks();
    printf("test_shim: %d checks, %d failures\n", checks, failures);
    return failures != 0;
}
