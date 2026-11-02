"""VS-14 acceptance: protocol v1 against a real rigd (ENG-01, ENG-02, ENG-04; ARCHITECTURE 4.6).

Every server message is validated against src/rigd/schema/protocol-v1.json by the client
(conftest.Client); each test also asserts none was invalid.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections import Counter

import pytest
from conftest import ROOT, Client, rms, sounding

from rigd import schema

KEY12 = 1 << 12  # key 12 plays note 60 (key 0 is note 48: rig.s BASENOTE)


def test_connect_sends_hello_patch_heartbeat_state_and_all_validate(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.pump(1.05)
    kinds = Counter(m["t"] for m in c.seen)
    assert [m["t"] for m in c.seen[:4]] == ["hello", "settings", "patch", "heartbeat"]
    assert kinds["state"] >= 55, kinds  # 60 Hz
    assert 25 <= kinds["scope"] <= 35, kinds  # 30 Hz
    assert 1 <= kinds["heartbeat"] <= 3, kinds  # 1 Hz, plus one at connect
    assert not c.invalid, c.invalid
    hello = c.last("hello")
    assert "profile test" in hello["engine_build"]  # VS-27: hello reports the profile
    assert [s["id"] for s in hello["capabilities"]["speeds"]] == [
        "run", "div30", "div300", "div3000", "crawl", "step"
    ]  # fmt: skip
    image = json.loads((ROOT / "build" / "program" / "rig.img.json").read_text())
    assert hello["image_sha256"] == image["sha256"]
    assert hello["disasm"]["0080"].startswith("LHI")  # SIMH fprint_sym, from the engine


def test_lamps_are_duty_fractions_at_60_hz(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    states = [m for m in c.pump(1.0) if m["t"] == "state"]
    assert len(states) >= 55  # lamp fractions at 60 Hz (>= 30 Hz required, PANEL-1)
    running = [s for s in states if not s["lamps"]["exact"]]
    assert running, "a running machine reports sampled fractions"
    for s in running:
        assert all(0.0 <= x <= 1.0 for x in s["lamps"]["addr"] + s["lamps"]["data"])
    # the scan loop runs, measured from the program's own KEYS reads
    assert states[-1]["scan_hz"] > 1000
    assert states[-1]["pc_hist"], "the heat band has samples"


def test_touch_key_reaches_the_program_and_sounds(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.pump(0.3)
    c.touch(KEY12)
    st = c.until(lambda m: m["t"] == "state" and sounding(m))
    assert st["keys_seen"][1] == 0x08  # key 12: row 1, bit 7 - 4 (ARCHITECTURE 5.1)
    assert 60 in st["watch"]["voices"]
    c.pump(0.4)
    c.touch(0)
    st = c.until(lambda m: m["t"] == "state" and not sounding(m))
    assert all(v is None for v in st["watch"]["voices"])
    c.pump(0.3)
    assert rms(rigd_proc.audio()) > 0.01  # the engine made the sound (see test_audio for pitch)
    assert not c.invalid


def test_keys_beyond_the_keyboard_are_not_offered_to_the_program(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.touch(((1 << 64) - 1) ^ ((1 << 37) - 1))  # keys 37..63 only (PRG-09)
    c.pump(0.4)
    st = c.last("state")
    assert st["keys_raw"][4] == 0 and st["keys_raw"][5:] == [0, 0, 0] and not sounding(st)


@pytest.mark.parametrize("pos", ["run", "div30", "div300", "div3000", "crawl", "step"])
def test_every_speed_is_acked_and_reported(rigd_proc, client_factory, pos):
    c = client_factory(rigd_proc.url)
    assert c.command({"t": "machine.speed", "position": pos})["t"] == "ack"
    st = c.until(lambda m: m["t"] == "state" and m["speed"] == pos)
    if pos in ("crawl", "step"):
        assert st["lamps"]["exact"] is True


def test_step_executes_one_instruction_per_command(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    assert c.command({"t": "machine.step"}) == {"v": 1, "t": "nack", "id": 1, "code": "busy"}
    assert c.command({"t": "machine.speed", "position": "step"})["t"] == "ack"
    c.pump(0.2)
    pcs = []
    for _ in range(5):
        before = c.last("state")["cycles"]
        assert c.command({"t": "machine.step"})["t"] == "ack"
        st = c.until(lambda m, b=before: m["t"] == "state" and m["cycles"] != b)
        pcs.append(st["pc"])
        c.pump(0.05)
        assert c.last("state")["cycles"] == st["cycles"], "nothing runs between STEPs"
    assert len(set(pcs)) >= 2


def test_home_returns_to_run_and_releases_held_keys(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.command({"t": "machine.speed", "position": "div300"})
    c.touch(KEY12)
    c.pump(0.3)
    assert c.command({"t": "machine.home"})["t"] == "ack"
    st = c.until(lambda m: m["t"] == "state" and m["speed"] == "run" and not sounding(m), 1.0)
    assert st["keys_raw"][1] == 0  # still held on the glass, released until let go (ENG-07)
    c.touch(0)
    c.pump(0.1)
    c.touch(KEY12)
    c.until(lambda m: m["t"] == "state" and sounding(m))  # a new press plays again


def test_a_key_held_past_the_limit_is_released_until_let_go(rigd_factory, client_factory, tmp_path):
    """PLAY-8 (held_key_release_s from kiosk.conf; 60 s on the station, 1.5 s here)."""
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "kiosk.conf").write_text("held_key_release_s = 1.5\n")
    r = rigd_factory("--no-midi", "--content", str(tmp_path / "content"))
    c = client_factory(r.url)
    c.refresh()  # a live page refreshes at 4 Hz: only the 60 s (here 1.5 s) rule may release
    c.touch(KEY12)
    c.until(lambda m: m["t"] == "state" and sounding(m))
    t0 = time.monotonic()
    c.until(lambda m: m["t"] == "state" and not m["keys_raw"][1] and not sounding(m), 3.0)
    assert 1.3 <= time.monotonic() - t0 <= 2.0
    c.touch(KEY12)  # the page's 4 Hz refresh of the same held key changes nothing
    c.pump(0.3)
    assert not sounding(c.last("state"))
    c.touch(0)
    c.pump(0.1)
    c.touch(KEY12)
    c.until(lambda m: m["t"] == "state" and sounding(m))  # pressed again: it plays


def test_every_nack_code_is_reachable(rigd_proc, client_factory):
    """ENG-01: bad_args, refused_gate, busy, not_staff, queue_full, unknown."""
    c = client_factory(rigd_proc.url)
    code = lambda m: c.command(m).get("code")  # noqa: E731
    assert code({"t": "machine.speed", "position": "warp"}) == "bad_args"
    assert code({"t": "passage.start", "slug": "anything"}) == "refused_gate"
    assert code({"t": "machine.step"}) == "busy"  # STEP only in the step position
    assert code({"t": "staff.mute", "on": True}) == "not_staff"  # no staff session
    assert code({"t": "memory.write", "addr": 0, "value": 0}) == "unknown"
    # queue_full: freeze the audio thread (test hook) so no period drains the ring (256)
    assert c.command({"t": "test.inject", "what": "freeze_audio"})["t"] == "ack"
    replies = []
    for i in range(300):
        c.send({"t": "machine.speed", "position": "run", "id": 1000 + i})
    c.until(lambda m: m.get("id") == 1299, 5.0)
    replies = [m["code"] for m in c.seen if m["t"] == "nack" and m.get("id", 0) >= 1000]
    assert "queue_full" in replies
    assert c.command({"t": "test.inject", "what": "thaw_audio"})["t"] == "ack"
    assert not c.invalid


def test_malformed_and_oversized_input_does_not_hurt(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    for raw in ["", "{", "[]", "null", '{"v":1}', '{"v":1,"t":"keys.touch","bits":"xyz"}',
                '{"v":2,"t":"machine.home","id":3}', b"\x00\x01binary"]:  # fmt: skip
        c.ws.send(raw)
    c.pump(0.2)
    assert c.command({"t": "machine.home"})["t"] == "ack"  # still answering
    big = Client(rigd_proc.url)
    with pytest.raises(Exception):  # noqa: B017 (the server closes it: frame over 64 KiB)
        big.ws.send("x" * (128 * 1024))
        big.pump(1.0)
        big.ws.send("x")
    assert c.command({"t": "machine.home"})["t"] == "ack"
    assert rigd_proc.proc.poll() is None


def test_closing_the_page_clears_its_touch_keys_after_250_ms(rigd_proc, client_factory):
    """VS-14 AC 2 / ENG-02: the touch source is cleared 250 ms after its socket closes."""
    watcher = client_factory(rigd_proc.url)
    page = client_factory(rigd_proc.url)
    page.touch(KEY12)
    watcher.until(lambda m: m["t"] == "state" and m["keys_raw"][1])
    page.ws.close()
    t0 = time.monotonic()
    watcher.until(lambda m: m["t"] == "state" and not m["keys_raw"][1], 2.0)
    dt = time.monotonic() - t0
    assert 0.2 <= dt <= 0.40, dt  # 250 ms plus at most a couple of 1/60 s ticks


def test_server_binds_loopback_only(rigd_proc):
    """VS-14 AC 3: dialling the LAN address is refused."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: no packet is sent for a UDP connect
            lan = s.getsockname()[0]
    except OSError:
        pytest.skip("no LAN address on this machine")
    if lan.startswith("127."):
        pytest.skip("no LAN address on this machine")
    with pytest.raises(OSError):
        socket.create_connection((lan, rigd_proc.port), timeout=1).close()
    socket.create_connection(("127.0.0.1", rigd_proc.port), timeout=1).close()


def test_rigd_refuses_a_non_loopback_host():
    out = subprocess.run(
        [sys.executable, "-m", "rigd", "--host", "0.0.0.0", "--audio", "null"],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
        capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    assert out.returncode == 2 and "loopback" in out.stderr


def test_no_memory_write_is_reachable_by_any_message():
    """ENG-04 / CODE-4: no client message carries an address or a value to write."""
    visitor = {t for t in schema.visitor_types("client") if not t.startswith("staff.")}
    assert visitor == {"keys.touch", "machine.speed", "machine.step", "machine.home",
                       "patch.connect", "patch.disconnect", "patch.load", "audio.volume",
                       "audio.mute"}  # fmt: skip
    for doc in (schema.protocol(), schema.extension()):
        for name, sch in doc["client"].items():
            fields = set(sch["properties"])
            assert not fields & {"addr", "address", "value", "word", "words", "data"}, name
    station = (ROOT / "src" / "rigd" / "station.py").read_text()
    for forbidden in ("CMD_DEPOSIT_TABLE", "CMD_SR_SET"):
        assert forbidden not in station  # no path from a message to a memory or SR write
    # the switch register is set only from a preset file's program block (bounded by sxpatch)
    wall = (ROOT / "src" / "rigd" / "patchwall.py").read_text()
    assert wall.count("CMD_SR_SET") == 1 and 'CMD_SR_SET, eflat["program"]["sr"]' in wall
