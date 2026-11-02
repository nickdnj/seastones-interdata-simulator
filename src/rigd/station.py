"""rigd's control loop: protocol v1, the session rules and supervision (VS-14, VS-16, VS-17,
VS-18; ARCHITECTURE 4.5, 4.6, 8).

One asyncio loop on one thread is the engine's one command writer (ARCHITECTURE 4.5). Every
1/60 s it reads the engine's snapshot and the audio thread's samples, applies the session
rules, supervises, and sends ``state`` (60 Hz), ``scope`` (30 Hz) and ``heartbeat`` (1 Hz) to
every page. The WebSocket listens on loopback only; it offers no memory write of any kind
(CODE-4, ENG-04): the visitor commands are keys, speed, step, HOME and the patch commands.

Session rules (ARCHITECTURE 4.5, 4.6, 8.1):
  * keys.touch is a level: each page's whole bitmap; the engine's touch source is their OR.
    A page that goes away has its keys cleared 250 ms later (INPUT-4).
  * No page for ui_absent_mute_s (10 s) mutes the engine; a page connecting unmutes it.
  * A key held past held_key_release_s (60 s, kiosk.conf) is released and stays ignored until
    it is let go (PLAY-8). HOME releases every held key the same way, returns to RUN and
    resets the machine (PLAY-9, ENG-07).
Supervision (8.1): an engine fault mutes in the engine within 8 ms; rigd then sends HOME
(reload the image) with backoff. A lost audio device is retried every 2 s; a stalled audio
thread (frames frozen over 150 ms) is reopened, and three stalls in a minute exit so systemd
restarts rigd. A vanished MIDI keyboard's notes are released at once by the host; rigd sends
the midi_absent notice and clears it on replug.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import engine as eng
from . import faults as F
from . import schema
from .panel import SPEED_BY_ID, SPEEDS, Panel
from .patchwall import PatchWall, sxpatch
from .rig import Rig
from .staff import Staff
from .supervise import Notifier

KEY_MASK_DEFAULT = (1 << 37) - 1
MAX_MESSAGE = 64 * 1024  # bytes; a larger frame closes the connection (ENG-03)
PAGE_STALE_S = 1.0  # a page silent this long has released its keys (QA-ADV-07)
UNDERRUN_STORM = (3, 5.0)  # late callbacks within seconds: the audio_underruns fault
UNDERRUN_CLEAR_S = 10.0
SLOW_SKIP_BYTES = 256 * 1024  # a page this far behind misses state and scope frames
SLOW_CLOSE_BYTES = 4 * 1024 * 1024  # and this far behind is dropped
TEST_TONE_HZ, TEST_TONE_DBFS, TEST_TONE_S = 1000, -20.0, 3.0  # staff.test_tone (UX 5.11)


@dataclass
class StationConfig:
    host: str = "127.0.0.1"
    port: int = 7690
    listing: Path | None = None
    hz: float = 60.0
    ui_absent_mute_s: float = 10.0  # 0 disables (test profile only)
    touch_clear_s: float = 0.25
    held_key_release_s: float = 60.0
    keys: int = 37
    test_hooks: bool = False
    staff_pin: str | None = None  # the digits or sha256:<hex> (staff.py)
    data_dir: Path | None = None  # staff.conf and staff-saved presets (/data on the station)
    content: Path | None = None  # the content set: presets/
    preset: str | None = None  # the patch at start and after HOME (kiosk.conf preset_order)
    map_name: str = "all-da-4"  # the channel map the image was built for
    ceiling_max_dba: int = 78
    ceiling_dba: int = 67
    ceiling_cap_dbfs: float = -1.0  # a developer's cap on top of the staff ceiling
    settings: dict = field(default_factory=lambda: {
        "idle_timeout_s": 90, "reduced_motion": False, "review_mode": False,
        "attract_sound": False})  # fmt: skip
    latency_log: Path | None = None
    recover_backoff_s: tuple = (0.25, 0.5, 1.0, 2.0)
    audio_retry_s: float = 2.0
    stall_s: float = 0.15
    stall_strikes: int = 3
    config_errors: list = field(default_factory=list)
    log: object = field(default=sys.stderr)


class Conn:
    _next = 1

    def __init__(self, ws):
        self.ws = ws
        self.n = Conn._next
        Conn._next += 1
        self.touch = 0
        self.closed_at: float | None = None
        self.staff = False  # a staff session is open on this connection
        self.last_msg = time.monotonic()  # a live page sends keys.touch at 4 Hz, always
        self.stale = False  # silent over PAGE_STALE_S: its keys count as released


class Station:
    def __init__(self, cfg: StationConfig, rig: Rig):
        self.cfg = cfg
        self.rig = rig
        self.conns: set[Conn] = set()
        self.leaving: list[tuple[float, Conn]] = []
        self.key_mask = (1 << cfg.keys) - 1 if cfg.keys < 64 else (1 << 64) - 1
        self.touch_mask = 0  # touch keys held through HOME or past 60 s, until released
        self.held_since: dict[int, float] = {}
        self.speed = "run"
        self.staff_mute = False
        self.ui_muted = False
        self.recovery_mute = False
        self.mute_sent: bool | None = None
        self.started = time.monotonic()
        self.last_ui = self.started
        self.active: dict[str, int] = {}  # fault code -> since (engine frames)
        self.fatal: str | None = None
        self.seq = 0
        self.tick_no = 0
        self.panel: Panel | None = None
        self.hello: dict | None = None
        self.notifier = Notifier()
        self.exit_code: int | None = None
        # supervision state
        self.recover_at: float | None = None
        self.recover_n = 0
        self.healthy_since = self.started
        self.audio_retry_at: float | None = None
        self.last_frames = -1
        self.frames_moved_at = self.started
        self.stalls: list[float] = []
        self.midi_sources = 0
        self.midi_seen = False
        self.patch: PatchWall | None = None
        self.staff = Staff(cfg.data_dir, cfg.staff_pin, cfg.settings, cfg.ceiling_max_dba,
                           cfg.ceiling_dba)  # fmt: skip
        self.staff_mute = bool(self.staff.cfg["muted"])
        self.ceiling_sent: float | None = None
        self.exit_at: float | None = None
        self.tone_off_at: float | None = None  # the staff test tone's end (at most 3 s, UX 5.11)
        self.underruns = 0  # late callbacks since start, across device reopens
        self.late_seen = 0
        self.late_times: list[float] = []
        self.volume_db = 0.0  # AUDIO-3: the visitor's volume below the ceiling
        self.visitor_mute = False
        self.deferred: list | None = None  # broadcasts held until a command's reply is sent
        self.last_onset = 0
        self.lat_fh = None
        self.last_snap = None

    # ================================================================ start-up

    def log(self, text: str) -> None:
        print(f"rigd: {text}", file=self.cfg.log, flush=True)

    def disasm_addrs(self) -> list[int]:
        """Every listed instruction address in the code segment (hello.disasm, CODE-3)."""
        path = self.cfg.listing
        if not path or not Path(path).exists():
            return []
        try:
            lines = json.loads(Path(path).read_text())["lines"]
        except (OSError, ValueError, KeyError):
            return []
        img = eng.load_image(self.rig.cfg.image) if Path(self.rig.cfg.image).exists() else None
        lo, hi = img.code_range() if img else (0, 0x1000)
        return sorted({int(ln["addr"], 16) for ln in lines if ln.get("words")} & set(range(lo, hi)))

    def start(self) -> None:
        try:
            addrs = self.disasm_addrs()
        except eng.ImageError:
            addrs = []
        try:
            self.rig.start(addrs)
        except eng.EngineLoadError as exc:
            self.fatal = "engine_load_failed"
            self.raise_fault("engine_load_failed", detail=str(exc))
            return
        if self.rig.image_error:
            code = "image_hash_mismatch" if "sha256" in self.rig.image_error else "image_missing"
            self.raise_fault(code, detail=self.rig.image_error)
        if self.rig.audio_error:
            self.raise_fault("audio_device_missing", detail=self.rig.audio_error)
            self.audio_retry_at = time.monotonic() + self.cfg.audio_retry_s
        if self.rig.midi_error:
            self.log(self.rig.midi_error)
        if self.cfg.config_errors:  # the defaults are used; the staff screen names the problem
            self.raise_fault("config_invalid", detail="; ".join(self.cfg.config_errors))
        self.cmap = sxpatch.channel_maps().get(self.cfg.map_name)
        if self.cmap is None:
            self.raise_fault("config_invalid", detail=f"unknown channel map {self.cfg.map_name}")
        self.panel = Panel(self.rig.image, self.rig.rate, self.cmap, self.rig.cfg.dac_word_bits)
        dirs = [d for d in (self.cfg.content and self.cfg.content / "presets",
                            self.cfg.data_dir and self.cfg.data_dir / "presets") if d]  # fmt: skip
        self.patch = PatchWall(self.rig, dirs, self.cfg.map_name)
        if self.cfg.preset:
            rc = self.patch.load(self.cfg.preset)
            if rc != "ack":
                self.log(f"preset {self.cfg.preset} did not load ({rc}); the engine's own patch")
        self.apply_ceiling()
        self.apply_mute()
        self.hello = self.build_hello()
        if self.cfg.latency_log:
            self.lat_fh = open(self.cfg.latency_log, "a", buffering=1)  # noqa: SIM115
        a = self.rig.audio_info or {}
        self.log(
            f"profile {self.rig.profile}; audio {a.get('backend')} '{a.get('device')}' "
            f"{a.get('rate')} Hz, period {a.get('period')} x {a.get('periods')}, reported "
            f"latency {a.get('latency_frames')} frames; image "
            f"{self.rig.image.sha256[:12] if self.rig.image else 'none'}"
        )
        self.notifier.ready(f"profile {self.rig.profile}")

    def build_hello(self) -> dict:
        img = self.rig.image
        listing_id = img.sha256 if img else "0" * 64
        if self.cfg.listing and Path(self.cfg.listing).exists():
            try:
                listing_id = json.loads(Path(self.cfg.listing).read_text())["image_sha256"]
            except (OSError, ValueError, KeyError):
                pass
        build = (
            f"seastones-rigd 0.1 · profile {self.rig.profile} · engine api {eng.SX_API_VERSION}"
            f" · host api {eng.SXH_API_VERSION} · libsxhost {self.rig.lib_sha256[:12]}"
        )
        return {
            "v": 1,
            "t": "hello",
            "engine_build": build,
            "image_sha256": img.sha256 if img else "0" * 64,
            "listing_id": listing_id,
            "capabilities": {
                "speeds": [
                    {
                        "id": s["id"],
                        "label": s["label"],
                        "ratio": s["ratio"],
                        "key_to_sound_ms": s["key_to_sound_ms"],
                        "calibrated": False,
                    }
                    for s in SPEEDS
                ],
                "voices": (self.cmap or {}).get("voices", 1),
                "dac": {
                    "word_bits": self.rig.cfg.dac_word_bits,
                    "range_v": self.rig.cfg.dac_range_v,
                },
                "channel_map": self.cfg.map_name,
                "jacks": self.patch.jacks() if self.patch else [],
            },
            "disasm": dict(self.rig.disasm_table),
        }

    # ================================================================ faults

    def raise_fault(self, code: str, detail: str = "") -> None:
        if code in self.active:
            return
        since = self.last_snap.frames if self.last_snap is not None else 0
        self.active[code] = since
        self.log(f"fault {code}{': ' + detail if detail else ''}")
        self.broadcast(
            {"v": 1, "t": "fault", "code": code, "staff_line": F.STAFF_LINES[code], "since": since}
        )

    def clear_fault(self, code: str) -> None:
        since = self.active.pop(code, None)
        if since is None:
            return
        self.log(f"fault {code} cleared")
        self.broadcast(
            {
                "v": 1,
                "t": "fault",
                "code": code,
                "staff_line": F.STAFF_LINES[code],
                "since": since,
                "cleared": True,
            }
        )

    # ================================================================ messages out

    def _write(self, conns, text: str, droppable: bool) -> None:
        from websockets.asyncio.server import broadcast

        ok = []
        for c in conns:
            transport = getattr(c.ws, "transport", None)
            backlog = transport.get_write_buffer_size() if transport is not None else 0
            if backlog > SLOW_CLOSE_BYTES:
                transport.abort()  # a page that stopped reading; it reconnects (ENG-11)
            elif not (droppable and backlog > SLOW_SKIP_BYTES):
                ok.append(c.ws)
        broadcast(ok, text)  # no waiting: the loop never blocks on a page

    def send(self, conn: Conn, msg: dict) -> None:
        self._write([conn], json.dumps(msg, separators=(",", ":")), droppable=False)

    def broadcast(self, msg: dict, droppable: bool = False) -> None:
        if self.deferred is not None:
            self.deferred.append((msg, droppable))
            return
        if self.conns:
            self._write(list(self.conns), json.dumps(msg, separators=(",", ":")), droppable)

    def patch_msg(self) -> dict:
        if self.patch is None:
            return {"v": 1, "t": "patch", "cables": [], "reaches_out": False, "preset": None}
        return self.patch.message()

    def heartbeat_msg(self) -> dict:
        a = self.rig.audio_status() if self.rig.lib is not None else {}
        audio_ok = bool(a.get("running")) and not (
            {"audio_device_missing", "audio_stalled"} & set(self.active)
        )
        stages = {k: not (blockers & set(self.active)) for k, blockers in F.STAGE_BLOCKERS.items()}
        stages["output"] = stages["output"] and audio_ok
        return {
            "v": 1,
            "t": "heartbeat",
            "engine_alive": self.fatal is None
            and not ({"program_stalled", "engine_load_failed"} & set(self.active)),
            "audio_ok": audio_ok,
            "midi_present": self.midi_sources > 0,
            "faults": self.fault_list(),
            "muted": bool(self.last_snap.muted) if self.last_snap is not None else True,
            "lat_p95": self.lat_p95(),
            "underruns": self.underruns,
            "stages": stages,
        }

    def fault_list(self) -> list[str]:
        return [c for c in F.CODES if c in self.active]

    def lat_p95(self) -> float | None:
        s = self.last_snap
        if s is None:
            return None
        hist = list(s.lat_hist)
        total = sum(hist)
        if not total:
            return None
        acc = 0
        for i, n in enumerate(hist):
            acc += n
            if acc >= 0.95 * total:
                return round((i + 1) * eng.LAT_BIN_US / 1000.0, 3)
        return None

    def state_msg(self, s) -> dict:
        halted = bool(s.halted)
        exact = halted or self.speed in ("crawl", "step") or not self.panel.frame_samples
        self.seq += 1
        return {
            "v": 1,
            "t": "state",
            "seq": self.seq,
            "frames": int(s.frames),
            "cycles": int(s.cycles),
            "pc": int(s.pc),
            "psw": int(s.psw),
            "r": [int(x) for x in s.r],
            "cc": int(s.cc) & 0xF,
            "dr": int(s.dr) & 0xFFFF,
            "sr": int(s.sr),
            "keys_raw": [int(x) for x in s.keys_raw],
            "keys_seen": [int(x) for x in s.keys_seen],
            "dac": [int(x) for x in s.dac_code],
            "gates": int(s.gates),
            "watch": {"voices": self.panel.voices(s)},
            "pc_hist": self.panel.pc_hist(),
            "lamps": self.panel.lamps(int(s.pc), exact),
            "speed": self.speed,
            "halted": halted,
            "waiting": bool(s.waiting),
            "muted": bool(s.muted),
            "faults": self.fault_list(),
            "scan_hz": self.panel.scan_hz(),
            "volume": {"db": self.volume_db, "muted": self.visitor_mute},
        }

    def scope_msg(self, s) -> dict:
        pts = [round(max(-1.0, min(1.0, float(x))), 4) for x in s.scope]
        return {"v": 1, "t": "scope", "seq": self.seq, "points": pts}

    # ================================================================ connections

    async def handler(self, ws) -> None:
        conn = Conn(ws)
        self.conns.add(conn)
        self.last_ui = time.monotonic()
        if self.ui_muted:
            self.ui_muted = False
            self.clear_fault("ui_absent_muted")
            self.apply_mute()
        if self.hello is not None:
            self.hello = self.build_hello()  # the jacks follow the live patch
            self.send(conn, self.hello)
            self.send(conn, self.staff.settings_message())
            self.send(conn, self.patch_msg())
        self.send(conn, self.heartbeat_msg())
        for code, since in self.active.items():
            self.send(conn, {"v": 1, "t": "fault", "code": code,
                             "staff_line": F.STAFF_LINES[code], "since": since})  # fmt: skip
        if self.last_snap is not None and self.panel is not None:
            self.send(conn, self.state_msg(self.last_snap))
        try:
            async for raw in ws:
                self.receive(conn, raw)
        except Exception:  # noqa: BLE001 (a dropped or oversized socket ends this page only)
            pass
        finally:
            self.conns.discard(conn)
            now = time.monotonic()
            self.last_ui = now
            if conn.touch:
                self.leaving.append((now + self.cfg.touch_clear_s, conn))

    def receive(self, conn: Conn, raw) -> None:
        conn.last_msg = self.last_ui = time.monotonic()  # any message: the page is alive
        if conn.stale:
            conn.stale = False
            self.log(f"page {conn.n} speaks again")
        if self.ui_muted:
            self.ui_muted = False
            self.clear_fault("ui_absent_muted")
            self.apply_mute()
        if isinstance(raw, bytes | bytearray):
            return  # the protocol is text frames only
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        mid = msg.get("id") if isinstance(msg, dict) else None
        has_id = isinstance(mid, int) and not isinstance(mid, bool) and mid > 0
        errs = schema.validate("client", msg)
        if errs:
            if has_id:
                unknown = errs[0].startswith("unknown client message type")
                self.send(conn, {"v": 1, "t": "nack", "id": mid,
                                 "code": "unknown" if unknown else "bad_args"})  # fmt: skip
            return
        # what a command broadcasts (a new patch, settings) goes out after its own ack or nack
        self.deferred = []
        try:
            reply = self.dispatch(conn, msg)
        finally:
            later, self.deferred = self.deferred, None
        if has_id and reply is not None:
            if reply == "ack":
                self.send(conn, {"v": 1, "t": "ack", "id": mid})
            else:
                self.send(conn, {"v": 1, "t": "nack", "id": mid, "code": reply})
        for m, droppable in later:
            self.broadcast(m, droppable)

    def command(self, kind: int, a: int = 0, b: int = 0, f: float = 0.0) -> str:
        rc = self.rig.command(kind, a, b, f)
        if rc == eng.SX_E_AGAIN:
            return "queue_full"
        return "ack" if rc == eng.SX_OK else "busy"

    def dispatch(self, conn: Conn, msg: dict) -> str | None:
        t = msg["t"]
        if self.fatal and t != "keys.touch":
            return "busy"
        if t == "keys.touch":
            conn.touch = int(msg["bits"], 16)
            self.apply_touch()
            return None
        if t == "machine.speed":
            return self.set_speed(msg["position"])
        if t == "machine.step":
            if self.speed != "step":
                return "busy"
            return self.command(eng.CMD_STEP)
        if t == "machine.home":
            return self.home()
        if t == "audio.volume":  # AUDIO-3: below the ceiling only; the limiter still holds it
            return self.set_volume(float(msg["db"]))
        if t == "audio.mute":
            self.visitor_mute = bool(msg["on"])
            self.apply_mute()
            return "ack"
        if t in ("patch.connect", "patch.disconnect", "patch.load"):
            if self.patch is None:
                return "busy"
            if t == "patch.load":
                rc = self.patch.load(msg["slug"])
            elif t == "patch.connect":
                rc = self.patch.connect(msg["from"], msg["to"])
            else:
                rc = self.patch.disconnect(msg["from"], msg["to"])
            if rc == "ack":
                self.broadcast(self.patch_msg())
            return rc
        if t == "passage.start":
            return "refused_gate"  # no passage is `ready` on this volume (SEA-3, CT-06, ENG-05)
        if t.startswith("staff."):
            return self.staff_cmd(conn, msg)
        if t == "test.inject":
            return self.test_inject(msg["what"])
        return "unknown"

    # ================================================================ commands

    def set_speed(self, position: str) -> str:
        sp = SPEED_BY_ID[position]
        if position == "run":
            rc = self.command(eng.CMD_SPEED, eng.SPEED_RUN)
        elif position == "step":
            rc = self.command(eng.CMD_SPEED, eng.SPEED_SINGLE)
        else:
            rc = self.command(eng.CMD_SPEED, eng.SPEED_DIVISOR, sp["divisor"])
        if rc == "ack":
            self.speed = position
        return rc

    def set_volume(self, db: float) -> str:
        db = max(-40.0, min(0.0, db))
        rc = self.command(eng.CMD_VOLUME, f=db)
        if rc == "ack":
            self.volume_db = db
        return rc

    def home(self) -> str:
        """HOME (PLAY-9, ENG-07, KP-06): reset the machine, RUN, every held key released, the
        visitor's volume and mute back to their defaults."""
        rc = self.command(eng.CMD_RESET_HOME)
        if rc != "ack":
            return rc
        self.set_volume(0.0)
        self.visitor_mute = False
        self.apply_mute()
        self.set_speed("run")
        self.touch_mask = self.touch_union()
        self.rig.midi_mask((1 << 64) - 1)
        self.apply_touch()
        if self.patch is not None and self.cfg.preset:
            self.patch.load(self.cfg.preset)  # HOME restores the default patch (ENG-07)
        self.broadcast(self.patch_msg())
        return "ack"

    def staff_cmd(self, conn: Conn, msg: dict) -> str | None:
        """The staff session (staff.py). Replies are a staff message to this connection only."""
        t, mid = msg["t"], msg["id"]

        def reply(code: str, **kw) -> None:
            self.send(conn, {"v": 1, "t": "ack", "id": mid} if code == "ack"
                      else {"v": 1, "t": "nack", "id": mid, "code": code})  # fmt: skip
            self.send(conn, self.staff.message(conn.staff, **kw))

        if t == "staff.auth":
            conn.staff = self.staff.auth(msg["pin"])
            reply("ack" if conn.staff else "not_staff")
            return None
        if not conn.staff:
            return "not_staff"
        s = self.staff
        if t == "staff.close":
            conn.staff = False
        elif t == "staff.ceiling":
            s.cfg["ceiling_dba"] = min(msg["dba"], s.cfg["ceiling_max_dba"])
            s.cfg["quiet_hours"]["dba"] = min(s.cfg["quiet_hours"]["dba"], s.cfg["ceiling_dba"])
        elif t == "staff.quiet_hours":
            s.cfg["quiet_hours"] = {"from": msg["from"], "to": msg["to"],
                                    "dba": min(msg["dba"], s.cfg["ceiling_dba"])}  # fmt: skip
        elif t == "staff.mute":
            s.cfg["muted"] = bool(msg["on"])
            self.staff_mute = s.cfg["muted"]
            self.apply_mute()
        elif t in ("staff.idle_timeout", "staff.attract_sound", "staff.reduced_motion",
                   "staff.review_mode"):  # fmt: skip
            key = {"staff.idle_timeout": "idle_timeout_s"}.get(t, t.removeprefix("staff."))
            s.settings[key] = msg["s"] if t == "staff.idle_timeout" else bool(msg["on"])
            self.broadcast(s.settings_message())
        elif t == "staff.test_tone":
            # The engine's own diagnostic sine (SX_CMD_TEST_TONE): 1 kHz at -20 dBFS, mixed in
            # before the safety chain, so the staff ceiling, the limiter and a mute all apply
            # (UX 5.11). It stops by itself 3 s after the last press (tick, below).
            rc = self.command(eng.CMD_TEST_TONE, 1, TEST_TONE_HZ, TEST_TONE_DBFS)
            if rc != "ack":
                reply(rc)
                return None
            self.tone_off_at = time.monotonic() + TEST_TONE_S
        elif t == "staff.restart":
            if msg["what"] == "computer":
                self.home()
            else:
                self.exit_at = time.monotonic() + 0.3  # exit: systemd starts the stack again
        elif t == "staff.save_preset":
            if self.patch is None or self.patch.flat is None or not self.cfg.data_dir:
                reply("busy")
                return None
            slug = time.strftime("staff-%Y%m%d-%H%M")
            d = self.cfg.data_dir / "presets"
            try:
                d.mkdir(parents=True, exist_ok=True)
                self.patch.save(d / f"{slug}.patch.json", slug)
            except OSError:
                reply("busy")
                return None
            s.save()
            reply("ack", saved=slug, with_saved=True)
            return None
        s.save()
        self.apply_ceiling()
        reply("ack")
        if t == "staff.mute":
            self.broadcast(self.heartbeat_msg())
        return None

    def apply_ceiling(self) -> None:
        dbfs = min(self.staff.ceiling_dbfs(), self.cfg.ceiling_cap_dbfs)
        if dbfs != self.ceiling_sent and self.command(eng.CMD_CEILING, f=dbfs) == "ack":
            self.ceiling_sent = dbfs

    def test_inject(self, what: str) -> str:
        if self.rig.profile != "test" or not self.cfg.test_hooks:
            return "unknown"  # absent from production (VS-27)
        if what in ("nan", "inf"):
            self.rig.test_inject(eng.INJECT_NAN if what == "nan" else eng.INJECT_INF)
        elif what in ("freeze_audio", "thaw_audio"):
            self.rig.test_freeze(what == "freeze_audio")
        elif what == "unplug_audio":
            self.rig.test_unplug()
        elif what == "late_callbacks":
            self.rig.test_late(4)  # an underrun storm, as the host counts one
        else:
            return "bad_args"
        return "ack"

    # ================================================================ session

    def touch_union(self) -> int:
        bits = 0
        for c in self.conns:
            bits |= c.touch
        for _t, c in self.leaving:
            bits |= c.touch
        return bits

    def apply_touch(self) -> None:
        union = self.touch_union()
        self.touch_mask &= union  # a released key is free again
        self.rig.keys_set(eng.KEYS_TOUCH, union & ~self.touch_mask & self.key_mask)

    def apply_mute(self) -> None:
        want = self.staff_mute or self.ui_muted or self.recovery_mute or self.visitor_mute
        if want != self.mute_sent:
            if self.command(eng.CMD_MUTE, 1 if want else 0) == "ack":
                self.mute_sent = want

    def session_tick(self, now: float, midi: dict) -> None:
        if self.leaving:
            due = [x for x in self.leaving if x[0] <= now]
            if due:
                self.leaving = [x for x in self.leaving if x[0] > now]
                for _t, c in due:
                    c.touch = 0
                self.apply_touch()
        # QA-ADV-07: a page that stops talking (a hung renderer keeps its socket open) has
        # released its keys after PAGE_STALE_S, and counts as gone for the 10 s mute
        stale = [c for c in self.conns if c.touch and now - c.last_msg > PAGE_STALE_S]
        for c in stale:
            self.log(f"page {c.n} silent {now - c.last_msg:.1f} s: its keys are released")
            c.touch = 0
            c.stale = True
        if stale:
            self.apply_touch()
        limit = self.cfg.ui_absent_mute_s
        if limit > 0 and not self.ui_muted and now - self.last_ui >= limit:
            self.ui_muted = True
            self.raise_fault("ui_absent_muted")
        self.apply_mute()
        touch = self.touch_union()
        if self.recovery_mute and (
            touch & ~self.touch_mask & self.key_mask
            or int(midi.get("bits", 0)) & ~int(midi.get("masked", 0)) & self.key_mask
        ):
            self.recovery_mute = False  # a new key after a recovery: the rig may sound again
            self.apply_mute()
        # PLAY-8: a key held past the limit is released until it is let go
        held = touch | int(midi.get("bits", 0))
        for k in list(self.held_since):
            if not held >> k & 1:
                del self.held_since[k]
        for k in range(64):
            if held >> k & 1:
                since = self.held_since.setdefault(k, now)
                if now - since >= self.cfg.held_key_release_s:
                    bit = 1 << k
                    if touch & bit and not self.touch_mask & bit:
                        self.touch_mask |= bit
                        self.apply_touch()
                    if int(midi.get("bits", 0)) & bit and not int(midi.get("masked", 0)) & bit:
                        self.rig.midi_mask(bit)

    # ================================================================ supervision

    def supervise(self, now: float, s, audio: dict, midi: dict) -> None:
        # engine faults: the engine has already muted (<= 8 ms); recover by HOME, with backoff
        engine_codes = F.from_engine(int(s.faults))
        for code in ("program_stalled", "dsp_fault"):
            if code in engine_codes:
                self.raise_fault(code)
            elif code in self.active and self.recover_at is None:
                self.clear_fault(code)
        if engine_codes & {"program_stalled", "dsp_fault"}:
            if self.recover_at is None:
                delay = self.cfg.recover_backoff_s[
                    min(self.recover_n, len(self.cfg.recover_backoff_s) - 1)
                ]
                self.recover_at = now + delay
            elif now >= self.recover_at:
                self.recover_n += 1
                self.log(f"recovery {self.recover_n}: HOME, muted until the next key")
                # The engine's HOME gates the voice off but does not reset it, so a note's
                # release tail from before the fault would come back with the 200 ms fade-in
                # (FLT-12: nothing before the next legitimate key). Hold a mute over the HOME
                # until a new key goes down. (Engine-lane finding: sx_engine_home could reset
                # the voice when a supervisor fault is latched.)
                self.recovery_mute = True
                self.apply_mute()
                self.home()
                self.recover_at = None
            self.healthy_since = now
        else:
            self.recover_at = None
            if now - self.healthy_since > 10.0:
                self.recover_n = 0
        # underruns (QA-ADV-06): the host's late-callback count, a storm is a named fault
        late = int(audio.get("late_callbacks", 0))
        if late < self.late_seen:  # the device was reopened: its counter starts again
            self.late_seen = 0
        if late > self.late_seen:
            self.underruns += late - self.late_seen
            self.late_times += [now] * min(late - self.late_seen, 64)
            self.late_seen = late
        n, window = UNDERRUN_STORM
        self.late_times = [t for t in self.late_times if now - t < max(window, UNDERRUN_CLEAR_S)]
        if sum(1 for t in self.late_times if now - t < window) >= n:
            self.raise_fault("audio_underruns", detail=f"{self.underruns} late callbacks")
        elif "audio_underruns" in self.active and not self.late_times:
            self.clear_fault("audio_underruns")
        # audio: lost device, retry every 2 s; stalled thread, reopen; three stalls exit
        if audio.get("lost") and "audio_device_missing" not in self.active:
            self.raise_fault("audio_device_missing", detail="the device stopped")
            self.rig.lib.sxh_audio_close()
            self.audio_retry_at = now + self.cfg.audio_retry_s
        if self.audio_retry_at is not None and now >= self.audio_retry_at:
            if self.rig.reopen_audio():
                self.audio_retry_at = None
                self.clear_fault("audio_device_missing")
                self.frames_moved_at = now
            else:
                self.audio_retry_at = now + self.cfg.audio_retry_s
        frames = int(audio.get("frames", 0))
        if frames != self.last_frames:
            self.last_frames = frames
            self.frames_moved_at = now
            if "audio_stalled" in self.active:
                self.clear_fault("audio_stalled")
        elif (
            audio.get("running")
            and self.audio_retry_at is None
            and now - self.frames_moved_at > self.cfg.stall_s
            and "audio_stalled" not in self.active
        ):
            self.raise_fault("audio_stalled", detail=f"frames frozen at {frames}")
            self.stalls = [t for t in self.stalls if now - t < 60.0] + [now]
            if len(self.stalls) >= self.cfg.stall_strikes:
                self.log("audio stalled three times in a minute: exiting for systemd")
                self.exit_code = 3
                return
            self.rig.reopen_audio()
            self.frames_moved_at = now
        # MIDI: the host released the notes already; this is the notice (VS-18)
        sources = int(midi.get("sources", 0))
        if sources and not self.midi_sources:
            self.midi_seen = True
            self.clear_fault("midi_absent")
        elif not sources and self.midi_sources and self.midi_seen:
            self.raise_fault("midi_absent")
        self.midi_sources = sources

    def latency_tick(self, s, midi: dict) -> None:
        onset = int(s.lat_t[eng.LAT_ONSET])
        if not self.lat_fh or not onset or onset == self.last_onset:
            return
        self.last_onset = onset
        rate = self.rig.rate
        lat_frames = (self.rig.audio_info or {}).get("latency_frames", 0)
        host = self.rig.frame_host_ns(onset)
        rec = {
            "t": "press",
            "arrival": int(s.lat_t[eng.LAT_ARRIVAL]),
            "latch": int(s.lat_t[eng.LAT_LATCH]),
            "first_write": int(s.lat_t[eng.LAT_FIRST_WRITE]),
            "onset": onset,
            "rate": rate,
            "onset_host_ns": host,
            "output_latency_frames": lat_frames,
            "out_host_ns": host + lat_frames * 1_000_000_000 // rate if host else 0,
            "midi_on_ns": int(midi.get("last_note_on_ns", 0)),
            "midi_note": int(midi.get("last_note_on", -1)),
        }
        self.lat_fh.write(json.dumps(rec) + "\n")

    # ================================================================ the loop

    def tick(self) -> None:
        now = time.monotonic()
        self.tick_no += 1
        if self.fatal:
            if self.tick_no % int(self.cfg.hz) == 0:
                self.broadcast(self.heartbeat_msg())
            return
        audio = self.rig.audio_status()
        midi = self.rig.midi_status()
        s = self.rig.snapshot()
        if s is not None:
            self.last_snap = s
        self.panel.feed(self.rig.samples())
        self.patch.retry()
        if self.tick_no % int(self.cfg.hz) == 0:
            self.apply_ceiling()  # quiet hours begin and end on the clock
        if self.tone_off_at is not None and now >= self.tone_off_at:
            if self.command(eng.CMD_TEST_TONE, 0) == "ack":  # queue full: next tick
                self.tone_off_at = None
        if self.exit_at is not None and now >= self.exit_at:
            self.log("staff restart of the station: exiting for systemd")
            self.exit_code = 0
            self.exit_at = None
        seg = self.rig.capture_segment_known()
        if seg:
            self.log(f"capture segment: sample {seg[0]} is engine frame {seg[1]}")
        self.session_tick(now, midi)
        if s is not None:
            self.supervise(now, s, audio, midi)
            self.latency_tick(s, midi)
            if self.conns:
                self.broadcast(self.state_msg(s), droppable=True)
                if self.tick_no % 2 == 0:
                    self.broadcast(self.scope_msg(s), droppable=True)
        if self.tick_no % int(self.cfg.hz) == 0:
            self.broadcast(self.heartbeat_msg())
        # WATCHDOG=1 only while the engine's frames advance (ARCHITECTURE 4.5)
        if now - self.frames_moved_at < 1.0 and self.tick_no % 15 == 0:
            self.notifier.watchdog()

    async def run(self, stop: asyncio.Event | None = None) -> int:
        from websockets.asyncio.server import serve

        self.start()
        stop = stop or asyncio.Event()
        async with serve(
            self.handler,
            self.cfg.host,
            self.cfg.port,
            max_size=MAX_MESSAGE,
            max_queue=64,
            ping_interval=None,
            compression=None,
        ) as server:
            port = server.sockets[0].getsockname()[1] if server.sockets else self.cfg.port
            self.log(f"listening on ws://{self.cfg.host}:{port}")
            period = 1.0 / self.cfg.hz
            nxt = time.monotonic()
            while not stop.is_set() and self.exit_code is None:
                self.tick()
                nxt += period
                delay = nxt - time.monotonic()
                if delay < -0.25:
                    nxt = time.monotonic()  # the loop was held up; do not race to catch up
                    delay = 0
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(0.0, delay))
                except TimeoutError:
                    pass
        self.shutdown()
        return self.exit_code or 0

    def shutdown(self) -> None:
        if self.rig.lib is not None and self.rig.e != eng.ffi.NULL:
            self.rig.command(eng.CMD_MUTE, 1)  # the 5 ms ramp, then close in silence
            time.sleep(0.03)
        self.rig.close()
        if self.lat_fh:
            self.lat_fh.close()
