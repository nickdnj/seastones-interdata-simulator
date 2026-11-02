"""Round 6 (docs/qa/results/adversarial-2026-11-03.md): a frozen page (QA-ADV-07), underrun
storms (QA-ADV-06) and the visitor's volume and mute (AUDIO-3, KP-06), against a real rigd."""

from __future__ import annotations

import time

import numpy as np
from conftest import rms, sounding

KEY12 = 1 << 12
RATE = 48000


def test_a_frozen_page_releases_its_keys_then_mutes_and_recovers(rigd_factory, client_factory):
    r = rigd_factory("--no-midi", "--preset", "four-voices")
    c = client_factory(r.url)
    c.touch(KEY12)  # one level, then nothing on an open socket: a hung renderer
    c.until(sounding)
    t0 = time.monotonic()
    c.until(lambda m: m["t"] == "state" and not any(m["keys_raw"]), 3.0)
    assert time.monotonic() - t0 < 1.5, "released about 1 s after the page went quiet"
    assert "page 1 silent" in r.text()
    f = c.until(lambda m: m["t"] == "fault" and m["code"] == "ui_absent_muted", 12.0)
    assert 9.0 <= time.monotonic() - t0 <= 11.5, "the no-page mute at 10 s of silence"
    assert not f.get("cleared")
    c.until(lambda m: m["t"] == "state" and m["muted"], 2.0)
    c.touch(0)  # the page wakes: the mute ends at once
    c.until(
        lambda m: m["t"] == "fault" and m["code"] == "ui_absent_muted" and m.get("cleared"), 2.0
    )
    c.until(lambda m: m["t"] == "state" and not m["muted"], 2.0)
    assert not c.invalid


def test_a_live_page_keeps_its_key_held(rigd_factory, client_factory):
    r = rigd_factory("--no-midi")
    c = client_factory(r.url)
    c.refresh()
    c.touch(KEY12)
    c.until(sounding)
    c.pump(3.0)
    assert sounding(c.last("state")) and c.last("state")["keys_raw"][1]
    assert "silent" not in r.text()


def test_an_underrun_storm_is_counted_named_and_cleared(rigd_factory, client_factory):
    r = rigd_factory("--no-midi", "--test-hooks")
    c = client_factory(r.url)
    c.refresh()
    hb = c.until(lambda m: m["t"] == "heartbeat", 3.0)
    assert hb["underruns"] == 0  # the null device's bursty timer is not counted
    c.pump(2.0)
    assert c.last("heartbeat")["underruns"] == 0
    assert c.command({"t": "test.inject", "what": "late_callbacks"})["t"] == "ack"  # four
    f = c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_underruns", 2.0)
    assert not f.get("cleared") and "late callbacks" in f["staff_line"] + r.text()
    hb = c.until(lambda m: m["t"] == "heartbeat" and m["underruns"] >= 4, 2.0)
    assert "audio_underruns" in hb["faults"] and hb["audio_ok"]  # glitching, not stopped
    c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_underruns" and m.get("cleared"),
            13.0)  # fmt: skip
    assert c.last("heartbeat")["underruns"] >= 4  # the count stays: NFR-6 reads it
    assert not c.invalid


def test_visitor_volume_and_mute_stay_under_the_ceiling(rigd_factory, client_factory):
    r = rigd_factory("--no-midi", "--preset", "four-voices", capture=True)
    c = client_factory(r.url)
    c.refresh()
    c.touch(KEY12)
    c.until(sounding)
    c.pump(0.6)
    f0 = c.last("state")["frames"]
    c.pump(0.3)
    full = r.at_frames(f0, f0 + RATE // 4)
    assert np.max(np.abs(full)) <= 0.2512, "at 0 dB the -12 dBFS ceiling holds"
    assert c.command({"t": "audio.volume", "db": -20})["t"] == "ack"
    c.until(lambda m: m["t"] == "state" and m["volume"]["db"] == -20)
    c.pump(0.3)
    f1 = c.last("state")["frames"]
    c.pump(0.3)
    drop = 20 * np.log10(rms(full) / rms(r.at_frames(f1, f1 + RATE // 4)))
    assert 17 < drop < 23, f"-20 dB asked, {drop:.1f} dB heard"
    assert c.command({"t": "audio.volume", "db": 6})["code"] == "bad_args"  # never above
    assert c.command({"t": "audio.mute", "on": True})["t"] == "ack"
    c.until(lambda m: m["t"] == "state" and m["muted"] and m["volume"]["muted"])
    c.pump(0.2)
    f2 = c.last("state")["frames"]
    c.pump(0.3)
    quiet = r.at_frames(f2, f2 + RATE // 4)
    assert len(quiet) and np.max(np.abs(quiet)) < 1e-4, "the visible mute silences"
    assert c.command({"t": "machine.home"})["t"] == "ack"  # KP-06: idle/HOME restores both
    # the volume resets at once; the engine's own HOME mute ramp ends a period or so later,
    # which under load is a later state message
    c.until(
        lambda m: (
            m["t"] == "state" and m["volume"] == {"db": 0.0, "muted": False} and not m["muted"]
        )
    )
    assert not c.invalid
