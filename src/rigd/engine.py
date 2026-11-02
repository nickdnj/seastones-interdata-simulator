"""The engine and the native host, through cffi in ABI mode (VS-14; ARCHITECTURE 4.5).

ABI mode needs no compiler on the station. The declarations below copy
``src/engine/include/seastones.h`` and ``src/host/sxhost.h`` field for field;
``tests/rigd/test_engine_binding.py`` compiles a probe that prints the C sizes and offsets and
fails if any differ, so the two cannot drift silently.

No Python runs on a real-time thread: the audio callback and the MIDI threads are C
(src/host/). This module is called from rigd's one control thread only.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from cffi import FFI

ROOT = Path(__file__).resolve().parents[2]

CDEF = r"""
typedef struct sx_engine sx_engine;

typedef struct sx_config {
    uint32_t api_version;
    uint32_t sample_rate;
    uint32_t mem_bytes;
    uint32_t cycle_ns;
    uint32_t dac_word_bits;
    float dac_range_v;
    uint32_t flags;
    uint32_t max_frames;
    float dac_output_hz;
    float dac_strobe_hz;
    float jitter_ms;
} sx_config;

typedef struct sx_segment {
    uint16_t addr;
    uint16_t nwords;
    const uint16_t *words;
} sx_segment;

typedef struct sx_image {
    const sx_segment *segments;
    uint32_t nsegments;
    uint16_t entry_pc;
    uint16_t entry_psw;
    uint8_t sha256[32];
} sx_image;

typedef struct sx_cmd {
    uint32_t kind;
    uint32_t a;
    uint32_t b;
    float f;
} sx_cmd;

typedef struct sx_snapshot {
    uint64_t seq;
    uint64_t frames;
    uint64_t cycles;
    uint16_t pc, psw;
    uint16_t r[16];
    uint8_t cc;
    uint32_t dr;
    uint8_t drx;
    uint16_t sr;
    uint8_t keys_raw[8];
    uint8_t keys_seen[8];
    uint16_t dac_code[16];
    float dac_volts[16];
    uint16_t gates;
    uint8_t halted, waiting, muted;
    uint32_t speed;
    uint32_t faults;
    uint32_t xruns;
    float scope[512];
    uint32_t lat_hist[32];
    uint64_t lat_t[4];
    uint32_t patch_seq;
    uint8_t path_to_out;
    uint8_t fading;
    uint32_t auth;
} sx_snapshot;

sx_engine *sx_create(const sx_config *cfg);
void sx_destroy(sx_engine *e);
int sx_load_image(sx_engine *e, const sx_image *img);
void sx_render(sx_engine *e, float *out_lr, uint32_t frames);
void sx_keys_set(sx_engine *e, int src, uint64_t bits);
int sx_command(sx_engine *e, const sx_cmd *cmd);
int sx_snapshot_read(sx_engine *e, sx_snapshot *out);
size_t sx_disasm(sx_engine *e, uint16_t addr, char *buf, size_t n);
uint32_t sx_api_version(void);
const char *sx_profile(void);
uint32_t sx_keys_reads_count(sx_engine *e);
int sx_patch_load(sx_engine *e, const char *t, size_t n, char *err, size_t en);
size_t sx_modules_json(char *buf, size_t n);
void sx_test_inject(sx_engine *e, uint32_t what);

typedef struct sxh_audio_cfg {
    const char *backend;
    const char *device;
    uint32_t rate;
    uint32_t period;
    uint32_t periods;
    uint32_t sub_period;
    uint32_t flags;
} sxh_audio_cfg;

typedef struct sxh_audio_info {
    char backend[32];
    char device[128];
    uint32_t rate;
    uint32_t period;
    uint32_t periods;
    uint32_t latency_frames;
} sxh_audio_info;

typedef struct sxh_audio_status {
    uint32_t open, running;
    uint32_t lost;
    uint64_t frames;
    uint64_t callbacks;
    uint64_t late_callbacks;
    uint64_t max_interval_ns;
    uint64_t last_callback_ns;
    int32_t sched_policy;
    int32_t sched_priority;
    uint64_t capture_frames;
    uint64_t capture_dropped;
    uint64_t capture_first_frame;
    uint32_t frozen;
} sxh_audio_status;

typedef struct sxh_sample {
    uint64_t frame;
    uint32_t keys_reads;
    uint16_t pc;
    uint16_t halted;
} sxh_sample;

typedef struct sxh_midi_status {
    uint32_t running;
    uint32_t sources;
    uint64_t bits;
    uint64_t masked;
    uint64_t events;
    uint64_t ignored;
    uint64_t plugs, unplugs;
    uint64_t last_unplug_ns;
    uint64_t last_note_on_ns;
    int32_t last_note_on;
    uint32_t gen;
} sxh_midi_status;

int sxh_audio_open(const sxh_audio_cfg *cfg, sxh_audio_info *info);
int sxh_audio_start(sx_engine *e);
void sxh_audio_close(void);
void sxh_audio_status_read(sxh_audio_status *out);
int sxh_capture_start(const char *path);
void sxh_capture_stop(void);
uint32_t sxh_samples_read(sxh_sample *out, uint32_t max);
uint64_t sxh_frame_host_ns(uint64_t frame);
uint64_t sxh_now_ns(void);
int sxh_midi_start(sx_engine *e, int32_t base_note, uint32_t nkeys);
void sxh_midi_stop(void);
void sxh_midi_mask(uint64_t bits);
void sxh_midi_filter(const char *part);
void sxh_midi_status_read(sxh_midi_status *out);
void sxh_test_freeze(uint32_t on);
void sxh_test_unplug(void);
void sxh_test_late(uint32_t n);
const char *sxh_profile(void);
uint32_t sxh_api_version(void);
"""

SX_API_VERSION = 2
SXH_API_VERSION = 1

# seastones.h
SX_OK, SX_E_ARG, SX_E_HASH, SX_E_STATE, SX_E_AGAIN = 0, -1, -2, -3, -11
SX_CFG_TEST_HOOKS = 0x1
FAULT_IMAGE_MISSING = 0x1
FAULT_IMAGE_HASH = 0x2
FAULT_DSP = 0x4
FAULT_PROGRAM_STALLED = 0x8
FAULT_CPU_STOPPED = 0x10
SPEED_RUN, SPEED_SINGLE, SPEED_DIVISOR = 0, 5, 100
KEYS_MIDI, KEYS_TOUCH, KEYS_DEV_QWERTY = 0, 1, 2
CMD_RUN, CMD_HALT, CMD_STEP, CMD_SPEED, CMD_RESET_HOME, CMD_SR_SET = 1, 2, 3, 4, 5, 6
CMD_DEPOSIT_TABLE, CMD_PATCH, CMD_CEILING, CMD_MUTE, CMD_AUTH_MODE = 7, 8, 9, 10, 11
CMD_VOLUME = 12
CMD_TEST_TONE = 13  # API 2, backward-compatible addition: a on/off, b Hz, f dBFS
INJECT_NAN, INJECT_INF = 1, 2
LAT_ARRIVAL, LAT_LATCH, LAT_FIRST_WRITE, LAT_ONSET = 0, 1, 2, 3
LAT_BIN_US = 250
SAFETY_LATENCY_FRAMES = 47  # SX_SAFETY_LATENCY: the limiter's look-ahead (VS-11)

# sxhost.h
SXH_OK, SXH_E_ARG, SXH_E_STATE, SXH_E_DEVICE = 0, -1, -3, -4
SXH_AUDIO_SILENT_DEVICE = 0x1

ffi = FFI()
ffi.cdef(CDEF)


def default_lib_path(build: Path | None = None) -> Path:
    ext = "dylib" if sys.platform == "darwin" else "so"
    env = os.environ.get("SX_HOST_LIB")
    if env:
        return Path(env)
    return (build or ROOT / "build") / "host" / f"libsxhost.{ext}"


class EngineLoadError(RuntimeError):
    """libsxhost could not be loaded or does not match these declarations (engine_load_failed)."""


def load_library(path: Path):
    try:
        lib = ffi.dlopen(str(path))
    except OSError as exc:
        raise EngineLoadError(f"cannot load {path}: {exc}") from exc
    if lib.sx_api_version() != SX_API_VERSION or lib.sxh_api_version() != SXH_API_VERSION:
        raise EngineLoadError(
            f"{path}: engine API {lib.sx_api_version()}, host API {lib.sxh_api_version()}; "
            f"rigd expects {SX_API_VERSION} and {SXH_API_VERSION}"
        )
    return lib


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class ImageError(ValueError):
    """The image file is missing or not seastones.image/1 (image_missing)."""


@dataclass
class Image:
    """A ``seastones.image/1`` file, as cffi structures that live as long as this object."""

    path: Path
    sha256: str
    entry_pc: int
    entry_psw: int
    segments: list[tuple[int, list[int]]]
    cdata: object = None
    keep: list = field(default_factory=list)

    def word(self, addr: int) -> int | None:
        """The image's word at a byte address (the code is never written: DEV-PLAN 7.1)."""
        for base, words in self.segments:
            if base <= addr < base + 2 * len(words) and not (addr - base) & 1:
                return words[(addr - base) // 2]
        return None

    def code_range(self) -> tuple[int, int]:
        for base, words in self.segments:
            if base <= self.entry_pc < base + 2 * len(words):
                return base, base + 2 * len(words)
        return self.entry_pc, self.entry_pc + 2


def load_image(path: Path) -> Image:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ImageError(f"{path}: no image (run `make program`)") from exc
    except (OSError, ValueError) as exc:
        raise ImageError(f"{path}: {exc}") from exc
    if doc.get("format") != "seastones.image/1":
        raise ImageError(f"{path}: not a seastones.image/1 file")
    try:
        segs = [(int(s["addr"], 16), [int(w, 16) for w in s["words"]]) for s in doc["segments"]]
        img = Image(
            path=Path(path),
            sha256=str(doc["sha256"]),
            entry_pc=int(doc["entry_pc"], 16),
            entry_psw=int(doc.get("entry_psw", "0000"), 16),
            segments=segs,
        )
        digest = bytes.fromhex(img.sha256)
    except (KeyError, TypeError, ValueError) as exc:
        raise ImageError(f"{path}: malformed image ({exc})") from exc
    c_segs = ffi.new("sx_segment[]", max(1, len(segs)))
    for i, (addr, words) in enumerate(segs):
        arr = ffi.new("uint16_t[]", words or [0])
        img.keep.append(arr)
        c_segs[i].addr = addr
        c_segs[i].nwords = len(words)
        c_segs[i].words = arr
    c_img = ffi.new("sx_image *")
    c_img.segments = c_segs
    c_img.nsegments = len(segs)
    c_img.entry_pc = img.entry_pc
    c_img.entry_psw = img.entry_psw
    ffi.memmove(c_img.sha256, digest[:32].ljust(32, b"\0"), 32)
    img.keep.append(c_segs)
    img.cdata = c_img
    return img
