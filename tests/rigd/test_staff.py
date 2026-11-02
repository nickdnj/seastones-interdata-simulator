"""The staff session (KP-07 to KP-09, CT-07; ENG-06) in a real rigd, with the UI lane's staff
protocol as adopted into src/rigd/schema/protocol-v1.json."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from conftest import ROOT, rms

from rigd.staff import Staff, pin_matches

PIN = "4826"


@pytest.fixture
def staff_rigd(rigd_factory, tmp_path):
    (tmp_path / "pin").write_text(PIN + "\n")
    data = tmp_path / "data"

    def make():
        return rigd_factory("--no-midi", "--staff-pin-file", str(tmp_path / "pin"),
                            "--data", str(data), capture=True)  # fmt: skip

    return make, data


def auth(c, pin=PIN) -> tuple[dict, dict]:
    reply = c.command({"t": "staff.auth", "pin": pin})
    return reply, c.until(lambda m: m["t"] == "staff")


def test_wrong_pins_count_down_and_lock(staff_rigd, client_factory):
    make, _ = staff_rigd
    c = client_factory(make().url)
    for left in (4, 3, 2, 1):
        reply, st = auth(c, "0000")
        assert reply["code"] == "not_staff" and st["tries_left"] == left and not st["authed"]
    reply, st = auth(c, "0000")
    assert st["lockout_s"] > 0  # five wrong: 30 s
    reply, st = auth(c, PIN)  # even the right PIN, while locked
    assert reply["code"] == "not_staff" and not st["authed"]
    assert c.command({"t": "staff.mute", "on": True})["code"] == "not_staff"
    assert not c.invalid


def test_a_session_changes_and_keeps_settings(staff_rigd, client_factory):
    make, data = staff_rigd
    r = make()
    c = client_factory(r.url)
    other = client_factory(r.url)
    reply, st = auth(c)
    assert reply["t"] == "ack" and st["authed"] and st["settings"]["ceiling_max_dba"] == 78
    assert other.command({"t": "staff.mute", "on": True})["code"] == "not_staff"  # its own session
    assert c.command({"t": "staff.ceiling", "dba": 90})["t"] == "nack"  # schema: at most 85
    assert c.command({"t": "staff.ceiling", "dba": 70})["t"] == "ack"
    st = c.until(lambda m: m["t"] == "staff" and m["settings"]["ceiling_dba"] == 70)
    assert c.command({"t": "staff.idle_timeout", "s": 120})["t"] == "ack"
    other.until(lambda m: m["t"] == "settings" and m["idle_timeout_s"] == 120)  # to every page
    assert c.command({"t": "staff.mute", "on": True})["t"] == "ack"
    c.until(lambda m: m["t"] == "state" and m["muted"])
    assert c.command({"t": "staff.test_tone"})["t"] == "ack"  # muted: the mute stage holds it
    assert c.command({"t": "staff.close"})["t"] == "ack"
    assert c.command({"t": "staff.mute", "on": False})["code"] == "not_staff"
    saved = json.loads((data / "staff.conf").read_text())
    assert saved["cfg"]["ceiling_dba"] == 70 and saved["cfg"]["muted"] is True
    assert saved["settings"]["idle_timeout_s"] == 120
    assert not c.invalid and not other.invalid
    r.stop()
    r2 = make()  # settings survive a restart (ENG-06)
    c2 = client_factory(r2.url)
    st = c2.until(lambda m: m["t"] == "settings")
    assert st["idle_timeout_s"] == 120
    c2.until(lambda m: m["t"] == "state" and m["muted"])  # still muted, as staff left it


def test_save_preset_writes_a_loadable_patch(staff_rigd, client_factory):
    make, data = staff_rigd
    c = client_factory(make().url)
    assert c.command({"t": "patch.load", "slug": "bell"})["t"] == "ack"
    auth(c)
    reply = c.command({"t": "staff.save_preset"})
    assert reply["t"] == "ack"
    st = c.until(lambda m: m["t"] == "staff" and "saved" in m)
    slug = st["saved"]
    assert slug.startswith("staff-") and (data / "presets" / f"{slug}.patch.json").exists()
    assert c.command({"t": "patch.load", "slug": slug})["t"] == "ack"
    p = c.until(lambda m: m["t"] == "patch" and m["preset"] == slug)
    bell = json.loads((ROOT / "content/presets/bell.patch.json").read_text())
    assert p["cables"] and bell["slug"] == "bell"
    assert not c.invalid


def test_pin_file_may_hold_a_hash_and_the_ceiling_maps_to_dbfs(tmp_path):
    import hashlib

    spec = "sha256:" + hashlib.sha256(PIN.encode()).hexdigest()
    assert pin_matches(PIN, spec) and not pin_matches("1111", spec) and not pin_matches(PIN, None)
    s = Staff(tmp_path, spec, {"idle_timeout_s": 90}, ceiling_max_dba=78, ceiling_dba=67)
    assert s.ceiling_dbfs() == -12.0  # 11 dB under the -1 dBFS hardware maximum
    s.cfg["quiet_hours"] = {"from": "00:00", "to": "23:59", "dba": 60}
    from datetime import datetime

    assert s.ceiling_dbfs(datetime(2026, 11, 2, 12, 0)) == -19.0


RATE = 48000


def tone_hz(x: np.ndarray) -> float:
    """The frequency of a sine from its upward zero crossings."""
    up = np.flatnonzero((x[:-1] < 0) & (x[1:] >= 0))
    return (len(up) - 1) * RATE / float(up[-1] - up[0]) if len(up) > 2 else 0.0


def test_the_staff_test_tone_plays_1khz_for_3s_under_the_ceiling(rigd_factory, client_factory,
                                                                 tmp_path):  # fmt: skip
    """staff.test_tone (UX 5.11, KP-08): the engine's sine, 1 kHz at -20 dBFS through the safety
    chain, for 3 s, then silence by itself; refused outside a staff session; held by a mute."""
    (tmp_path / "pin").write_text(PIN + "\n")
    r = rigd_factory("--no-midi", "--rate", str(RATE), "--staff-pin-file", str(tmp_path / "pin"),
                     "--data", str(tmp_path / "data"), capture=True)  # fmt: skip
    c = client_factory(r.url)
    c.until(lambda m: m["t"] == "hello")
    assert c.command({"t": "staff.test_tone"})["code"] == "not_staff"
    time.sleep(0.5)
    assert rms(r.audio()[-RATE // 4 :]) < 1e-4  # nothing pressed, nothing plays
    auth(c)
    assert c.command({"t": "staff.test_tone"})["t"] == "ack"
    t0 = time.monotonic()
    time.sleep(1.2)
    x = r.audio()[-RATE // 5 :]
    level = rms(x) * np.sqrt(2.0)  # peak of the sine
    assert 0.08 < level < 0.12, level  # -20 dBFS = 0.1, well under the -12 dBFS staff ceiling
    assert abs(tone_hz(x) - 1000.0) < 5.0, tone_hz(x)
    while time.monotonic() - t0 < 3.6:
        time.sleep(0.05)
    assert rms(r.audio()[-RATE // 5 :]) < 1e-4  # stopped by itself, at most 3 s (+ a tick)
    # a staff mute holds the tone too: it is mixed in before the mute stage
    assert c.command({"t": "staff.mute", "on": True})["t"] == "ack"
    assert c.command({"t": "staff.test_tone"})["t"] == "ack"
    time.sleep(1.0)
    assert rms(r.audio()[-RATE // 5 :]) < 1e-4
    assert not c.invalid
