"""VS-17: kill -9 and SIGSTOP under supervision, on the Mac's stand-in for systemd
(scripts/supervise-stub.py: Restart=always, RestartSec=1, WatchdogSec=5, sd_notify), and the
unit files themselves (FLT-01, FLT-02, ENG-11).

What "silence" means here: the output is the capture of what rigd hands its (null) device.
After kill -9 the process and its device are gone, so the output ends at once; after SIGSTOP
the callback no longer runs. On the station a real codec must also stop rather than loop its
ring on underrun: that is a hardware property, S-6 (SP-S6), not testable in software.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from conftest import ROOT, Client, free_port, need_build, rms, sounding

UNIT = ROOT / "deploy" / "systemd" / "seastones-rigd.service"
KEY12 = 1 << 12


class Supervised:
    def __init__(self, tmp: Path):
        need_build()
        self.port = free_port()
        self.url = f"ws://127.0.0.1:{self.port}"
        self.tmp = tmp
        cmd = [sys.executable, str(ROOT / "scripts" / "supervise-stub.py"), "--",
               sys.executable, "-m", "rigd", "--audio", "null", "--no-midi",
               "--port", str(self.port), "--capture", str(tmp / "out-{n}.f32")]  # fmt: skip
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True, env=env)
        self.events: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                pass

    def wait(self, event: str, timeout: float) -> dict:
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                e = self.events.get(timeout=left)
            except queue.Empty:
                break
            if e["event"] == event:
                return e
        raise AssertionError(f"no {event} within {timeout} s")

    def capture(self, n: int) -> Path:
        return self.tmp / f"out-{n}.f32"

    def stop(self):
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for f in self.tmp.glob("out-*.f32"):
            f.unlink()


@pytest.fixture
def supervised(tmp_path):
    s = Supervised(tmp_path)
    yield s
    s.stop()


def connect(url: str, timeout: float) -> Client:
    end = time.monotonic() + timeout
    while True:
        try:
            return Client(url)
        except OSError:
            if time.monotonic() > end:
                raise
            time.sleep(0.05)


def play(c: Client, timeout: float = 3.0) -> dict:
    c.touch(KEY12)
    return c.until(lambda m: m["t"] == "state" and sounding(m) and not m["muted"], timeout)


def grows(path: Path, during: float) -> bool:
    a = path.stat().st_size
    time.sleep(during)
    return path.stat().st_size > a


@pytest.mark.parametrize("how", ["kill9", "sigstop"])
def test_fault_gives_silence_and_recovery_to_playable_within_10_s(supervised, how):
    first = supervised.wait("ready", 15)
    c = connect(supervised.url, 5)
    play(c)
    c.pump(0.5)
    out1 = supervised.capture(1)
    assert rms(np.fromfile(out1, dtype="<f4")[-12000:]) > 0.01, "playing before the fault"
    t0 = time.monotonic()
    os.kill(first["pid"], signal.SIGKILL if how == "kill9" else signal.SIGSTOP)
    time.sleep(0.1)
    # silence within 100 ms: nothing more reaches the device once the process is dead or stopped
    assert not grows(out1, 0.4), "no output after the fault"
    if how == "sigstop":
        timeout = supervised.wait("watchdog_timeout", 8)
        assert 4.5 <= timeout["t"] - t0 <= 6.5, "WatchdogSec=5 caught the hang"
    second = supervised.wait("ready", 12)
    assert second["pid"] != first["pid"]
    c2 = connect(supervised.url, 5)
    st = play(c2)
    t_play = time.monotonic() - t0
    assert t_play < 10.0, f"playable again {t_play:.1f} s after {how}"
    c2.pump(0.5)
    assert rms(np.fromfile(supervised.capture(2), dtype="<f4")[-12000:]) > 0.01
    assert st["frames"] < 10 * 48000  # a new engine, started from frame 0
    for cl in (c, c2):
        try:
            cl.close()
        except Exception:  # noqa: BLE001 (the first page's socket died with its rigd)
            pass
    print(f"\n{how}: playable again after {t_play:.2f} s")


def test_the_unit_file_says_what_the_architecture_says():
    """ARCHITECTURE 4.1 / ADR-006: Restart=always, RestartSec=1, WatchdogSec=5, sd_notify,
    LimitRTPRIO, never giving up, loopback only. systemd-analyze verify runs in
    scripts/verify-units.sh (Docker on the Mac; directly on Linux)."""
    text = UNIT.read_text()
    unit = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            unit.setdefault((section, k), v)
    want = {
        ("Unit", "StartLimitIntervalSec"): "0",
        ("Service", "Type"): "notify",
        ("Service", "Restart"): "always",
        ("Service", "RestartSec"): "1",
        ("Service", "WatchdogSec"): "5",
        ("Service", "TimeoutAbortSec"): "1",
        ("Service", "LimitRTPRIO"): "70",
        ("Service", "IPAddressDeny"): "any",
        ("Service", "IPAddressAllow"): "localhost",
    }
    for k, v in want.items():
        assert unit.get(k) == v, (k, unit.get(k))
    assert ("Service", "RestrictRealtime") not in unit  # it would forbid SCHED_FIFO
    assert ("Service", "PrivateDevices") not in unit  # it would hide /dev/snd


def test_systemd_analyze_verify_where_systemd_exists():
    if sys.platform != "linux" or not Path("/usr/bin/systemd-analyze").exists():
        pytest.skip("not a systemd host: scripts/verify-units.sh runs it in Docker (see record)")
    out = subprocess.run(
        ["bash", str(ROOT / "scripts" / "verify-units.sh")],
        env=dict(os.environ, SX_VERIFY_LOCAL="1"), capture_output=True, text=True,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
