/*
 * sxmidi: S-2a MIDI latency and hot-plug harness (SP-S2A). Spike code, not shipped.
 *
 *   sxmidi selftest [--events N] [--spacing-ms MS] [--seed S]
 *       Creates a virtual source, sends N note events at known host times, receives them on
 *       the harness's input, and reports delivery latency (arrival - send) p50/p95/p99/max.
 *       Then removes the virtual source (a simulated unplug) and reports how long the
 *       removal notice (CoreMIDI kMIDIMsgObjectRemoved / ALSA PORT_EXIT) took.
 *       PASS needs p99 < 1 ms and an unplug notice.
 *
 *   sxmidi listen [--seconds S] [--sync PATH] [--sync-every-ms MS]
 *       Bench mode for S-2b. Connects to every MIDI source (and to new ones as they appear)
 *       and prints one JSON line per event on stdout: note-on/off with host arrival time
 *       (and the driver timestamp), source added/removed with host time. With --sync it writes
 *       one byte to a serial device every MS and logs the host time, so the QA rig can map
 *       host time onto the capture clock (tests/latency/midi_analyze.py).
 *
 * Host time is CLOCK_MONOTONIC_RAW on Linux and mach_absolute_time on the Mac, in ns.
 */
#ifndef SXMIDI_H
#define SXMIDI_H

#include <stddef.h>
#include <stdint.h>

#define SXMIDI_MAX_EVENTS 16000 /* event index is encoded in note and velocity */

uint64_t sxmidi_now_ns(void);
void sxmidi_sleep_ns(uint64_t ns);

typedef struct {
    const char *backend;
    unsigned sent;
    unsigned received;
    unsigned out_of_order;
    double p50_us, p95_us, p99_us, max_us, mean_us;
    double ts_err_p99_us;  /* |driver timestamp - send time|, where the driver gives one */
    int ts_available;
    int unplug_seen;
    double unplug_ms;
    unsigned seed;
} sxmidi_selftest_result;

/* Fills percentiles from send/arrive arrays (ns). */
void sxmidi_stats(const uint64_t *send, const uint64_t *arrive, const uint64_t *ts, unsigned n,
                  sxmidi_selftest_result *r);
void sxmidi_print_selftest(const sxmidi_selftest_result *r);

/* Backends */
int sxmidi_selftest(unsigned n, double spacing_ms, unsigned seed, sxmidi_selftest_result *r);
int sxmidi_listen(double seconds, const char *sync_path, double sync_every_ms);

#endif
