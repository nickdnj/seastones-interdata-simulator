#!/usr/bin/env python3
"""The station's process supervisor where systemd is not there to do it (macOS, launchd).

launchd's ``KeepAlive`` restarts a job that exits, but it has no watchdog and no log rotation,
so each macOS job runs its process under this file, which does for one child what
``deploy/systemd/seastones-rigd.service`` asks systemd to do (VS-17; ARCHITECTURE 10):

* **Restart=always**, ``--restart-sec`` apart, forever: a silent exhibit never gives up.
* **Type=notify + WatchdogSec** (``--watchdog-sec``, 0 = off): the child gets
  ``NOTIFY_SOCKET``; after its ``READY=1``, a gap longer than the watchdog between
  ``WATCHDOG=1`` datagrams (rigd sends them only while the engine's frames advance) gets it
  SIGABRT and, 1 s later, SIGKILL. A child that never says READY within ``--start-timeout``
  is treated the same way.
* **Logs**: the child's stdout and stderr go to ``--log``, rotated at ``--log-max-kb`` with
  ``--log-keep`` old files. The pipe is always drained, even when the disk is full or the log
  cannot be written, so a full disk never blocks the child on a write (it would then stop
  feeding its watchdog and be killed for nothing). Lost lines are counted, not fatal.
* **No orphans**: the child's PID is kept in ``--pidfile``. A supervisor that was itself
  killed with SIGKILL leaves its child running (launchd kills the job's process group; a
  hand-started stack has nobody to do that), so the next supervisor stops a previous child
  whose command line still matches before starting its own (Model 4 lesson: pidfiles).
  On Linux the child also gets ``PR_SET_PDEATHSIG`` = SIGTERM.
* **Safe stop**: SIGTERM or SIGINT is passed to the child as SIGTERM (rigd ramps its output
  to silence and closes the device), then SIGKILL after ``--stop-timeout``.

Each event is one JSON line (``start``, ``ready``, ``watchdog_timeout``, ``exit``,
``log_write_failed``, ``reaped_orphan``) written to the log, and with ``--events`` to stdout
as well, stamped with ``time.monotonic()`` so tests can measure recovery.

    deploy/supervise.py --name rigd --log /data/log/rigd.log --watchdog-sec 5 \\
        --pidfile /data/run/rigd.pid -- python3 -m rigd ...
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time


class RotatingLog:
    """Size-rotated append-only log that never raises (a full disk loses lines, nothing else)."""

    def __init__(self, path: str | None, max_bytes: int, keep: int):
        self.path, self.max_bytes, self.keep = path, max_bytes, keep
        self.fh = None
        self.size = 0
        self.failed = 0  # lines lost since the last report
        self.lock = threading.Lock()

    def _open(self) -> None:
        if self.fh is None and self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            self.fh = open(self.path, "ab")  # noqa: SIM115
            self.size = self.fh.tell()

    def _rotate(self) -> None:
        if self.fh is not None:
            self.fh.close()
            self.fh = None
        for i in range(self.keep - 1, 0, -1):
            src = f"{self.path}.{i}"
            if os.path.exists(src):
                os.replace(src, f"{self.path}.{i + 1}")
        if self.keep > 0:
            os.replace(self.path, f"{self.path}.1")
        else:
            os.unlink(self.path)

    def write(self, data: bytes) -> bool:
        if not self.path:
            return True
        with self.lock:
            try:
                self._open()
                if self.size and self.size + len(data) > self.max_bytes:
                    self._rotate()
                    self._open()
                self.fh.write(data)
                self.fh.flush()
                self.size += len(data)
                return True
            except OSError:
                self.failed += 1
                with contextlib.suppress(OSError):
                    if self.fh is not None:
                        self.fh.close()
                self.fh = None
                return False


def stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Supervisor:
    def __init__(self, args, cmd: list[str]):
        self.args, self.cmd = args, cmd
        self.log = RotatingLog(args.log, args.log_max_kb * 1024, args.log_keep)
        self.stopping = False
        self.child: subprocess.Popen | None = None
        self.last_fail_report = 0.0

    def emit(self, event: str, **kw) -> None:
        line = json.dumps({"event": event, "name": self.args.name, "t": time.monotonic(), **kw})
        if self.args.events:
            print(line, flush=True)
        self.log.write(f"{stamp()} supervise: {line}\n".encode())

    def drain(self, pipe) -> None:
        """Copy the child's output to the log, line by line, until the pipe closes."""
        for raw in iter(pipe.readline, b""):
            if not self.log.write(stamp().encode() + b" " + raw):
                now = time.monotonic()
                if now - self.last_fail_report > 60.0:
                    self.last_fail_report = now
                    lost, self.log.failed = self.log.failed, 0
                    print(f"supervise[{self.args.name}]: cannot write {self.args.log}; "
                          f"{lost} line(s) lost, still running", file=sys.stderr, flush=True)  # fmt: skip
                    if self.args.events:
                        print(json.dumps({"event": "log_write_failed", "name": self.args.name,
                                          "t": now, "lost": lost}), flush=True)  # fmt: skip
        pipe.close()

    # ---------------------------------------------------------------- orphans

    def reap_orphan(self) -> None:
        pf = self.args.pidfile
        if not pf:
            return
        try:
            pid = int(open(pf).read().strip())
        except (OSError, ValueError):
            return
        if pid <= 1 or pid == os.getpid():
            return
        try:
            out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=5).stdout  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return
        # ours only if its command line still carries our child's own arguments (a PID that
        # has been reused by something else is left alone)
        tail = " ".join(self.cmd[1:4]) or self.cmd[0]
        if not out.strip() or tail not in out:
            return
        self.emit("reaped_orphan", pid=pid, command=out.strip()[:200])
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                return
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)

    def write_pidfile(self, pid: int) -> None:
        if self.args.pidfile:
            with contextlib.suppress(OSError):
                os.makedirs(os.path.dirname(os.path.abspath(self.args.pidfile)), exist_ok=True)
                tmp = self.args.pidfile + ".tmp"
                with open(tmp, "w") as fh:
                    fh.write(f"{pid}\n")
                os.replace(tmp, self.args.pidfile)

    # ---------------------------------------------------------------- the loop

    def run(self) -> int:
        a = self.args
        tmp = tempfile.mkdtemp(prefix="sx-notify-")
        path = os.path.join(tmp, "notify")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(path)
        sock.settimeout(0.05)

        def stop(_sig, _frm):
            self.stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        self.reap_orphan()
        starts = 0
        try:
            while not self.stopping and (not a.max_starts or starts < a.max_starts):
                starts += 1
                env = dict(os.environ)
                if a.watchdog_sec > 0:
                    env["NOTIFY_SOCKET"] = path
                else:
                    env.pop("NOTIFY_SOCKET", None)
                self.child = subprocess.Popen(
                    [c.replace("{n}", str(starts)) for c in self.cmd],
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=pdeathsig if sys.platform.startswith("linux") else None,
                )  # fmt: skip
                child = self.child
                reader = threading.Thread(target=self.drain, args=(child.stdout,), daemon=True)
                reader.start()
                self.write_pidfile(child.pid)
                self.emit("start", n=starts, pid=child.pid)
                started = time.monotonic()
                ready = a.watchdog_sec <= 0
                last_ping = started
                abort_at = None
                while child.poll() is None and not self.stopping:
                    try:
                        data = sock.recv(4096).decode(errors="replace")
                    except (TimeoutError, BlockingIOError):
                        data = ""
                    except OSError:
                        data = ""
                        time.sleep(0.05)
                    now = time.monotonic()
                    for line in data.splitlines():
                        if line == "READY=1" and not ready:
                            ready = True
                            last_ping = now
                            self.emit("ready", n=starts, pid=child.pid, after_s=now - started)
                        elif line == "WATCHDOG=1":
                            last_ping = now
                    if abort_at is None and a.watchdog_sec > 0:
                        late = (ready and now - last_ping > a.watchdog_sec) or (
                            not ready and now - started > a.start_timeout
                        )
                        if late:
                            self.emit("watchdog_timeout", n=starts, pid=child.pid,
                                      silent_s=now - last_ping, ready=ready)  # fmt: skip
                            with contextlib.suppress(OSError):
                                child.send_signal(signal.SIGABRT)
                                os.kill(child.pid, signal.SIGCONT)  # a stopped child takes it
                            abort_at = now + 1.0
                    if abort_at is not None and now > abort_at and child.poll() is None:
                        child.kill()
                if child.poll() is None:  # stopping: the child's own safe shutdown first
                    child.send_signal(signal.SIGTERM)
                    try:
                        child.wait(a.stop_timeout)
                    except subprocess.TimeoutExpired:
                        child.kill()
                code = child.wait()
                reader.join(2.0)
                self.emit("exit", n=starts, pid=child.pid, code=code)
                if not self.stopping:
                    end = time.monotonic() + a.restart_sec
                    while not self.stopping and time.monotonic() < end:
                        time.sleep(0.05)
        finally:
            if self.child is not None and self.child.poll() is None:
                self.child.kill()
            sock.close()
            with contextlib.suppress(OSError):
                os.unlink(path)
                os.rmdir(tmp)
            if a.pidfile:
                with contextlib.suppress(OSError):
                    os.unlink(a.pidfile)
        return 0


def pdeathsig() -> None:
    """In the child, before exec (Linux only): SIGTERM when the supervisor dies."""
    try:
        import ctypes

        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="supervise.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="child")
    ap.add_argument("--log", help="the child's output, rotated (default: discarded)")
    ap.add_argument("--log-max-kb", type=int, default=2048)
    ap.add_argument("--log-keep", type=int, default=5)
    ap.add_argument("--restart-sec", type=float, default=1.0)
    ap.add_argument("--watchdog-sec", type=float, default=0.0, help="0: no watchdog")
    ap.add_argument("--start-timeout", type=float, default=30.0, help="READY=1 within this")
    ap.add_argument("--stop-timeout", type=float, default=3.0)
    ap.add_argument("--pidfile")
    ap.add_argument("--max-starts", type=int, default=0, help="0: no limit (tests only)")
    ap.add_argument("--events", action="store_true", help="also print events to stdout")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("no command")
    return Supervisor(args, cmd).run()


if __name__ == "__main__":
    sys.exit(main())
