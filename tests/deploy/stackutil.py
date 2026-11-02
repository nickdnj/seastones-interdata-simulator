"""Helpers for the station-stack tests (KP-11, KP-17, SOK-05, SOK-08, SOK-09).

``Supervised`` runs one process under ``deploy/supervise.py`` (the macOS supervisor, which does
for a child what the systemd units ask systemd to do) and reads its JSON events. ``Stack`` is
rigd on the paced null audio device plus the page server, each supervised, on free loopback
ports, with logs, pidfiles and state in pytest's temp folder. Everything is stopped by the PIDs
the test started; nothing on this machine is installed or touched.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUPERVISE = ROOT / "deploy" / "supervise.py"
PLAYABLE = ROOT / "deploy" / "playable.py"
sys.path.insert(0, str(ROOT / "src"))

from rigd import engine as eng  # noqa: E402

LIB = eng.default_lib_path()
IMAGE = ROOT / "build" / "program" / "rig.img.json"


def need_build() -> None:
    if not LIB.exists() or not IMAGE.exists():
        pytest.skip(f"needs `make host program` ({LIB.name}, {IMAGE.name}) (UNVERIFIED)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # a zombie child of ours counts as gone
    try:
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                             text=True).stdout.strip()  # fmt: skip
    except OSError:
        return True
    return bool(out) and not out.startswith("Z")


class Supervised:
    def __init__(self, tmp: Path, name: str, cmd: list[str], *, watchdog: float = 0.0,
                 restart: float = 1.0, log_kb: int = 2048, keep: int = 5,
                 env: dict | None = None, preexec=None, extra: list[str] | None = None):  # fmt: skip
        self.name = name
        self.log = tmp / "log" / f"{name}.log"
        self.pidfile = tmp / "run" / f"{name}.pid"
        args = [sys.executable, str(SUPERVISE), "--name", name, "--events", "--log", str(self.log),
                "--log-max-kb", str(log_kb), "--log-keep", str(keep), "--restart-sec",
                str(restart), "--watchdog-sec", str(watchdog), "--pidfile", str(self.pidfile),
                *(extra or []), "--", *cmd]  # fmt: skip
        e = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUNBUFFERED="1")
        e.pop("NOTIFY_SOCKET", None)
        e.update(env or {})
        self.proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env=e, preexec_fn=preexec)  # fmt: skip
        self.events: queue.Queue = queue.Queue()
        self.seen: list[dict] = []
        self.stderr: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            self.seen.append(ev)
            self.events.put(ev)

    def _read_err(self):
        for line in self.proc.stderr:
            self.stderr.append(line)

    def wait(self, event: str, timeout: float, pred=None) -> dict:
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                e = self.events.get(timeout=left)
            except queue.Empty:
                break
            if e["event"] == event and (pred is None or pred(e)):
                return e
        raise AssertionError(f"{self.name}: no {event} within {timeout} s; seen {self.seen}")

    def child_pid(self) -> int:
        starts = [e for e in self.seen if e["event"] == "start"]
        assert starts, f"{self.name} never started a child"
        return starts[-1]["pid"]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)


class Stack:
    """rigd + the page server, each under deploy/supervise.py, as the macOS agents run them."""

    def __init__(self, tmp: Path, rigd_args: list[str] | None = None, ws_port: int | None = None,
                 http_port: int | None = None, rigd_env: dict | None = None,
                 rigd_preexec=None):  # fmt: skip
        need_build()
        self.tmp = tmp
        self.ws_port = ws_port or free_port()
        self.http_port = http_port or free_port()
        self.ws = f"ws://127.0.0.1:{self.ws_port}"
        self.http = f"http://127.0.0.1:{self.http_port}/"
        self.data = tmp / "data"
        self.run = tmp / "run"
        self.procs: list[Supervised] = []
        self.rigd_cmd = [sys.executable, "-m", "rigd", "--audio", "null", "--no-midi",
                         "--port", str(self.ws_port), "--data", str(self.data),
                         *(rigd_args or [])]  # fmt: skip
        self.web_cmd = [sys.executable, str(ROOT / "src" / "web" / "serve.py"), "--port",
                        str(self.http_port), "--content", str(ROOT / "content"), "--index-dir",
                        str(tmp / "index"), "--program", str(ROOT / "build" / "program"),
                        "--run", str(self.run)]  # fmt: skip
        self.rigd = self.start_rigd(env=rigd_env, preexec=rigd_preexec)
        self.web = self.start_web()

    def start_rigd(self, env=None, preexec=None) -> Supervised:
        s = Supervised(self.tmp, "rigd", self.rigd_cmd, watchdog=5.0, env=env, preexec=preexec)
        self.procs.append(s)
        return s

    def start_web(self) -> Supervised:
        s = Supervised(self.tmp, "web", self.web_cmd, restart=2.0)
        self.procs.append(s)
        return s

    def playable(self, timeout: float = 20.0, check: str = "all") -> dict:
        p = subprocess.run([sys.executable, str(PLAYABLE), "--check", check, "--http", self.http,
                            "--ws", self.ws, "--timeout", str(timeout)],
                           capture_output=True, text=True, timeout=timeout + 30)  # fmt: skip
        rec = json.loads(p.stdout.strip().splitlines()[-1])
        rec["rc"] = p.returncode
        return rec

    def stop(self) -> None:
        for s in reversed(self.procs):
            s.stop()
