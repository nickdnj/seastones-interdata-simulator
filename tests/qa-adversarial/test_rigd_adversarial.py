"""rigd under hostile conditions (QA-ADV-03, QA-ADV-06, QA-ADV-07)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rigd import faults as F  # noqa: E402
from rigd.staff import Staff  # noqa: E402

SETTINGS = {"idle_timeout_s": 90, "reduced_motion": False, "review_mode": False,
            "attract_sound": False}  # fmt: skip
KEY12 = 1 << 12

DAMAGED = [
    {"cfg": {"ceiling_dba": "loud"}},
    {"cfg": {"ceiling_dba": None}},
    {"cfg": {"quiet_hours": 5}},
    {"cfg": {"quiet_hours": {"from": "22:00"}}},
    {"cfg": {"ceiling_dba": -500}},
    [],
    {"settings": {"idle_timeout_s": 1}},
    {"settings": {"idle_timeout_s": True}},
]


# QA-ADV-03 (fixed in this branch, staff.py): a staff.conf with a value of the wrong type
# raised in Staff.__init__ (ValueError, TypeError, KeyError, AttributeError), so rigd could not
# start: under systemd, a restart loop and a dead station. And a saved idle_timeout_s of 1 (or
# true) was accepted although the protocol's floor is 30 s: the page reset every second.
@pytest.mark.parametrize("saved", DAMAGED, ids=[json.dumps(d) for d in DAMAGED])
def test_qa_adv_03_damaged_staff_conf_keeps_defaults(tmp_path, saved):
    (tmp_path / "staff.conf").write_text(json.dumps(saved))
    s = Staff(tmp_path, "2468", SETTINGS)
    assert s.ceiling_dbfs() == -12.0
    assert s.settings["idle_timeout_s"] == 90
    assert s.in_quiet_hours() is False


def test_qa_adv_03_rigd_starts_on_a_damaged_staff_conf(rigd_factory, client_factory, tmp_path):
    data = tmp_path / "damaged"
    data.mkdir()
    (data / "staff.conf").write_text(json.dumps({"cfg": {"quiet_hours": 5, "ceiling_dba": "x"}}))
    r = rigd_factory("--no-midi", "--data", str(data))
    c = client_factory(r.url)
    assert c.until(lambda m: m["t"] == "hello", 5.0)
    assert c.until(lambda m: m["t"] == "settings")["idle_timeout_s"] == 90


# QA-ADV-07 (fixed, host lane round 6, station.py): a page that freezes with a key down keeps
# its socket open and stops its 4 Hz level refresh. rigd now stamps every message: a page
# silent for over 1 s has released its keys, and one silent for 10 s counts as gone for the
# no-page mute (NFR-4, ENG-02). The browser-side watchdog (KIOSK-3) is the kiosk lane's.
def test_qa_adv_07_a_frozen_page_does_not_hold_a_note(rigd_factory, client_factory):
    r = rigd_factory("--no-midi")
    c = client_factory(r.url)
    c.until(lambda m: m["t"] == "state")
    c.touch(KEY12)  # one level, then silence on an open socket, as a hung page sends
    c.until(lambda m: m["t"] == "state" and any(v is not None for v in m["watch"]["voices"]))
    t0 = time.monotonic()
    while time.monotonic() - t0 < 11.0:
        c.pump(0.5)
    st = c.last("state")
    assert st["muted"] or all(v is None for v in st["watch"]["voices"]), (
        f"still sounding 11 s after the page stopped: voices {st['watch']['voices']}"
    )


# QA-ADV-06 (fixed, host lane round 6): KIOSK-5 says an underrun storm is a named fault shown
# with its cause, and NFR-6 counts underruns. rigd now reads the host's late-callback count:
# heartbeat.underruns, and a storm (3 within 5 s) raises audio_underruns.
def test_qa_adv_06_underruns_are_surfaced(rigd_factory, client_factory):
    r = rigd_factory("--no-midi")
    c = client_factory(r.url)
    hb = c.until(lambda m: m["t"] == "heartbeat", 3.0)
    named = any("underrun" in code or "xrun" in code for code in F.CODES)
    counted = any(k in hb for k in ("underruns", "xruns", "late_callbacks"))
    assert named and counted
