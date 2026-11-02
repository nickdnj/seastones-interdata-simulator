"""The audio device going wrong (FLT-06, KIOSK-5; ARCHITECTURE 8.1): rigd started on a device
that is not there, and a device that disappears while playing. Either way: no sound from
anywhere else, the fault named (`audio_device_missing`), rigd still up and serving the page,
the device retried every 2 s, and playing again by itself when the device is back."""

from __future__ import annotations

import time

import numpy as np
from conftest import rms, sounding

RATE = 48000


def test_starting_on_a_device_that_is_not_there(rigd_factory, client_factory):
    r = rigd_factory("--no-midi", "--audio", "auto", "--device", "no-such-device-sx-test")
    c = client_factory(r.url)
    f = c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_device_missing", 3.0)
    assert not f.get("cleared")
    hb = c.until(lambda m: m["t"] == "heartbeat" and not m["audio_ok"], 3.0)
    assert hb["stages"]["output"] is False and "audio_device_missing" in hb["faults"]
    assert hb["engine_alive"] is True  # the computer is fine; the sound is the problem
    assert c.command({"t": "machine.home"})["t"] == "ack"  # rigd still answers
    time.sleep(4.5)  # two retries
    assert r.proc.poll() is None
    assert r.text().count("would not open") >= 1
    assert "audio_device_missing" in c.until(lambda m: m["t"] == "heartbeat")["faults"]
    assert not c.invalid


def test_a_device_unplugged_while_playing_comes_back_by_itself(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.refresh()  # the page keeps the key held through the unplug
    c.touch(1 << 12)
    c.until(sounding)
    c.pump(0.3)
    t0 = time.monotonic()
    assert c.command({"t": "test.inject", "what": "unplug_audio"})["t"] == "ack"
    c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_device_missing", 2.0)
    c.until(lambda m: m["t"] == "heartbeat" and not m["audio_ok"], 3.0)
    back = c.until(lambda m: m["t"] == "fault" and m["code"] == "audio_device_missing"
                   and m.get("cleared"), 6.0)  # fmt: skip
    assert time.monotonic() - t0 < 4.0, "retried within 2 s and reopened"
    assert back
    c.until(lambda m: m["t"] == "heartbeat" and m["audio_ok"], 3.0)
    c.pump(0.5)  # the key is still held: the reopened device plays it
    st = c.last("state")
    assert sounding(st)
    time.sleep(0.1)
    segs = rigd_proc.segments()
    assert len(segs) == 2, "the capture has a second segment from the reopened device"
    x = rigd_proc.at_frames(st["frames"] - RATE // 4, st["frames"])
    assert rms(x) > 0.01
    # while the device was gone nothing was rendered: the engine's clock stood still
    assert segs[1][1] - segs[0][1] == segs[1][0] - segs[0][0] or segs[1][1] >= segs[1][0]
    assert np.isfinite(x).all()
    assert rigd_proc.proc.poll() is None
    assert not c.invalid
