"""Fail-silent and recovery in a real rigd (VS-16 rigd half, VS-17; FLT-03, FLT-04, FLT-10,
FLT-12, FLT-13; ARCHITECTURE 8).

Silence is measured on the capture of the output exactly as it is handed to the (null) device,
mapped to engine frames through rigd's capture-segment log line. The engine's own <= 8 ms is
VS-16's offline test (tests/engine/test_supervisor.c); here the bound is VS-17's 100 ms.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

import numpy as np
import pytest
from conftest import ROOT, Keys, rms, sounding

from rigd import faults as F
from rigd import schema

RATE = 48000
KEY12 = 1 << 12
SILENT = 1e-4  # -80 dBFS


def loud(x: np.ndarray) -> bool:
    return rms(x) > 0.01


def test_dsp_fault_falls_silent_and_home_recovers(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.touch(KEY12)
    c.until(lambda m: m["t"] == "state" and sounding(m))
    c.pump(0.4)
    mark = c.mark()
    for _ in range(2):  # three non-finite catches in a second: dsp_fault (VS-16)
        assert c.command({"t": "test.inject", "what": "nan"})["t"] == "ack"
        c.pump(0.02)
    f_ref = c.last("state")["frames"]  # at or before the third injection's frame
    assert c.command({"t": "test.inject", "what": "nan"})["t"] == "ack"
    t_fault = time.monotonic()
    fault = c.until(lambda m: m["t"] == "fault" and m["code"] == "dsp_fault", 2.0, mark)
    assert not fault.get("cleared")
    muted = c.until(lambda m: m["t"] == "state" and m["muted"], 1.0, mark)
    assert "dsp_fault" in muted["faults"]
    c.until(lambda m: m["t"] == "fault" and m["code"] == "dsp_fault" and m.get("cleared"))
    c.pump(0.3)
    # HOME released the held key: let go and press again, and it plays (<= 2 s from the fault)
    c.touch(0)
    c.pump(0.1)
    f_press = c.last("state")["frames"]
    time.sleep(0.05)
    quiet = rigd_proc.at_frames(f_ref + RATE // 10, f_press)
    assert len(quiet) > RATE // 4
    assert np.max(np.abs(quiet)) < SILENT, "silent from 100 ms after the fault to the next press"
    c.touch(KEY12)
    st = c.until(lambda m: m["t"] == "state" and sounding(m) and not m["muted"], 2.0)
    assert time.monotonic() - t_fault < 2.0
    c.pump(0.4)
    assert loud(rigd_proc.at_frames(st["frames"] + RATE // 4, st["frames"] + RATE // 2))
    assert "recovery 1: HOME" in rigd_proc.text()
    assert not c.invalid


@pytest.fixture
def halt_image(tmp_path):
    out = tmp_path / "halt"
    subprocess.run(
        [sys.executable, "-m", "sxasm", str(ROOT / "tests" / "rigd" / "fixtures" / "halt.s"),
         "-o", str(out), "--name", "halt"],
        check=True, env={"PYTHONPATH": str(ROOT / "src" / "toolchain")}, capture_output=True,
    )  # fmt: skip
    return out


def test_halting_program_falls_silent_within_100ms_and_restarts(
    rigd_factory, client_factory, halt_image
):
    """FLT-03: a program that halts. Silence within 100 ms; HOME reloads it; it plays again."""
    r = rigd_factory(
        "--no-midi", "--image", str(halt_image / "halt.img.json"),
        "--listing", str(halt_image / "halt.lst.json"), "--preset", "four-voices", capture=True,
    )  # fmt: skip
    c = client_factory(r.url)
    stalled = lambda m: m["t"] == "fault" and m["code"] == "program_stalled"  # noqa: E731
    mark = c.mark()
    c.until(lambda m: stalled(m) and not m.get("cleared"), 3.0)
    c.until(lambda m: stalled(m) and m.get("cleared"), 3.0, mark)
    halted = [m for m in c.seen if m["t"] == "state" and m["waiting"]]
    first_halt = halted[0]["frames"]  # within one 1/60 s tick after the LPSW
    f_press = c.last("state")["frames"]  # press at once: the reloaded program runs ~0.3 s
    # after a recovery rigd keeps the rig quiet until a key goes down (FLT-12); then the
    # reloaded program sounds its note again: playable within 2 s of the halt
    c.touch(KEY12)
    run2 = c.until(lambda m: m["t"] == "state" and sounding(m) and not m["muted"], 2.0)
    assert run2["frames"] - first_halt < 2 * RATE
    c.until(lambda m: stalled(m) and not m.get("cleared"), 3.0)  # and it halts again
    time.sleep(0.1)
    before = r.at_frames(first_halt - RATE // 5, first_halt - RATE // 20)
    after = r.at_frames(first_halt + RATE // 10, f_press)  # through the HOME, to the next key
    assert loud(before), "the test program sounds its note before it halts"
    assert len(after) and np.max(np.abs(after)) < SILENT, "silent 100 ms after the halt"
    assert loud(r.at_frames(run2["frames"] + RATE // 20, run2["frames"] + RATE // 7))
    assert "recovery 1: HOME" in r.text()
    assert not c.invalid


def test_no_page_for_10_s_mutes_and_a_page_unmutes(rigd_factory, client_factory):
    """VS-16 AC 3, FLT-04: silent at 10 s (+-0.5 s) with no page, not earlier; reconnect plays."""
    try:
        keys = Keys()
        keys.do("plug", "plug")
    except AssertionError as exc:
        pytest.skip(f"needs a MIDI system for a key held with no page (UNVERIFIED): {exc}")
    try:
        r = rigd_factory("--test-hooks", capture=True)
        c = client_factory(r.url)
        c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
        keys.do("on 60", "sent")
        c.until(lambda m: m["t"] == "state" and sounding(m))
        c.pump(0.2)
        f_close = c.last("state")["frames"]
        c.close()
        time.sleep(11.0)
        x = r.at_frames(f_close, f_close + 11 * RATE)
        win = RATE // 10
        levels = [rms(x[i : i + win]) for i in range(0, len(x) - win, win)]
        silent_at = next(i for i, v in enumerate(levels) if v < SILENT) * 0.1
        assert 9.5 <= silent_at <= 10.5, silent_at  # muted at 10 s, not earlier
        assert all(v > 0.01 for v in levels[: int(9.4 / 0.1)])  # the held key played on
        c2 = client_factory(r.url)
        st = c2.until(lambda m: m["t"] == "state" and not m["muted"], 2.0)
        c2.pump(0.5)
        assert loud(r.at_frames(st["frames"] + RATE // 4, st["frames"] + RATE // 2))
        assert "fault ui_absent_muted cleared" in r.text()
        keys.do("off 60", "sent")
    finally:
        keys.close()


def test_a_stalled_audio_thread_is_reopened_and_three_stalls_exit(rigd_proc, client_factory):
    """FLT-10: frames frozen over 150 ms is audio_stalled; the device is reopened; three
    strikes in a minute exit, for systemd to restart rigd."""
    c = client_factory(rigd_proc.url)
    c.pump(0.3)
    for strike in range(1, 4):
        mark = c.mark()
        assert c.command({"t": "test.inject", "what": "freeze_audio"})["t"] == "ack"
        if strike < 3:
            c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_stalled", 2.0, mark)
            c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_stalled"
                    and m.get("cleared"), 3.0, mark)  # fmt: skip
            f = c.last("state")["frames"]
            c.until(lambda m, f=f: m["t"] == "state" and m["frames"] > f + RATE // 10, 2.0)
    assert rigd_proc.proc.wait(5) == 3
    assert "audio stalled three times in a minute" in rigd_proc.text()


@pytest.mark.parametrize(
    "case, code",
    [("missing", "image_missing"), ("hash", "image_hash_mismatch"),
     ("lib", "engine_load_failed"), ("config", "config_invalid")],
)  # fmt: skip
def test_image_config_and_load_faults_are_named_and_silent(
    rigd_factory, client_factory, tmp_path, case, code
):
    """FLT-13: each fault is reported by its code and nothing sounds."""
    args = ["--no-midi"]
    if case == "missing":
        args += ["--image", str(tmp_path / "no-such.img.json")]
    elif case == "hash":
        img = json.loads((ROOT / "build" / "program" / "rig.img.json").read_text())
        img["segments"][0]["words"][3] = "FFFF"  # one word changed, hash kept
        (tmp_path / "bad.img.json").write_text(json.dumps(img))
        args += ["--image", str(tmp_path / "bad.img.json")]
    elif case == "lib":
        args += ["--lib", str(tmp_path / "libnothing.dylib")]
    else:
        (tmp_path / "content").mkdir()
        (tmp_path / "content" / "kiosk.conf").write_text("held_key_release_s = soon\n")
        args += ["--content", str(tmp_path / "content")]
    r = rigd_factory(*args, capture=(case != "lib"))
    c = client_factory(r.url)
    c.touch(KEY12)
    c.until(lambda m: m["t"] == "fault" and m["code"] == code, 3.0)
    hb = c.until(lambda m: m["t"] == "heartbeat" and code in m["faults"], 3.0)
    c.pump(0.6)
    assert not c.invalid
    if case == "config":
        assert loud(r.audio()), "a bad tunable falls back to its default; the rig still plays"
        return
    if case == "lib":
        assert hb["engine_alive"] is False and hb["stages"]["computer"] is False
        assert not [m for m in c.seen if m["t"] == "state"]  # no engine, no invented state
        return
    assert hb["stages"]["program"] is False
    assert r.audio().size and np.max(np.abs(r.audio())) < SILENT  # a key, and silence


def test_every_fault_code_has_a_staff_line_and_matches_the_architecture():
    """VS-17 AC 3 (rigd's half: staff lines; the visitor lines are content, CT-*)."""
    arch = (ROOT / "docs" / "ARCHITECTURE.md").read_text()
    section = arch.split("### 8.2 Fault codes", 1)[1].split("###", 1)[0]
    listed = re.findall(r"`([a-z_]+)`", section.split("Each has", 1)[0])
    assert tuple(listed) + F.EXTENSION_CODES == F.CODES  # extensions: ARCHITECTURE to follow
    assert set(F.STAFF_LINES) == set(F.CODES)
    assert all(line.startswith("STAFF · ") and len(line) < 110 for line in F.STAFF_LINES.values())
    enum = schema.protocol()["definitions"]["faultCode"]["enum"]
    assert tuple(enum) == F.CODES
    faults_md = ROOT / "content" / "captions" / "faults.md"
    if faults_md.exists():  # the UI lane's content: the visitor's words for each state
        text = faults_md.read_text()
        for section in ("computer", "sound", "keyboard-lost", "starting"):
            assert f"## {section}" in text


def test_no_sound_source_outside_the_engine_in_host_or_rigd():
    """FLT-12 / VS-19 (host half): nothing in src/host or src/rigd can make a sound of its own.
    The only writer of device samples is rt.c, and it writes what sx_render produced (or
    zeros); there is no oscillator, sample playback or audio file anywhere here."""
    banned = re.compile(
        r"\b(sin|sinf|cos|cosf|tanh)\s*\(|AudioContext|\.wav\b|\.mp3\b|\.ogg\b|\.aiff?\b|"
        r"AudioServicesPlay|NSSound|aplay|afplay|math\.sin|numpy\.sin|np\.sin"
    )  # fmt: skip
    files = [p for p in (ROOT / "src" / "host").rglob("*") if p.suffix in (".c", ".h")
             and "vendor" not in p.parts] + list((ROOT / "src" / "rigd").rglob("*.py"))  # fmt: skip
    hits = [f"{p.relative_to(ROOT)}:{n}" for p in files
            for n, ln in enumerate(p.read_text().splitlines(), 1) if banned.search(ln)]  # fmt: skip
    assert not hits, hits
    rt = (ROOT / "src" / "host" / "rt" / "rt.c").read_text()
    assert "sx_render(rt->e, rt->stereo" in rt  # the device gets only the engine's samples
    assert not list((ROOT / "src" / "host").rglob("*.wav"))


def test_first_key_sounds_from_a_cold_start_with_no_page(rigd_factory):
    """AUDIO-5 (host half): the first key after start sounds, with no page and no click."""
    try:
        keys = Keys()
        keys.do("plug", "plug")
    except AssertionError as exc:
        pytest.skip(f"needs a MIDI system (UNVERIFIED): {exc}")
    try:
        r = rigd_factory("--test-hooks", capture=True)
        deadline = time.monotonic() + 5.0
        while "capture segment" not in r.text() and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(1.0)  # CoreMIDI connects new clients' sources on its own schedule
        keys.do("on 60", "sent")
        time.sleep(0.6)
        keys.do("off 60", "sent")
        time.sleep(0.2)
        x = r.audio()
        assert loud(x[-int(0.7 * RATE) :]), "the first key, with no page ever connected"
    finally:
        keys.close()
