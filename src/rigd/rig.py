"""The rig: one engine, its audio device and its MIDI input, owned by rigd's control thread.

Start-up order (ARCHITECTURE 8.1 "Starting"): open the audio device (its rate decides the
engine's), create the engine, load the image, set the staff ceiling, start MIDI, start the
device. The engine fades in over 200 ms from its first period (AUDIO-4). Each step that fails
leaves a named fault rather than a fallback: no image is ``image_missing``, a device that will
not open is ``audio_device_missing`` (the engine is then created at the configured rate and
the device is retried), and so on. Nothing here makes a sound except the engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import engine as eng
from .engine import ffi


@dataclass
class AudioConfig:
    backend: str = "auto"  # "auto" (CoreAudio / ALSA) or "null" (paced, no hardware)
    device: str = ""
    rate: int = 0  # 0: the device's own rate (a shared Mac keeps its rate); ALSA asks 48000
    period: int = 128
    periods: int = 2
    sub_period: int = 32
    silent_device: bool = False


@dataclass
class RigConfig:
    lib: Path
    image: Path
    audio: AudioConfig
    midi: bool = True
    midi_base_note: int = 48  # key 0 plays note 48 (the program's BASENOTE; VS-29 default)
    midi_source: str = ""  # connect only sources whose name has this ("": every source)
    keys: int = 37
    ceiling_dbfs: float = -12.0
    dac_word_bits: int = 12
    dac_range_v: float = 10.24
    capture: Path | None = None


class Rig:
    def __init__(self, cfg: RigConfig):
        self.cfg = cfg
        self.lib = None
        self.e = ffi.NULL
        self.image: eng.Image | None = None
        self.image_error: str | None = None
        self.audio_info: dict | None = None
        self.audio_error: str | None = None
        self.midi_error: str | None = None
        self.rate = cfg.audio.rate or 48000
        self.profile = "unknown"
        self.lib_sha256 = ""
        self._snap = None
        self._samples = None
        self._astat = None
        self._mstat = None
        self.disasm_table: dict[str, str] = {}
        self.capture_segments: list[list] = []  # [file sample, engine frame or None]

    # -------------------------------------------------------------- lifetime

    def load(self) -> None:
        """Load libsxhost. Raises EngineLoadError (engine_load_failed)."""
        self.lib = eng.load_library(self.cfg.lib)
        self.profile = ffi.string(self.lib.sxh_profile()).decode()
        self.lib_sha256 = eng.file_sha256(self.cfg.lib)
        self._snap = ffi.new("sx_snapshot *")
        self._samples = ffi.new("sxh_sample[]", 4096)
        self._astat = ffi.new("sxh_audio_status *")
        self._mstat = ffi.new("sxh_midi_status *")

    def open_audio(self, rate: int | None = None) -> bool:
        a = self.cfg.audio
        cfg = ffi.new("sxh_audio_cfg *")
        keep = [ffi.new("char[]", a.backend.encode()), ffi.new("char[]", a.device.encode())]
        cfg.backend, cfg.device = keep
        cfg.rate = rate if rate is not None else a.rate
        cfg.period = a.period
        cfg.periods = a.periods
        cfg.sub_period = a.sub_period
        cfg.flags = eng.SXH_AUDIO_SILENT_DEVICE if a.silent_device else 0
        info = ffi.new("sxh_audio_info *")
        rc = self.lib.sxh_audio_open(cfg, info)
        if rc != eng.SXH_OK:
            self.audio_error = f"the audio device would not open ({a.backend} {a.device!r}, {rc})"
            self.audio_info = None
            return False
        self.audio_error = None
        self.audio_info = {
            "backend": ffi.string(info.backend).decode(errors="replace"),
            "device": ffi.string(info.device).decode(errors="replace"),
            "rate": info.rate,
            "period": info.period,
            "periods": info.periods,
            "latency_frames": info.latency_frames,
        }
        return True

    def create_engine(self, rate: int) -> None:
        cfg = ffi.new("sx_config *")
        cfg.api_version = eng.SX_API_VERSION
        cfg.sample_rate = rate
        cfg.dac_word_bits = self.cfg.dac_word_bits
        cfg.dac_range_v = self.cfg.dac_range_v
        cfg.flags = eng.SX_CFG_TEST_HOOKS if self.profile == "test" else 0
        cfg.max_frames = 4096
        e = self.lib.sx_create(cfg)
        if e == ffi.NULL:
            raise eng.EngineLoadError(f"sx_create refused the configuration (rate {rate})")
        self.e = e
        self.rate = rate
        try:
            self.image = eng.load_image(self.cfg.image)
        except eng.ImageError as exc:
            self.image, self.image_error = None, str(exc)
            return
        rc = self.lib.sx_load_image(self.e, self.image.cdata)
        if rc == eng.SX_E_HASH:
            self.image_error = f"{self.cfg.image}: the image's sha256 does not match its words"
        elif rc != eng.SX_OK:
            self.image_error = f"{self.cfg.image}: sx_load_image returned {rc}"

    def start(self, disasm_addrs: list[int] = ()) -> None:
        """The whole start-up. Faults are left in *_error; only a missing library raises.

        ``disasm_addrs``: listed instruction addresses whose sx_disasm text hello carries. It is
        read here, before the device starts, because sx_disasm may not run beside sx_render."""
        self.load()
        opened = self.open_audio()
        self.create_engine(self.audio_info["rate"] if opened else self.rate)
        self.disasm_table = (
            {f"{a:04X}": self.disasm(a) for a in disasm_addrs} if self.image is not None else {}
        )
        self.command(eng.CMD_CEILING, f=self.cfg.ceiling_dbfs)
        if self.cfg.midi:
            self.lib.sxh_midi_filter(self.cfg.midi_source.encode())
            rc = self.lib.sxh_midi_start(self.e, self.cfg.midi_base_note, self.cfg.keys)
            self.midi_error = None if rc == eng.SXH_OK else f"MIDI would not start ({rc})"
        if opened:
            self.start_audio()

    def start_audio(self) -> bool:
        if self.cfg.capture is not None:  # before the device starts: no frame is missed
            path = Path(self.cfg.capture)
            if not self.capture_segments and path.exists():
                path.unlink()  # a new run starts a new file; a reopen appends a segment
            offset = path.stat().st_size // 4 if path.exists() else 0
            if self.lib.sxh_capture_start(str(path).encode()) == eng.SXH_OK:
                self.capture_segments.append([offset, None])
        if self.lib.sxh_audio_start(self.e) != eng.SXH_OK:
            self.audio_error = "the audio device would not start"
            self.lib.sxh_audio_close()
            self.audio_info = None
            return False
        return True

    def capture_segment_known(self) -> tuple[int, int] | None:
        """(file sample, engine frame) of the newest capture segment, once, when it is known."""
        if not self.capture_segments or self.capture_segments[-1][1] is not None:
            return None
        first = int(self.audio_status()["capture_first_frame"])
        if first == 2**64 - 1:
            return None
        self.capture_segments[-1][1] = first
        return self.capture_segments[-1][0], first

    def reopen_audio(self) -> bool:
        """Close and reopen the device at the engine's rate (unplug, stall: ARCHITECTURE 8.1)."""
        self.lib.sxh_audio_close()
        if not self.open_audio(self.rate):
            return False
        return self.start_audio()

    def close(self) -> None:
        if self.lib is None:
            return
        self.lib.sxh_midi_stop()
        self.lib.sxh_audio_close()
        if self.e != ffi.NULL:
            self.lib.sx_destroy(self.e)
            self.e = ffi.NULL

    # -------------------------------------------------------------- calls

    def command(self, kind: int, a: int = 0, b: int = 0, f: float = 0.0) -> int:
        if self.e == ffi.NULL:
            return eng.SX_E_STATE
        c = ffi.new("sx_cmd *", {"kind": kind, "a": a, "b": b, "f": f})
        return self.lib.sx_command(self.e, c)

    def keys_set(self, source: int, bits: int) -> None:
        if self.e != ffi.NULL:
            self.lib.sx_keys_set(self.e, source, bits & 0xFFFFFFFFFFFFFFFF)

    def midi_mask(self, bits: int) -> None:
        if self.lib is not None:
            self.lib.sxh_midi_mask(bits & 0xFFFFFFFFFFFFFFFF)

    def snapshot(self):
        """A fresh seqlock copy (cffi struct), or None."""
        if self.e == ffi.NULL or self.lib.sx_snapshot_read(self.e, self._snap) != eng.SX_OK:
            return None
        return self._snap

    def samples(self) -> list[tuple[int, int, int, int]]:
        out = []
        while True:
            n = self.lib.sxh_samples_read(self._samples, 4096)
            out.extend(
                (s.frame, s.pc, s.halted, s.keys_reads)
                for s in (self._samples[i] for i in range(n))
            )
            if n < 4096:
                return out

    def audio_status(self) -> dict:
        self.lib.sxh_audio_status_read(self._astat)
        s = self._astat
        return {k: getattr(s, k) for k in dir(s)}

    def midi_status(self) -> dict:
        self.lib.sxh_midi_status_read(self._mstat)
        s = self._mstat
        return {k: getattr(s, k) for k in dir(s)}

    def frame_host_ns(self, frame: int) -> int:
        return self.lib.sxh_frame_host_ns(frame)

    def now_ns(self) -> int:
        return self.lib.sxh_now_ns()

    def disasm(self, addr: int) -> str:
        """SIMH fprint_sym text; [non-RT]: call before the device starts (hello's table)."""
        buf = ffi.new("char[]", 96)
        n = self.lib.sx_disasm(self.e, addr, buf, 96)
        return ffi.string(buf, n).decode(errors="replace").strip() if n else ""

    def patch_load(self, graph: str) -> tuple[int, str]:
        """Queue a seastones.graph/1 patch (swapped in at the next period, 5 ms crossfade).
        (SX_OK, ""), (SX_E_ARG, "line N: why") or (SX_E_AGAIN, "") while a swap is pending."""
        if self.e == ffi.NULL:
            return eng.SX_E_STATE, "no engine"
        data = graph.encode()
        err = ffi.new("char[]", 256)
        rc = self.lib.sx_patch_load(self.e, data, len(data), err, 256)
        return rc, ffi.string(err).decode(errors="replace")

    def modules_json(self) -> dict:
        """The engine's module registry (seastones.modules/1)."""
        n = self.lib.sx_modules_json(ffi.NULL, 0)
        buf = ffi.new("char[]", n + 1)
        self.lib.sx_modules_json(buf, n + 1)
        return json.loads(ffi.string(buf, n).decode())

    def test_inject(self, what: int) -> None:
        self.lib.sx_test_inject(self.e, what)

    def test_freeze(self, on: bool) -> None:
        self.lib.sxh_test_freeze(1 if on else 0)

    def test_late(self, n: int) -> None:
        self.lib.sxh_test_late(n)

    def test_unplug(self) -> None:
        self.lib.sxh_test_unplug()
