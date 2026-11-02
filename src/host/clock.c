/* clock.c: the host monotonic clock, ns (VS-13). The same clock stamps MIDI arrivals, audio
 * callbacks and tools/host/sxkeys's sends, so latency is a subtraction. As in the S-1a and S-2a
 * harnesses: mach_absolute_time on the Mac, CLOCK_MONOTONIC_RAW on Linux.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#include "sxhost.h"

#if defined(__APPLE__)
#include <mach/mach_time.h>

uint64_t sxh_now_ns(void)
{
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0)
        mach_timebase_info(&tb);
    uint64_t t = mach_absolute_time();
    return t / tb.denom * tb.numer + t % tb.denom * tb.numer / tb.denom;
}
#else
#include <time.h>

uint64_t sxh_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
}
#endif
