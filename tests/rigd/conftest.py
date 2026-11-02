"""Fixtures for rigd's tests (VS-14, VS-17, VS-18): a real rigd on the null audio device.

``rigd_proc`` starts ``python3 -m rigd`` as a child on a free loopback port with the paced
null device (real time, no hardware, nothing audible) and, when asked, a capture of its output
in pytest's temp folder. It is stopped by its own PID. ``Client`` is a small synchronous
protocol client that validates every server message against src/rigd/schema/.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rigd import engine as eng  # noqa: E402
from rigd import schema  # noqa: E402

LIB = eng.default_lib_path()
IMAGE = ROOT / "build" / "program" / "rig.img.json"
SXKEYS = ROOT / "build" / "tools" / "sxkeys"
MIDI_PREFIX = f"sxkeys-{os.getpid()}-"  # the names of this process's virtual keyboards


def need_build() -> None:
    if not LIB.exists() or not IMAGE.exists():
        pytest.skip(f"needs `make host program` ({LIB.name}, {IMAGE.name}) (UNVERIFIED)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Rigd:
    def __init__(self, tmp: Path, args: list[str], capture: bool, env: dict | None = None):
        need_build()
        self.port = free_port()
        self.url = f"ws://127.0.0.1:{self.port}"
        self.log_path = tmp / f"rigd-{self.port}.log"
        self.capture = tmp / f"out-{self.port}.f32" if capture else None
        cmd = [sys.executable, "-m", "rigd", "--port", str(self.port)]
        if "--audio" not in args:
            cmd += ["--audio", "null"]  # paced, no hardware, nothing audible
        if self.capture:
            cmd += ["--capture", str(self.capture)]
        if "--no-midi" not in args and "--midi-source" not in args:
            # only this test process's own virtual keyboards: other lanes on this machine run
            # theirs at the same time, and CoreMIDI sources are system-wide
            cmd += ["--midi-source", MIDI_PREFIX]
        if "--data" not in args:
            cmd += ["--data", str(tmp / f"data-{self.port}")]  # staff.conf, saves
        cmd += args
        e = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUNBUFFERED="1")
        e.pop("NOTIFY_SOCKET", None)
        e.update(env or {})
        self.log = open(self.log_path, "w")  # noqa: SIM115
        self.proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT, env=e
        )
        self.wait_for("listening on", 10)

    def text(self) -> str:
        return self.log_path.read_text()

    def wait_for(self, needle: str, timeout: float) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.text():
                return
            if self.proc.poll() is not None:
                break
            time.sleep(0.02)
        raise AssertionError(f"rigd never said {needle!r}:\n{self.text()}")

    def stop(self) -> int | None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.log.close()
        return self.proc.returncode

    def audio(self) -> np.ndarray:
        """The captured output so far (channel 0, float32)."""
        return np.fromfile(self.capture, dtype="<f4") if self.capture.exists() else np.zeros(0)

    def segments(self) -> list[tuple[int, int]]:
        """(file sample, engine frame) where each capture segment starts (rigd's log)."""
        return [
            (int(m.group(1)), int(m.group(2)))
            for m in re.finditer(
                r"capture segment: sample (\d+) is engine frame (\d+)", self.text()
            )
        ]

    def at_frames(self, f0: int, f1: int) -> np.ndarray:
        """The captured samples for engine frames [f0, f1), from the segment holding f0."""
        segs = self.segments()
        assert segs, "rigd has not logged its capture segment yet"
        sample, frame = max((s for s in segs if s[1] <= f0), key=lambda s: s[1], default=segs[0])
        x = self.audio()
        return x[max(0, sample + f0 - frame) : max(0, sample + f1 - frame)]


@pytest.fixture
def rigd_factory(tmp_path):
    started: list[Rigd] = []

    def make(*args: str, capture: bool = False, env: dict | None = None) -> Rigd:
        r = Rigd(tmp_path, list(args), capture, env)
        started.append(r)
        return r

    yield make
    for r in started:
        r.stop()
        if r.capture and r.capture.exists():
            r.capture.unlink()  # no audio is kept anywhere (RE-1)


@pytest.fixture
def rigd_proc(rigd_factory):
    return rigd_factory("--no-midi", "--test-hooks", capture=True)


class Client:
    """Synchronous protocol v1 client; every server message is schema-checked."""

    def __init__(self, url: str):
        from websockets.sync.client import connect

        # an unbounded receive queue: the library's reader thread then never stalls on a client
        # that is busy sending (the fuzz test), so a close handshake always completes
        self.ws = connect(url, max_size=None, max_queue=None, open_timeout=5)
        self.seen: list[dict] = []
        self.invalid: list[tuple[str, list[str]]] = []
        self.next_id = 1
        self.cursor = 0  # messages before it have been looked at (until) or pumped

    def _recv(self, seconds: float) -> list[dict]:
        end = time.monotonic() + seconds
        got = []
        while (left := end - time.monotonic()) > 0:
            try:
                raw = self.ws.recv(timeout=left)
            except TimeoutError:
                break
            m = json.loads(raw)
            errs = schema.validate("server", m, extensions=False)
            if errs:
                self.invalid.append((m.get("t"), errs))
            self.seen.append(m)
            got.append(m)
        return got

    def pump(self, seconds: float) -> list[dict]:
        """Receive for `seconds`; everything received counts as looked at."""
        got = self._recv(seconds)
        self.cursor = len(self.seen)
        return got

    def last(self, t: str) -> dict | None:
        for m in reversed(self.seen):
            if m["t"] == t:
                return m
        return None

    def mark(self) -> int:
        """A position in `seen`; pass it to until(since=...) to also look at what came after."""
        return len(self.seen)

    def until(self, pred, timeout: float = 3.0, since: int | None = None) -> dict:
        """The first message matching `pred` that nobody has looked at yet (or since `since`).
        Messages that arrived in the same batch after the match stay unread for the next call,
        so a reply's companion (an ack and its patch or staff message) is never lost."""
        start = self.cursor if since is None else min(since, self.cursor)
        end = time.monotonic() + timeout
        i = start
        while True:
            while i < len(self.seen):
                m = self.seen[i]
                i += 1
                if pred(m):
                    self.cursor = max(self.cursor, i)
                    return m
            self.cursor = max(self.cursor, i)
            if time.monotonic() >= end:
                break
            self._recv(0.05)
        raise AssertionError("condition not met within timeout")

    def send(self, msg: dict) -> None:
        self.ws.send(json.dumps({"v": 1, **msg}))

    def command(self, msg: dict, timeout: float = 2.0) -> dict:
        mid = self.next_id
        self.next_id += 1
        self.send({**msg, "id": mid})
        return self.until(lambda m: m["t"] in ("ack", "nack") and m.get("id") == mid, timeout)

    def touch(self, bits: int) -> None:
        self.bits = bits
        self.send({"t": "keys.touch", "bits": f"{bits & (2**64 - 1):016X}"})

    def refresh(self) -> None:
        """Behave like the page: send the touch level at 4 Hz from now on (keyboard.js), so
        rigd does not take this client for a frozen page (QA-ADV-07: silent 1 s = keys up)."""
        if getattr(self, "_refresher", None):
            return
        self.bits = getattr(self, "bits", 0)
        self._stop = threading.Event()

        def run() -> None:
            while not self._stop.wait(0.25):
                try:
                    self.send({"t": "keys.touch", "bits": f"{self.bits & (2**64 - 1):016X}"})
                except Exception:  # noqa: BLE001 (closed)
                    return

        self._refresher = threading.Thread(target=run, daemon=True)
        self._refresher.start()

    def close(self) -> None:
        if getattr(self, "_refresher", None):
            self._stop.set()
        self.ws.close()


@pytest.fixture
def client_factory():
    made: list[Client] = []

    def make(url: str) -> Client:
        c = Client(url)
        made.append(c)
        return c

    yield make
    for c in made:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


class Keys:
    """tools/host/sxkeys: a virtual MIDI keyboard rigd sees like a USB one."""

    _n = 0

    def __init__(self):
        if not SXKEYS.exists():
            pytest.skip("needs `make host` (build/tools/sxkeys)")
        Keys._n += 1
        self.name = f"{MIDI_PREFIX}{Keys._n}"
        self.proc = subprocess.Popen(
            [str(SXKEYS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1
        )
        self.lines: queue.Queue = queue.Queue()
        # read its output all the time, so a long burst can never fill the pipe and stall it
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for out in self.proc.stdout:
            try:
                self.lines.put(json.loads(out))
            except ValueError:
                pass

    def do(self, line: str, expect: str | None = None, timeout: float = 15.0) -> dict | None:
        if line == "plug":
            line = f"plug {self.name}"
        if expect is not None:
            while not self.lines.empty():  # only what this command prints counts
                self.lines.get_nowait()
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        if expect is None:
            return None
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                m = self.lines.get(timeout=left)
            except queue.Empty:
                break
            if m.get("t") == "error":
                raise AssertionError(f"sxkeys: {line} failed")
            if m.get("t") == expect:
                return m
        raise AssertionError(f"sxkeys: no {expect} after {line}")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.write("quit\n")
            self.proc.stdin.flush()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture
def keys():
    k = Keys()
    yield k
    k.close()


def sounding(m: dict) -> bool:
    """A state message in which any voice holds a note (its gate high: watch.voices)."""
    return m.get("t") == "state" and any(v is not None for v in m["watch"]["voices"])


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
