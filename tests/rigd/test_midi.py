"""VS-13 AC 1, VS-18 and FLT-09 on this machine's MIDI system (CoreMIDI on the Mac, the ALSA
sequencer on Linux), through tools/host/sxkeys, a virtual keyboard rigd sees like a USB one.

* A virtual MIDI note sounds through the engine: the capture of the device buffer holds a tone
  at the pitch the program's table gives the note (VS-13 AC 1).
* Unplug with eight notes held: every gate is closed within 100 ms of emulated time of the
  host releasing the notes, and the midi_absent notice is sent; replug sounds within 3 s and
  clears it (VS-18; INPUT-3, FLT-08 software form).
* Hostile MIDI leaves no stuck note and no crash (FLT-09, a short form).
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import Keys, rms, sounding

C4 = 60  # key 12: the program plays MIDI note 60


def expected_hz(note: int) -> float:
    """MIDI note numbering (A4 = note 69 = 440 Hz), as the engine's voice tunes it: note 60 is
    261.63 Hz. The 12-bit converter's steps leave at most 1.5 cents (ARCHITECTURE 6.3)."""
    return 440.0 * 2 ** ((note - 69) / 12)


def peak_hz(x: np.ndarray, rate: int) -> float:
    w = x * np.hanning(len(x))
    spec = np.abs(np.fft.rfft(w, n=1 << 18))
    return float(np.argmax(spec) * rate / (1 << 18))


@pytest.fixture
def midi_rigd(rigd_factory):
    try:
        k = Keys()
        k.do("plug sxkeys-probe", "plug")
        k.close()
    except AssertionError as exc:
        pytest.skip(f"no MIDI system here (UNVERIFIED): {exc}")
    return rigd_factory("--test-hooks", capture=True)


def test_a_virtual_midi_note_sounds_through_the_engine(midi_rigd, client_factory, keys):
    c = client_factory(midi_rigd.url)
    assert c.command({"t": "patch.load", "slug": "four-voices"})["t"] == "ack"  # 0.25 s release
    keys.do("plug", "plug")
    c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
    c.pump(0.3)
    start = len(midi_rigd.audio())
    keys.do(f"on {C4}", "sent")
    st = c.until(lambda m: m["t"] == "state" and sounding(m), 2.0)
    assert st["keys_raw"][1] == 0x08 and C4 in st["watch"]["voices"]
    c.pump(0.5)
    keys.do(f"off {C4}", "sent")
    c.until(lambda m: m["t"] == "state" and not sounding(m), 2.0)
    c.pump(0.8)
    x = midi_rigd.audio()[start:]
    rate = 48000
    loud = np.flatnonzero(np.abs(x) > 0.01)
    assert len(loud) > rate // 4, "a quarter second or more of tone"
    tone = x[loud[0] + rate // 20 : loud[0] + rate // 20 + rate // 4]
    f = peak_hz(tone, rate)
    assert abs(1200 * np.log2(f / expected_hz(C4))) < 10, f  # cents
    assert rms(x[-rate // 10 :]) < 1e-3, "released: below -60 dBFS (the release tail, echo)"
    assert not c.invalid


def test_unplug_with_eight_notes_held_releases_them_and_replug_plays(
    midi_rigd, client_factory, keys
):
    c = client_factory(midi_rigd.url)
    keys.do("plug", "plug")
    c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
    for note in range(56, 64):  # keys 8-15: all of row 1
        keys.do(f"on {note}", "sent")
    c.until(lambda m: m["t"] == "state" and sounding(m) and m["keys_raw"][1] == 0xFF)
    c.pump(0.2)
    mark = c.mark()
    t_unplug = keys.do("unplug", "unplug")["host_ns"]
    released = c.until(lambda m: m["t"] == "state" and not any(m["keys_raw"]), 3.0)
    closed = c.until(lambda m: m["t"] == "state" and not sounding(m), 1.0)
    rate = 48000
    # emulated time from the host clearing the bitmap to the program closing every gate
    assert (closed["frames"] - released["frames"]) / rate <= 0.100
    notice = c.until(lambda m: m["t"] == "fault" and m["code"] == "midi_absent", 3.0, mark)
    assert not notice.get("cleared")
    c.until(lambda m: m["t"] == "heartbeat" and not m["midi_present"], 2.0, mark)
    del t_unplug  # CoreMIDI's own notice is ~250 ms late on a Mac (M1/S2A.md); not measured here
    # replug: sounds within 3 s, with no restart, and the notice clears
    t0 = time.monotonic()
    mark = c.mark()
    keys.do("plug", "plug")
    cleared = lambda m: m["t"] == "fault" and m["code"] == "midi_absent" and m.get("cleared")  # noqa: E731
    c.until(cleared, 3.0, mark)
    keys.do(f"on {C4}", "sent")
    c.until(lambda m: m["t"] == "state" and sounding(m), 3.0)
    assert time.monotonic() - t0 < 3.0
    keys.do(f"off {C4}", "sent")
    assert midi_rigd.proc.poll() is None
    assert not c.invalid


def test_hostile_midi_leaves_no_stuck_note(midi_rigd, client_factory, keys):
    """FLT-09 short form: floods, out-of-range notes, real-time and system bytes, a note-on
    with no note-off, then all-notes-off. No crash; nothing left sounding."""
    c = client_factory(midi_rigd.url)
    keys.do("plug", "plug")
    c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
    for i in range(2000):
        keys.do(f"on {(i * 7) % 128} {1 + i % 127}")
        keys.do(f"off {(i * 7) % 128}")
    for raw in ("raw 0xFE", "raw 0xF8", "raw 0xE0 0x00 0x40", "raw 0xF0", "raw 0x45 0x12",
                "raw 0xB0 0x40 0x7F", "raw 0xA0 0x30 0x30"):  # fmt: skip
        keys.do(raw)
    keys.do(f"on {C4 + 3}")  # never released by a note-off ...
    c.until(lambda m: m["t"] == "state" and sounding(m), 3.0)
    keys.do("cc 123 0", "sent")  # ... until all notes off
    c.until(lambda m: m["t"] == "state" and not sounding(m) and not any(m["keys_raw"]), 3.0)
    c.pump(0.3)
    assert midi_rigd.proc.poll() is None
    assert c.command({"t": "machine.home"})["t"] == "ack"


def test_a_foreign_keyboard_is_ignored_with_midi_source(midi_rigd, client_factory, keys):
    """--midi-source: a source not named for this rig (another lane's virtual keyboard on a
    shared machine) is never connected; ours is."""
    other = Keys()
    try:
        other.do("plug someone-elses-keyboard", "plug")
        c = client_factory(midi_rigd.url)
        c.pump(1.5)
        assert not c.last("heartbeat")["midi_present"]
        other.do(f"on {C4}", "sent")
        c.pump(0.5)
        assert not any(c.last("state")["keys_raw"]), "the foreign note never reaches the rig"
        keys.do("plug", "plug")
        c.until(lambda m: m["t"] == "heartbeat" and m["midi_present"], 10.0)
    finally:
        other.close()
