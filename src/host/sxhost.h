/* sxhost.h: the native host around the rig engine (VS-13; ARCHITECTURE 4.1, 4.5; ADR-002).
 *
 * rigd (Python) loads one shared library, libsxhost, that holds the engine (libseastones,
 * linked whole) and these C helpers. C threads do all the real-time work, so no Python ever runs
 * on the audio or the MIDI thread:
 *
 *   audio   miniaudio (vendored, src/host/vendor/miniaudio): CoreAudio on macOS, ALSA on Linux,
 *           or the paced "null" device for tests. The device callback renders the engine: the
 *           engine's clock is the audio sample count. The callback is RT-safe (src/host/rt/,
 *           checked by scripts/rt-lint.py).
 *   midi    CoreMIDI on macOS, the ALSA sequencer on Linux. Every source has its own key bitmap;
 *           their OR is the engine's MIDI source. A vanished source clears its bitmap at once
 *           (all notes off on unplug, INPUT-3), and new sources are connected as they appear.
 *   taps    lock-free rings the control thread drains: a PC sample per engine period (lamps,
 *           heat band, scan rate), the callback clock (frame to host time, for latency), and an
 *           optional capture of the output exactly as handed to the device.
 *
 * Thread tags as in seastones.h: [non-RT] control thread (rigd's one writer), [any thread].
 * Nothing here is called from the audio thread except through the device callback.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SXHOST_H
#define SXHOST_H

#include <stdint.h>

#include "seastones.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SXH_API_VERSION 1

#define SXH_OK 0
#define SXH_E_ARG (-1)    /* bad argument */
#define SXH_E_STATE (-3)  /* not possible now (already open, not open) */
#define SXH_E_DEVICE (-4) /* the audio or MIDI system refused (no device, no permission) */

/* --- audio ------------------------------------------------------------------------------- */

#define SXH_AUDIO_SILENT_DEVICE                                                                    \
    0x1u /* render and tap as usual, but give the device zeros:                                    \
            the timing is the real device's, the room stays quiet */

typedef struct sxh_audio_cfg {
    const char *backend; /* "auto" (CoreAudio on macOS, ALSA on Linux) or "null" (paced, no
                            hardware: tests and CI). NULL means "auto" */
    const char *device;  /* NULL or "" for the default output; else a substring of a device's
                            name or id, e.g. "hw:1,0" on the station */
    uint32_t rate;       /* frames per second; 0 = the device's own rate */
    uint32_t period;     /* device period in frames (ADR-002: 128) */
    uint32_t periods;    /* periods in the device buffer (ADR-002: 2) */
    uint32_t sub_period; /* engine period inside a callback, in frames (0 = period); smaller
                            gives more PC samples per second, the same latency */
    uint32_t flags;      /* SXH_AUDIO_* */
} sxh_audio_cfg;

typedef struct sxh_audio_info {
    char backend[32];
    char device[128];
    uint32_t rate;   /* the rate the engine must be created with */
    uint32_t period; /* what the device granted */
    uint32_t periods;
    uint32_t latency_frames; /* the device's reported output latency (HAL device + safety +
                                stream + buffer on CoreAudio; the buffer on ALSA) */
} sxh_audio_info;

typedef struct sxh_audio_status {
    uint32_t open, running;
    uint32_t lost;   /* the device stopped without being asked (unplug, error) */
    uint64_t frames; /* frames rendered by the engine through the callback */
    uint64_t callbacks;
    uint64_t late_callbacks; /* interval over 1.5 periods: the host's xrun proxy (not counted
                                on the null device, whose timer wakes in bursts) */
    uint64_t max_interval_ns;
    uint64_t last_callback_ns; /* host monotonic time of the last callback start */
    int32_t sched_policy;      /* the audio thread's, seen on its first callback (-1 unknown) */
    int32_t sched_priority;
    uint64_t capture_frames;      /* frames written to the capture file */
    uint64_t capture_dropped;     /* frames the capture ring could not hold (must stay 0) */
    uint64_t capture_first_frame; /* engine frame of the capture's first sample (or ~0) */
    uint32_t frozen;              /* test profile: the freeze hook is on */
} sxh_audio_status;

/* Open the device (not started). Fills `info`, whose rate the engine must be created with. */
int sxh_audio_open(const sxh_audio_cfg *cfg, sxh_audio_info *info); /* [non-RT] */
/* Start rendering `e` from the device callback. The engine must use info.rate. */
int sxh_audio_start(sx_engine *e); /* [non-RT] */
/* Stop the device and close it. Afterwards the engine may be used from the control thread. */
void sxh_audio_close(void);                        /* [non-RT] */
void sxh_audio_status_read(sxh_audio_status *out); /* [any thread] */

/* Capture the output, as handed to the device (before SILENT_DEVICE zeroes it), to `path` as
 * raw little-endian float32, channel 0 only, one sample per frame from the frame the capture
 * starts (status.capture_first_frame). The file is appended to, so a reopened device adds a
 * segment; the caller notes where each starts. A writer thread drains a lock-free ring. Never a
 * WAV: nothing audio-like is made for the repo (RE-1); tests write it to build/ or a temp folder
 * and delete it. */
int sxh_capture_start(const char *path); /* [non-RT] */
void sxh_capture_stop(void);             /* [non-RT] flushes and closes */

/* One sample per engine period: where the CPU was at the period's end. */
typedef struct sxh_sample {
    uint64_t frame;      /* engine frames at the period's end */
    uint32_t keys_reads; /* KEYS row reads so far (sx_keys_reads_count): the scan rate */
    uint16_t pc;
    uint16_t halted;
} sxh_sample;

/* Copy up to `max` samples not yet read; returns how many. One reader (the control thread). */
uint32_t sxh_samples_read(sxh_sample *out, uint32_t max); /* [non-RT] */

/* Host monotonic time (ns) at which engine frame `frame` was handed to the device, from the
 * callback clock ring; 0 if that frame is too old or not rendered yet. Add info.latency_frames
 * for the time it leaves the converter. */
uint64_t sxh_frame_host_ns(uint64_t frame); /* [any thread] */

/* Host monotonic clock, ns (mach_absolute_time on the Mac, CLOCK_MONOTONIC_RAW on Linux): the
 * same clock as the MIDI arrival stamps and tools/host/sxkeys. */
uint64_t sxh_now_ns(void); /* [any thread] */

/* --- MIDI -------------------------------------------------------------------------------- */

typedef struct sxh_midi_status {
    uint32_t running;
    uint32_t sources; /* sources connected now */
    uint64_t bits;    /* OR of the sources' keys, before the held-key mask */
    uint64_t masked;  /* keys masked until released (HOME, the 60 s rule) */
    uint64_t events;  /* note on and off received */
    uint64_t ignored; /* notes outside the keyboard, and other messages */
    uint64_t plugs, unplugs;
    uint64_t last_unplug_ns;
    uint64_t last_note_on_ns; /* arrival time of the last note-on, host clock */
    int32_t last_note_on;     /* its note number */
    uint32_t gen;             /* bumps on every plug and unplug */
} sxh_midi_status;

/* MIDI note `base_note` is key 0; keys are 0 .. nkeys-1; other notes are ignored (VS-29's
 * default; the program's own pitch table says key 0 is note 48). Velocity is ignored, note-on
 * with velocity 0 is note-off, CC 120 and CC 123 release that source's keys. */
int sxh_midi_start(sx_engine *e, int32_t base_note, uint32_t nkeys); /* [non-RT] */
void sxh_midi_stop(void);                                            /* [non-RT] */
/* Mask these keys until each is released on every source (HOME, the 60 s held-key rule). */
void sxh_midi_mask(uint64_t bits); /* [any thread] */
/* Connect only sources whose name contains `part` (NULL or "": every source, the station's
 * setting). For tests and developers sharing a machine whose other virtual keyboards would
 * otherwise play this rig. Call before sxh_midi_start. */
void sxh_midi_filter(const char *part);          /* [non-RT] */
void sxh_midi_status_read(sxh_midi_status *out); /* [any thread] */

/* --- test profile ------------------------------------------------------------------------ */

/* Freeze the audio thread's work (FLT-10): the callback gives the device zeros and does not
 * render, so the engine's frame counter stops. Present only in the test profile; the host
 * reports which profile it was built for. */
void sxh_test_freeze(uint32_t on); /* [any thread] */
/* Stop the audio device without being asked, as a USB unplug does (FLT-06): status.lost
 * goes to 1 and rigd must name audio_device_missing and reopen it. Test profile only. */
void sxh_test_unplug(void); /* [non-RT] */
/* Add n to the late-callback counter, as an underrun storm would (QA-ADV-06). Test only. */
void sxh_test_late(uint32_t n); /* [any thread] */
const char *sxh_profile(void);  /* [any thread] "production" or "test" */
uint32_t sxh_api_version(void); /* [any thread] */

#ifdef __cplusplus
}
#endif

#endif /* SXHOST_H */
