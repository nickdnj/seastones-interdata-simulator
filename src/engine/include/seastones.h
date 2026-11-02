/* seastones.h: THE contract between the rig engine and its hosts (ARCHITECTURE 4.3).
 *
 * Version 0 (VS-01). Every public function is tagged with the thread it may be called on:
 *   [RT]          the real-time audio thread only (no allocation, locks, syscalls, logging)
 *   [any thread]  lock-free, safe from any thread, including concurrently with [RT]
 *   [non-RT]      control threads only; may allocate; never concurrently with sx_render
 *
 * The engine is single-instance per process (SIMH keeps CPU state in globals, R-A3):
 * sx_create returns NULL if an engine already exists.
 *
 * Bump SX_API_VERSION on any change to a type or signature here; hosts check it.
 * Version 1 (VS-12): sx_config.max_frames, return and fault codes, speed positions, the
 * snapshot's Method B timestamps (lat_t) and lat_hist bin width, sx_profile, authenticity modes.
 * Version 2 (PM-05, PM-07, PM-08): the patch graph (sx_patch_load, sx_modules_json, SX_CMD_PATCH
 * as a parameter edit), the D/A model's output_hz and strobe_hz and the research jitter in
 * sx_config, SX_CMD_VOLUME, and the snapshot's patch_seq, path_to_out and voices fields.
 * Version 2, backward-compatible addition (round 5): SX_CMD_TEST_TONE appended to sx_cmd_kind.
 * No type, layout or signature changed, so hosts built against version 2 are unaffected.
 * Also added (VS-21): sx_score_load, the score table ("the tape") deposited at X'2000' through
 * SX_CMD_DEPOSIT_TABLE at the next period.
 *
 * Copyright (c) 2026 Nick D. MIT licence.
 */
#ifndef SEASTONES_H
#define SEASTONES_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SX_API_VERSION 2

/* --- configuration ------------------------------------------------------------------ */

typedef struct sx_engine sx_engine;

typedef struct sx_config {
    uint32_t api_version;   /* must be SX_API_VERSION */
    uint32_t sample_rate;   /* frames per second, e.g. 48000 */
    uint32_t mem_bytes;     /* emulated memory, default 32768 */
    uint32_t cycle_ns;      /* emulated cycle length, default 250 (ARCHITECTURE 4.2) */
    uint32_t dac_word_bits; /* converter resolution, default 12 (MACH-3) */
    float dac_range_v;      /* full-scale range, default 10.24 V */
    uint32_t flags;         /* SX_CFG_* */
    uint32_t max_frames;    /* largest sx_render call, default 4096; larger calls are split */
    float dac_output_hz;    /* `analog` mode: the converter's output low-pass, default 2000 Hz */
    float dac_strobe_hz;    /* `strobed` mode: the D/A update clock, default 1000 Hz */
    float jitter_ms;        /* research-only `jitter` mode: sigma, default 1 ms (test profile) */
} sx_config;

#define SX_CFG_TEST_HOOKS 0x1u /* test profile only; the release gate rejects it (VS-27) */

/* --- return codes and faults ------------------------------------------------------------ */

#define SX_OK 0
#define SX_E_ARG (-1)    /* bad argument or configuration */
#define SX_E_HASH (-2)   /* image_hash_mismatch (ASM-09): the image is refused, silently */
#define SX_E_STATE (-3)  /* not possible now (e.g. a second engine in this process) */
#define SX_E_AGAIN (-11) /* the command queue is full: try again (EAGAIN) */

/* sx_snapshot.faults bits (ARCHITECTURE 8.2; the supervisor, VS-16, adds the rest) */
#define SX_FAULT_IMAGE_MISSING 0x1u
#define SX_FAULT_IMAGE_HASH 0x2u
#define SX_FAULT_DSP 0x4u /* non-finite audio was caught and the module reset */
#define SX_FAULT_PROGRAM_STALLED 0x8u
#define SX_FAULT_CPU_STOPPED 0x10u /* the CPU stopped itself (HALT, a trap with stops on) */

/* --- speed positions (SX_CMD_SPEED a; ARCHITECTURE 7) ------------------------------------- */

enum sx_speed {
    SX_SPEED_RUN = 0, /* x 1 */
    SX_SPEED_SLOW1,   /* / 10 */
    SX_SPEED_SLOW2,   /* / 100 */
    SX_SPEED_SLOW3,   /* / 1000 */
    SX_SPEED_CRAWL,   /* / 10000 */
    SX_SPEED_SINGLE,  /* STEP executes exactly one instruction */
    SX_SPEED_NPOS,
    SX_SPEED_DIVISOR = 100 /* b: a raw divisor, 1..100000 (calibration, tests) */
};

/* --- authenticity modes (SX_CMD_AUTH_MODE a; ARCHITECTURE 6.4) ------------------------------ */

enum sx_auth {
    SX_AUTH_AUTHENTIC = 0, /* the default: each write is a step at its exact frame */
    SX_AUTH_ANALOG = 1,
    SX_AUTH_STROBED = 2,
    SX_AUTH_JITTER = 3 /* research only: refused by the production profile (VS-27) */
};

/* --- images ------------------------------------------------------------------------- */

typedef struct sx_segment {
    uint16_t addr;   /* byte address, even */
    uint16_t nwords; /* halfwords in `words` */
    const uint16_t *words;
} sx_segment;

typedef struct sx_image {
    const sx_segment *segments;
    uint32_t nsegments;
    uint16_t entry_pc;
    uint16_t entry_psw;
    uint8_t sha256[32]; /* of the segments, checked at load (ASM-09) */
} sx_image;

/* --- keys ----------------------------------------------------------------------------- */

typedef enum sx_key_source {
    SX_KEYS_MIDI = 0,
    SX_KEYS_TOUCH = 1,
    SX_KEYS_DEV_QWERTY = 2,
    SX_KEYS_NSOURCES = 3
} sx_key_source;

/* --- commands (SPSC ring, applied at the start of the next period) -------------------- */

typedef enum sx_cmd_kind {
    SX_CMD_RUN = 1,
    SX_CMD_HALT,
    SX_CMD_STEP,       /* SINGLE: execute exactly one instruction at the next period */
    SX_CMD_SPEED,      /* a: enum sx_speed position; SX_SPEED_DIVISOR with b = divisor */
    SX_CMD_RESET_HOME, /* reload the image, clear devices and keys-seen, RUN */
    SX_CMD_SR_SET,     /* a: switch register value, bounds-checked by the host */
    SX_CMD_DEPOSIT_TABLE,
    SX_CMD_PATCH,     /* a parameter edit (patch.param): a module index, b parameter, f value */
    SX_CMD_CEILING,   /* f: staff ceiling, dBFS */
    SX_CMD_MUTE,      /* a: 1 mute, 0 unmute */
    SX_CMD_AUTH_MODE, /* a: authenticity mode (ARCHITECTURE 6.4) */
    SX_CMD_VOLUME,    /* f: visitor volume, dB, clamped to at most 0 (never above the ceiling) */
    SX_CMD_TEST_TONE  /* staff diagnostic, OFF by default: a 1 on, 0 off; b Hz (0: 1000, else
                       * 100-4000); f dBFS (0: -20, else -60 to -12). A sine mixed into the bus
                       * before the safety chain, 10 ms ramps; the only sound not from the D/A */
} sx_cmd_kind;

typedef struct sx_cmd {
    uint32_t kind; /* sx_cmd_kind */
    uint32_t a;
    uint32_t b;
    float f;
} sx_cmd;

/* --- snapshot (ARCHITECTURE 4.4; seqlock, published every period) ---------------------- */

#define SX_DAC_CHANNELS 16
#define SX_KEY_ROWS 8
#define SX_SCOPE_POINTS 512
#define SX_LAT_BINS 32
#define SX_LAT_BIN_US 250 /* lat_hist bin width; the last bin also counts everything later */

/* lat_t: Method B timestamps of the most recent key press, in frames since create (LAT-02,
 * LAT-08): key bitmap set (host call), key latched (period start), first D/A or gate write after
 * it, onset (output first above -50 dBFS after a gate rise). 0 = not seen yet. */
enum { SX_LAT_ARRIVAL = 0, SX_LAT_LATCH, SX_LAT_FIRST_WRITE, SX_LAT_ONSET, SX_LAT_N };

typedef struct sx_snapshot {
    uint64_t seq;
    uint64_t frames; /* frames rendered since create */
    uint64_t cycles; /* emulated cycles since load */
    uint16_t pc, psw;
    uint16_t r[16];
    uint8_t cc;
    uint32_t dr;
    uint8_t drx;
    uint16_t sr;
    uint8_t keys_raw[SX_KEY_ROWS];  /* what the device would return now (staff only) */
    uint8_t keys_seen[SX_KEY_ROWS]; /* the last value the program actually read per row */
    uint16_t dac_code[SX_DAC_CHANNELS];
    float dac_volts[SX_DAC_CHANNELS];
    uint16_t gates;
    uint8_t halted, waiting, muted;
    uint32_t speed;
    uint32_t faults; /* SX_FAULT_* bits (ARCHITECTURE 8.2) */
    uint32_t xruns;
    float scope[SX_SCOPE_POINTS];
    uint32_t lat_hist[SX_LAT_BINS]; /* key latch to first write, SX_LAT_BIN_US bins */
    uint64_t lat_t[SX_LAT_N];
    uint32_t patch_seq;  /* patches applied since create (1: the built-in) */
    uint8_t path_to_out; /* 0: no path from a D/A or gate line reaches an out (PATCH-4 hint) */
    uint8_t fading;      /* a patch change's 5 ms crossfade is running */
    uint32_t auth;       /* enum sx_auth in force */
} sx_snapshot;

/* --- the Phase 2 seam (P2-3): every device write with its emulated time ----------------- */

typedef void (*sx_io_sink)(void *ctx, uint64_t emu_cycle, uint8_t dev, uint8_t ch, uint16_t val);

/* --- functions -------------------------------------------------------------------------- */

sx_engine *sx_create(const sx_config *cfg);                       /* [non-RT] */
void sx_destroy(sx_engine *e);                                    /* [non-RT] */
int sx_load_image(sx_engine *e, const sx_image *img);             /* [non-RT] SX_OK, SX_E_* */
void sx_render(sx_engine *e, float *out_lr, uint32_t frames);     /* [RT] */
void sx_keys_set(sx_engine *e, sx_key_source src, uint64_t bits); /* [any thread] */
int sx_command(sx_engine *e, const sx_cmd *cmd);                  /* [any thread] -EAGAIN if full */
int sx_snapshot_read(sx_engine *e, sx_snapshot *out);             /* [any thread] seqlock copy */
size_t sx_disasm(sx_engine *e, uint16_t addr, char *buf, size_t n); /* [non-RT] SIMH fprint_sym */
void sx_set_io_sink(sx_engine *e, sx_io_sink sink, void *ctx);      /* [non-RT] */
uint32_t sx_api_version(void);                                      /* [any thread] */

/* The patch graph (PM-05). sx_patch_load parses `seastones.graph/1` text (src/engine/api/patch.c;
 * sxpatch compiles seastones.patch/1 JSON to it), builds the graph and queues it: the render
 * swaps it in at the next period boundary with a 5 ms crossfade, held notes carrying over.
 * Returns SX_OK; SX_E_ARG with "line N: why" in err; SX_E_AGAIN while the last swap is still
 * pending (try again after a period). */
int sx_patch_load(sx_engine *e, const char *t, size_t n, char *err, size_t en); /* [non-RT] */
/* The module registry as JSON (seastones.modules/1): writes at most n bytes, returns the full
 * length (call with n = 0 to size the buffer). */
size_t sx_modules_json(char *buf, size_t n); /* [any thread] */
/* The score table (VS-21; sxscore.compile writes it): n halfwords deposited at X'2000' at the
 * next period start, as an operator would load a tape; word 0 is replaced by a new generation
 * number so the program notices. SX_E_ARG if n is under 3 or past the score area (24 KB) or the
 * memory; SX_E_AGAIN while the previous one is still waiting. Switches 0-3 pick play (0), score
 * (1) or both (2). */
int sx_score_load(sx_engine *e, const uint16_t *words, uint32_t n); /* [non-RT] */
/* KEYS row reads the program has made since create (wraps). The host samples it after each
 * render to report the scan rate (state.scan_hz). Added by the host lane (VS-14) as an addition,
 * not a change, so SX_API_VERSION is unchanged by it; exact on the render thread, a relaxed read
 * elsewhere */
uint32_t sx_keys_reads_count(sx_engine *e); /* [any thread] */
const char *sx_profile(void); /* [any thread] "production" or "test" (VS-27; hello reports it) */

#ifdef __cplusplus
}
#endif

#endif /* SEASTONES_H */
