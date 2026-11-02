"""The station stack under its supervisor, attacked (KP-11, KP-17; SOK-05, SOK-08, SOK-09, FLT-01).

Each process of the stack is killed with SIGKILL in turn (rigd, the page server, the browser,
each supervisor); ports are taken by somebody else first; the disk is "full" (RLIMIT_FSIZE, so
every file write fails with EFBIG exactly as a full /data would); the wall clock jumps. The
station must come back by itself, or stay silent and say why, every time.

On the station systemd does the supervising (deploy/systemd/); these runs use
deploy/supervise.py, which is what the macOS launch agents run and which implements the same
contract (Restart=always, WatchdogSec from rigd's WATCHDOG=1 heartbeat). The systemd half is
checked by `systemd-analyze verify` (scripts/verify-units.sh); kill -9 under real systemd is a
box test (SOK-05), listed as needs-human in the handoff.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from stackutil import ROOT, Supervised, alive, free_port

KEY12 = 1 << 12


def client(url: str, timeout: float = 10.0):
    from websockets.sync.client import connect

    end = time.monotonic() + timeout
    while True:
        try:
            return connect(url, open_timeout=2, max_size=None)
        except OSError:
            if time.monotonic() > end:
                raise
            time.sleep(0.1)


def messages(ws, seconds: float) -> list[dict]:
    out, end = [], time.monotonic() + seconds
    while (left := end - time.monotonic()) > 0:
        try:
            out.append(json.loads(ws.recv(timeout=left)))
        except TimeoutError:
            break
    return out


def sounding_after_touch(url: str) -> bool:
    ws = client(url)
    try:
        ws.send(json.dumps({"v": 1, "t": "keys.touch", "bits": f"{KEY12:016X}"}))
        for m in messages(ws, 3.0):
            if m["t"] == "state" and any(v is not None for v in m["watch"]["voices"]):
                return True
        return False
    finally:
        ws.close()


# ------------------------------------------------------------------------- boot to playable


def test_the_stack_is_playable_within_seconds_of_starting(stack_factory):
    """KP-17 software half: from process start to playable (page up with our header, engine
    alive, audio ok). The box adds BIOS, kernel, X and Chromium on top (SYS-01, needs-human)."""
    t0 = time.monotonic()
    s = stack_factory()
    rec = s.playable(timeout=20)
    took = time.monotonic() - t0
    assert rec["playable"] and rec["rc"] == 0, rec
    assert took < 10.0, f"playable {took:.1f} s after start"
    assert sounding_after_touch(s.ws)
    print(f"\nstack start to playable: {took:.2f} s")


# ------------------------------------------------------------------------- kill -9, each process


def test_kill9_rigd_comes_back_playable_and_the_page_server_is_untouched(stack_factory):
    s = stack_factory()
    assert s.playable()["playable"]
    s.rigd.wait("ready", 15)
    old, web_pid = s.rigd.child_pid(), s.web.child_pid()
    t0 = time.monotonic()
    os.kill(old, signal.SIGKILL)
    s.rigd.wait("exit", 5, lambda e: e["pid"] == old)
    s.rigd.wait("ready", 15, lambda e: e["pid"] != old)
    rec = s.playable(timeout=15)
    took = time.monotonic() - t0
    assert rec["playable"], rec
    assert took < 10.0, f"playable again {took:.1f} s after kill -9 rigd (NFR-4: 10 s)"
    assert s.web.child_pid() == web_pid and alive(web_pid), "the page server shares no fate"


def test_sigstop_rigd_is_caught_by_its_heartbeat_watchdog(stack_factory):
    s = stack_factory()
    first = s.rigd.wait("ready", 15)
    t0 = time.monotonic()
    os.kill(first["pid"], signal.SIGSTOP)
    timeout = s.rigd.wait("watchdog_timeout", 9)
    assert 5.0 <= timeout["silent_s"] < 6.5, timeout  # WatchdogSec=5 from the last WATCHDOG=1
    s.rigd.wait("ready", 15, lambda e: e["pid"] != first["pid"])
    assert s.playable(timeout=10)["playable"]
    assert time.monotonic() - t0 < 15.0


def test_kill9_page_server_comes_back_and_rigd_keeps_running(stack_factory):
    s = stack_factory()
    assert s.playable()["playable"]
    old, rigd_pid = s.web.child_pid(), s.rigd.child_pid()
    t0 = time.monotonic()
    os.kill(old, signal.SIGKILL)
    s.web.wait("start", 6, lambda e: e["pid"] != old)
    rec = s.playable(timeout=10)
    assert rec["playable"], rec
    assert time.monotonic() - t0 < 8.0
    assert s.rigd.child_pid() == rigd_pid and alive(rigd_pid)


@pytest.mark.parametrize("which", ["rigd", "web"])
def test_kill9_of_a_supervisor_leaves_no_orphan_holding_the_port(stack_factory, which):
    """Without launchd (which kills the job's process group) a supervisor killed with SIGKILL
    leaves its child running and holding the port. The next supervisor finds it by its
    pidfile and command line and stops it before starting its own."""
    s = stack_factory()
    assert s.playable()["playable"]
    sup = s.rigd if which == "rigd" else s.web
    orphan = sup.child_pid()
    os.kill(sup.proc.pid, signal.SIGKILL)
    sup.proc.wait(5)
    time.sleep(0.5)
    assert alive(orphan), "the child outlived its supervisor (the case being tested)"
    new = s.start_rigd() if which == "rigd" else s.start_web()
    reaped = new.wait("reaped_orphan", 10)
    assert reaped["pid"] == orphan
    new.wait("start", 10)
    rec = s.playable(timeout=15)
    assert rec["playable"], rec
    assert not alive(orphan)
    assert new.child_pid() != orphan


FAKE_BROWSER = """#!/bin/sh
# a stand-in for Chromium: records its arguments, then waits like a browser, keeping them on
# its command line (restart-browser.sh finds the kiosk browser by its --user-data-dir)
echo "$$ $*" >> "{log}"
exec "{py}" -c "import time; time.sleep(600)" "$@"
"""


def test_kill9_browser_is_relaunched_and_a_stale_page_restarts_it(stack_factory, tmp_path):
    """kiosk.sh under its supervisor (the macOS agent; the Linux .xinitrc loop does the same),
    with a fake browser: SIGKILL it and it is back in about 3 s; stop the page heartbeat and the
    watchdog closes it through restart-browser.sh, which only matches our own profile dir."""
    s = stack_factory()
    assert s.playable()["playable"]
    launches = tmp_path / "browser-launches.txt"
    fake = tmp_path / "fake-browser"
    fake.write_text(FAKE_BROWSER.format(log=launches, py=sys.executable))
    fake.chmod(0o755)
    data = tmp_path / "kdata"
    env = {"SX_DEST": str(ROOT), "SX_DATA": str(data), "SX_URL": s.http,
           "SX_BROWSER": str(fake), "SX_PYTHON": sys.executable,
           "SX_CONF": str(ROOT / "deploy" / "station.conf")}  # fmt: skip
    # SX_DEST is the repo: kiosk.sh finds deploy/playable.py and deploy/boot-wait.html there
    k = Supervised(tmp_path, "kiosk", ["/bin/bash", str(ROOT / "deploy" / "kiosk.sh")],
                   restart=3.0, env=env)  # fmt: skip
    s.procs.append(k)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not (launches.exists() and launches.read_text()):
        time.sleep(0.1)
    first = launches.read_text().split("\n")[0].split(" ", 1)
    assert "--kiosk" in first[1] and f"--user-data-dir={data}/chrome" in first[1]
    assert first[1].rstrip().endswith(s.http), "opened our page, not the holding page"
    pid = int(first[0])
    t0 = time.monotonic()
    os.kill(pid, signal.SIGKILL)
    while time.monotonic() - t0 < 10 and len(launches.read_text().splitlines()) < 2:
        time.sleep(0.1)
    assert len(launches.read_text().splitlines()) == 2, "relaunched after kill -9"
    took = time.monotonic() - t0
    assert took < 8.0, f"browser back after {took:.1f} s"
    # the page watchdog: a heartbeat that stopped changing, judged on the monotonic clock
    run = s.run
    (run / "page-heartbeat").write_text("1")
    restart = [str(ROOT / "deploy" / "restart-browser.sh")]
    wd = [sys.executable, str(ROOT / "deploy" / "watchdog.py"), "--run", str(run), "--restart",
          restart[0], "--conf", str(ROOT / "deploy" / "station.conf")]  # fmt: skip
    wenv = dict(os.environ, SX_DATA=str(data), SX_BROWSER_GRACE_S="2")
    now = time.monotonic() + 1000  # past the boot grace
    subprocess.run([*wd, "--now", str(now)], env=wenv, check=True)  # first look: fresh
    second_pid = int(launches.read_text().splitlines()[1].split()[0])
    subprocess.run([*wd, "--now", str(now + 61)], env=wenv, check=True)  # 61 s unchanged
    assert not alive(second_pid), "the watchdog closed the stale browser"
    t1 = time.monotonic()
    while time.monotonic() - t1 < 10 and len(launches.read_text().splitlines()) < 3:
        time.sleep(0.1)
    assert len(launches.read_text().splitlines()) == 3, "and the loop opened a fresh one"


# ------------------------------------------------------------------------- port conflicts


def squat(port: int, http: bool = False):
    """Somebody else's listener on a port; an HTTP one answers 200 without our header."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(16)
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except (TimeoutError, OSError):
                continue
            if http:
                try:
                    c.recv(4096)
                    c.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>not us</h1>")
                except OSError:
                    pass
            c.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    def release():
        stop.set()
        t.join(2)
        srv.close()

    return release


def test_rigd_port_taken_stays_silent_says_why_and_recovers_when_freed(stack_factory):
    port = free_port()
    release = squat(port)
    s = stack_factory(ws_port=port)
    first = s.rigd.wait("exit", 15)
    assert first["code"] != 0
    s.rigd.wait("exit", 10)  # and again: it keeps trying, it never gives up
    rec = s.playable(timeout=2)
    assert not rec["playable"] and "rigd not answering" in rec["why"], rec
    text = s.rigd.log.read_text()
    assert "address already in use" in text.lower() or "errno 48" in text.lower() \
        or "errno 98" in text.lower(), text[-2000:]  # fmt: skip
    release()
    s.rigd.wait("ready", 15)
    assert s.playable(timeout=10)["playable"]


def test_page_port_taken_by_another_server_is_never_shown(stack_factory):
    port = free_port()
    release = squat(port, http=True)
    s = stack_factory(http_port=port)
    s.web.wait("exit", 15)
    rec = s.playable(timeout=2, check="page")
    assert not rec["playable"] and "not our page server" in rec["why"], rec
    release()
    s.web.wait("start", 10)
    assert s.playable(timeout=15)["playable"]


# ------------------------------------------------------------------------- disk full


def fsize_limit(nbytes: int):
    def pre():
        resource.setrlimit(resource.RLIMIT_FSIZE, (nbytes, nbytes))

    return pre


CHATTY = textwrap.dedent("""
    import os, socket, sys, time
    path = os.environ.get("NOTIFY_SOCKET")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.sendto(b"READY=1", path)
    end = time.monotonic() + 8
    while time.monotonic() < end:
        sys.stdout.write("x" * 199 + "\\n")
        sys.stdout.flush()
        s.sendto(b"WATCHDOG=1", path)
        time.sleep(0.001)
""")


def test_a_full_disk_loses_log_lines_never_the_child(tmp_path):
    """Every log write fails (EFBIG past 16 KB, as ENOSPC on a full /data). The supervisor must
    still drain the pipe, or the child blocks on stdout, stops feeding its watchdog and is
    killed for nothing."""
    s = Supervised(tmp_path, "chatty", [sys.executable, "-c", CHATTY], watchdog=2.0,
                   preexec=fsize_limit(16 * 1024), log_kb=4096)  # fmt: skip
    try:
        s.wait("ready", 10)
        ev = s.wait("exit", 20)
        assert ev["code"] == 0, "the child ran to its end"
        assert not [e for e in s.seen if e["event"] == "watchdog_timeout"]
        assert any(e["event"] == "log_write_failed" for e in s.seen)
        assert s.log.stat().st_size <= 16 * 1024
        assert any("cannot write" in line for line in s.stderr)
    finally:
        s.stop()


def test_logs_rotate_at_the_size_and_keep_the_count(tmp_path):
    cmd = [
        sys.executable,
        "-c",
        "import sys\nfor i in range(3000): print('line %05d' % i + '.' * 40)",
    ]
    s = Supervised(tmp_path, "rot", cmd, log_kb=8, keep=2, extra=["--max-starts", "1"])
    s.proc.wait(20)
    names = sorted(p.name for p in s.log.parent.iterdir())
    assert names == ["rot.log", "rot.log.1", "rot.log.2"], names
    for p in s.log.parent.iterdir():
        assert p.stat().st_size <= 8 * 1024 + 200
    assert "line 02999" in s.log.read_text()


def test_rigd_with_no_space_for_its_state_still_plays(stack_factory):
    """ENG-09 / SOK-09 (rigd's part): staff.conf cannot be written; rigd still plays."""
    s = stack_factory(rigd_preexec=fsize_limit(1))
    assert s.playable()["playable"]
    assert sounding_after_touch(s.ws)
    assert not (s.data / "staff.conf").exists() or (s.data / "staff.conf").stat().st_size <= 1


# ------------------------------------------------------------------------- clock jumps


JUMPER = textwrap.dedent("""
    # sitecustomize for the clock-jump test: the wall clock (time.time) jumps 3 days forward
    # 2 s after start, then back to 1970 (a dead RTC) 2 s later. time.monotonic is untouched,
    # as on a real machine.
    import threading, time
    _real = time.time
    _off = [0.0]
    time.time = lambda: _real() + _off[0]
    def _jump():
        time.sleep(2.0); _off[0] = 3 * 86400.0
        time.sleep(2.0); _off[0] = 1.0 - _real()
    threading.Thread(target=_jump, daemon=True).start()
""")


def test_wall_clock_jumps_do_not_mute_restart_or_fault_rigd(stack_factory, tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(JUMPER)
    env = {"PYTHONPATH": f"{site}{os.pathsep}{ROOT / 'src'}"}
    s = stack_factory(rigd_env=env)
    s.rigd.wait("ready", 15)
    ws = client(s.ws)
    try:
        got = messages(ws, 7.0)  # across both jumps
    finally:
        ws.close()
    beats = [m for m in got if m["t"] == "heartbeat"]
    assert len(beats) >= 5, "heartbeats kept their 1 Hz through the jumps"
    assert all(b["engine_alive"] and b["audio_ok"] and not b["faults"] for b in beats), beats
    assert not [e for e in s.rigd.seen if e["event"] in ("watchdog_timeout", "exit")]
    assert sounding_after_touch(s.ws)


def test_the_page_watchdog_ignores_wall_clock_jumps(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    marker = tmp_path / "restarted"
    restart = tmp_path / "restart.sh"
    restart.write_text(f"#!/bin/sh\necho x >> {marker}\n")
    restart.chmod(0o755)
    hb = run / "page-heartbeat"

    def look(now: float) -> str:
        subprocess.run([sys.executable, str(ROOT / "deploy" / "watchdog.py"), "--run", str(run),
                        "--restart", str(restart), "--now", str(now),
                        "--conf", str(ROOT / "deploy" / "station.conf")], check=True)  # fmt: skip
        return json.loads((run / "watchdog.state").read_text())["action"]

    t = 10_000.0
    hb.write_text("100")
    assert look(t) == "fresh"
    # the page keeps beating while the wall clock jumps three days ahead, then to 1970
    for i, wall in enumerate((time.time() + 3 * 86400, 1.0, time.time() - 400 * 86400)):
        hb.write_text(str(200 + i))
        os.utime(hb, (wall, wall))
        t += 30
        assert look(t) == "fresh"
    t += 50
    assert look(t) == "ok"  # 50 s unchanged: under the 60 s limit
    assert not marker.exists()
    t += 20
    assert look(t) == "restart"  # 70 s unchanged on the monotonic clock
    assert marker.read_text() == "x\n"
    assert look(t + 30) == "cooldown"
    # a reboot: monotonic time starts again; old state must not trigger anything
    assert look(5.0) == "fresh"  # state from before the reboot is discarded, not acted on
    hb.unlink()
    assert look(6.0) == "waiting"  # no page yet after boot
    assert look(150.0) == "boot-grace"  # still inside WATCHDOG_BOOT_GRACE_S (180 s)
    assert look(200.0) == "restart"  # past it, and never a heartbeat: restart the browser
    assert marker.read_text() == "x\nx\n"


def test_no_deadline_in_rigd_or_the_supervisors_uses_the_wall_clock():
    """The static half of SOK-08: deadlines are monotonic; the wall clock only names things
    (log stamps, a saved preset's name) and decides quiet hours, by design."""
    allowed = {
        "src/rigd/station.py": ["time.strftime"],
        "src/rigd/staff.py": ["datetime.now"],
        "deploy/supervise.py": ["time.strftime"],
        "deploy/watchdog.py": ["time.strftime"],
        "deploy/playable.py": ["time.strftime", "time.time() - sec"],
    }
    import re

    pat = re.compile(r"time\.time\(\)[^\n]*|datetime\.now\(\)|time\.strftime\(")
    hits = []
    for rel in ("src/rigd", "deploy"):
        for p in sorted((ROOT / rel).rglob("*.py")):
            r = str(p.relative_to(ROOT))
            for n, line in enumerate(p.read_text().splitlines(), 1):
                for m in pat.finditer(line):
                    ok = any(a.split("(")[0] in m.group(0) or a in line for a in allowed.get(r, []))
                    if not ok:
                        hits.append(f"{r}:{n}: {line.strip()}")
    assert hits == [], hits


# ------------------------------------------------------------------------- safe shutdown


def test_sigterm_to_the_supervisor_ramps_rigd_to_silence_then_exits(stack_factory, tmp_path):
    cap = tmp_path / "out.f32"
    s = stack_factory(rigd_args=["--capture", str(cap)])
    assert s.playable()["playable"]
    ws = client(s.ws)
    ws.send(json.dumps({"v": 1, "t": "keys.touch", "bits": f"{KEY12:016X}"}))
    messages(ws, 1.0)
    import numpy as np

    playing = np.fromfile(cap, dtype="<f4")[-4800:]
    assert float(np.sqrt(np.mean(playing.astype(np.float64) ** 2))) > 0.01
    t0 = time.monotonic()
    s.rigd.proc.send_signal(signal.SIGTERM)
    ev = s.rigd.wait("exit", 5)
    s.rigd.proc.wait(5)
    assert time.monotonic() - t0 < 4.0 and s.rigd.proc.returncode == 0
    assert ev["code"] == 0
    x = np.fromfile(cap, dtype="<f4")
    tail = np.abs(x[-48:])  # the last millisecond handed to the device
    assert tail.max() < 1e-3, "it closed in silence, after the mute ramp (no click)"
    cap.unlink()
    ws.close()
    assert not Path(s.rigd.pidfile).exists(), "the pidfile is removed on a clean stop"
