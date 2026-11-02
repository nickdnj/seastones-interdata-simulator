/* sxmidi shared code: clock, stats, report, argument parsing (SP-S2A). */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "sxmidi.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef __APPLE__
#include <mach/mach_time.h>
uint64_t sxmidi_now_ns(void) {
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0) mach_timebase_info(&tb);
    return mach_absolute_time() * tb.numer / tb.denom;
}
#else
uint64_t sxmidi_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
#endif

void sxmidi_sleep_ns(uint64_t ns) {
    struct timespec ts = {(time_t)(ns / 1000000000ull), (long)(ns % 1000000000ull)};
    nanosleep(&ts, NULL);
}

static int cmp_d(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static double pct(const double *sorted, unsigned n, double q) {
    if (n == 0) return 0.0;
    double pos = q / 100.0 * (double)(n - 1);
    unsigned lo = (unsigned)pos;
    unsigned hi = lo + 1 < n ? lo + 1 : lo;
    double f = pos - lo;
    return sorted[lo] * (1.0 - f) + sorted[hi] * f;
}

void sxmidi_stats(const uint64_t *send, const uint64_t *arrive, const uint64_t *ts, unsigned n,
                  sxmidi_selftest_result *r) {
    double *d = calloc(n ? n : 1, sizeof *d);
    double *e = calloc(n ? n : 1, sizeof *e);
    unsigned m = 0, k = 0;
    double sum = 0;
    for (unsigned i = 0; i < n; i++) {
        if (!arrive[i]) continue;
        double us = ((double)arrive[i] - (double)send[i]) / 1000.0;
        d[m++] = us;
        sum += us;
        if (ts && ts[i]) {
            double err = ((double)ts[i] - (double)send[i]) / 1000.0;
            e[k++] = err < 0 ? -err : err;
        }
    }
    qsort(d, m, sizeof *d, cmp_d);
    qsort(e, k, sizeof *e, cmp_d);
    r->received = m;
    r->p50_us = pct(d, m, 50);
    r->p95_us = pct(d, m, 95);
    r->p99_us = pct(d, m, 99);
    r->max_us = m ? d[m - 1] : 0;
    r->mean_us = m ? sum / m : 0;
    r->ts_available = k > 0;
    r->ts_err_p99_us = pct(e, k, 99);
    free(d);
    free(e);
}

void sxmidi_print_selftest(const sxmidi_selftest_result *r) {
    int pass = r->received == r->sent && r->p99_us < 1000.0 && r->unplug_seen;
    printf("{\"harness\":\"sxmidi\",\"spike\":\"S-2a\",\"mode\":\"selftest\",\"backend\":\"%s\",\"seed\":%u,"
           "\"sent\":%u,\"received\":%u,\"out_of_order\":%u,"
           "\"delivery_us\":{\"p50\":%.1f,\"p95\":%.1f,\"p99\":%.1f,\"max\":%.1f,\"mean\":%.1f},"
           "\"driver_timestamp\":%s,\"driver_timestamp_err_p99_us\":%.1f,"
           "\"unplug_seen\":%s,\"unplug_notice_ms\":%.3f,"
           "\"criteria\":{\"timestamp_better_than_1ms_p99\":%s,\"unplug_reported\":%s},\"pass\":%s}\n",
           r->backend, r->seed, r->sent, r->received, r->out_of_order, r->p50_us, r->p95_us, r->p99_us, r->max_us,
           r->mean_us, r->ts_available ? "true" : "false", r->ts_err_p99_us, r->unplug_seen ? "true" : "false",
           r->unplug_ms, r->p99_us < 1000.0 ? "true" : "false", r->unplug_seen ? "true" : "false",
           pass ? "true" : "false");
}

static void usage(void) {
    fprintf(stderr, "usage: sxmidi selftest [--events N] [--spacing-ms MS] [--seed S]\n"
                    "       sxmidi listen [--seconds S] [--sync PATH] [--sync-every-ms MS]\n");
}

int main(int argc, char **argv) {
    if (argc < 2) {
        usage();
        return 2;
    }
    unsigned n = 500, seed = 1974;
    double spacing = 2.0, seconds = 1e9, sync_every = 1000.0;
    const char *sync = NULL;
    for (int i = 2; i < argc; i += 2) {
        const char *a = argv[i], *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!v) { usage(); return 2; }
        if (!strcmp(a, "--events")) n = (unsigned)atoi(v);
        else if (!strcmp(a, "--spacing-ms")) spacing = atof(v);
        else if (!strcmp(a, "--seed")) seed = (unsigned)atoi(v);
        else if (!strcmp(a, "--seconds")) seconds = atof(v);
        else if (!strcmp(a, "--sync")) sync = v;
        else if (!strcmp(a, "--sync-every-ms")) sync_every = atof(v);
        else { usage(); return 2; }
    }
    if (!strcmp(argv[1], "selftest")) {
        if (n == 0 || n > SXMIDI_MAX_EVENTS) n = 500;
        sxmidi_selftest_result r;
        memset(&r, 0, sizeof r);
        r.seed = seed;
        r.sent = n;
        if (sxmidi_selftest(n, spacing, seed, &r) != 0) {
            printf("{\"harness\":\"sxmidi\",\"mode\":\"selftest\",\"pass\":false,\"error\":\"backend failed\"}\n");
            return 1;
        }
        sxmidi_print_selftest(&r);
        return (r.received == r.sent && r.p99_us < 1000.0 && r.unplug_seen) ? 0 : 1;
    }
    if (!strcmp(argv[1], "listen")) return sxmidi_listen(seconds, sync, sync_every);
    usage();
    return 2;
}
