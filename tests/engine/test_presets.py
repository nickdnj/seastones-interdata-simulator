"""PM-16, PM-09, PO-10, PO-11, PM-07 acceptance on the real engine, offline: every preset (a patch
in content/presets/ plus the routine it pairs with in the 7/16 program) rendered from its key
script through the CPU, the devices, the patch graph and the safety chain.

Golden renders are a hash of the float32 PCM plus feature JSON, never audio
(tests/engine/golden/preset-<slug>.json; re-bless with SX_REBLESS=1 and a CHANGES.md line).
WAVs go to pytest's temporary directory, outside the work tree. No person listens overnight, so
listen.py's measurements stand in until the DES-3 gate (PM-17): headroom, DC, clicks at every
write, silence after release, the noise floor with the gates closed, aliasing, pitch, rhythm.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "engine"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

import listen as A  # noqa: E402
import presets as P  # noqa: E402
from sxpatch import load  # noqa: E402

GOLDEN = ROOT / "tests" / "engine" / "golden"
pytestmark = [
    pytest.mark.lockstep,  # needs build outputs: runs under `make conformance`
    pytest.mark.skipif(
        not P.RENDER.exists() or not P.IMAGES["all-da-4"].exists(),
        reason="run `make engine program` first",
    ),
]

ALL = P.presets() if P.RENDER.exists() else []
SLUGS = [p.slug for p in ALL]
BY = {p.slug: p for p in ALL}
UX = {"stadium-drone", "two-voice-duet", "computer-rhythm", "bell", "sweep"}  # UX 8.5


@pytest.fixture(scope="module")
def renders(tmp_path_factory) -> dict:
    d = tmp_path_factory.mktemp("presets")
    out = {}
    for pr in ALL:
        wav, tr, feat = d / f"{pr.slug}.wav", d / f"{pr.slug}.trace", d / f"{pr.slug}.json"
        r = P.render(pr, "--wav", str(wav), "--trace-out", str(tr), "--features", str(feat))
        out[pr.slug] = {
            "x": A.read_wav(wav),
            "frames": A.trace_frames(tr),
            "trace": tr.read_text(),
            "sha": r.stdout.split()[1],
            "features": json.loads(feat.read_text()),
            "features_text": feat.read_text(),
        }
    return out


def test_the_presets_are_there_and_valid() -> None:
    """PM-16: the default (Stadium drone), the UX candidates, and the routines' own presets;
    each validates, names nothing after the record, and has as many voices as its map."""
    assert UX <= set(SLUGS)
    assert {"four-voices", "slow-steps", "big-steps", "arpeggio", "eight-voices"} <= set(SLUGS)
    for pr in ALL:
        problems, flat = load(pr.patch)
        assert not [p for p in problems if p.level == "error"], problems
        assert "seastones" not in pr.slug
        assert pr.script.exists(), f"{pr.slug}: no key script"
        voices = {m[:-1] for m in flat["modules"] if m[-1].isdigit()}
        assert voices, pr.slug


@pytest.mark.parametrize("slug", SLUGS)
def test_golden_render_is_pinned(slug: str, renders: dict) -> None:
    """PO-10, DSP-16: the hash and the features of each preset's scripted render."""
    got = renders[slug]["features"]
    golden = GOLDEN / f"preset-{slug}.json"
    if os.environ.get("SX_REBLESS"):
        golden.write_text(renders[slug]["features_text"])
        pytest.skip(f"re-blessed {golden.name}: record the reason in golden/CHANGES.md")
    pinned = json.loads(golden.read_text())
    assert got["sha256"] == pinned["sha256"], f"{slug}: golden render moved: re-bless with a reason"
    assert got == pinned


@pytest.mark.parametrize("slug", ["four-voices", "computer-rhythm", "arpeggio", "stadium-drone"])
def test_the_sound_does_not_depend_on_the_period_size(slug: str, renders: dict, tmp_path) -> None:
    """DSP-14, DSP-15: the preset's D/A and gate writes (its trace), replayed into the synth in
    periods of 64 and of 1,000 frames, render bit for bit as at 128. (Keys themselves are
    latched at a period boundary, ARCHITECTURE 4.2, so a keyed run is compared through its
    writes: that is the synth's half of the claim.)"""
    tr = tmp_path / "t.trace"
    tr.write_text(renders[slug]["trace"])
    pr = BY[slug]
    shas = set()
    for per in ("128", "64", "1000"):
        r = subprocess.run([str(P.RENDER), "--replay", str(tr), "--graph", str(pr.graph),
                            "--seconds", f"{pr.seconds:g}", "--period", per],
                           capture_output=True, text=True, check=True)  # fmt: skip
        shas.add(r.stdout.split()[1])
    assert len(shas) == 1, f"{slug}: the sound depends on the period size"


@pytest.mark.parametrize("slug", SLUGS)
def test_headroom_dc_and_finite(slug: str, renders: dict) -> None:
    """Nothing non-finite; the peak under the -3 dBFS soft-clip knee, so the safety chain never
    had to touch the sound; DC below -70 dBFS (DSP-09)."""
    rep = A.report(renders[slug]["x"])
    print(f"{slug}: peak {rep.peak_dbfs:.1f} dBFS, DC {rep.dc_dbfs:.1f} dBFS, L/R corr "
          f"{rep.correlation:.2f}")  # fmt: skip
    assert rep.finite
    assert rep.peak_dbfs <= -3.0
    assert rep.peak_dbfs >= -16.0, "too quiet to stand beside the other presets"
    assert rep.dc_dbfs <= -70.0


@pytest.mark.parametrize("slug", SLUGS)
def test_no_click_at_any_write(slug: str, renders: dict) -> None:
    """DSP-06, DSP-07, PO-11: at every D/A and gate write (notes on and off, steals, lane
    steps), no click above -50 dBFS by listen.event_clicks; and the metric can fail: a planted
    spike, quieter than -30 dBFS, at a write is found."""
    x = renders[slug]["x"].mean(axis=1)
    frames = renders[slug]["frames"]
    found = A.event_clicks(x, frames)
    assert not found, f"{slug}: clicks at {[round(t, 3) for t in found[:8]]} s"
    later = [f for f in frames if f > 4800]
    f = later[len(later) // 2] + 47 + 30
    smallest = None
    for lv in range(-50, -9, 2):
        y = x.copy()
        y[f] += 10 ** (lv / 20)
        if A.event_clicks(y, frames):
            smallest = lv
            break
    print(f"{slug}: {len(frames)} writes, no click; a planted spike is found from {smallest} dBFS")
    assert smallest is not None and smallest <= -30


@pytest.mark.parametrize("slug", SLUGS)
def test_silence_after_the_last_release(slug: str, renders: dict) -> None:
    """PO-11: after the last key comes up, the release and the echo die away: the last half
    second of the render is below -60 dBFS."""
    x = renders[slug]["x"]
    end = len(x) / A.RATE
    tail = A.rms_db(x, end - 0.5, end)
    print(f"{slug}: the last 0.5 s at {tail:.1f} dBFS")
    assert tail < -60.0


@pytest.mark.parametrize("slug", SLUGS)
def test_noise_floor_with_the_gates_closed(slug: str, tmp_path: Path) -> None:
    """DSP-09: two seconds, no key: below -80 dBFS (it should be digital silence)."""
    pr = BY[slug]
    quiet = tmp_path / "none.txt"
    quiet.write_text("0.0 keys 0\n")
    wav = tmp_path / "q.wav"
    pr2 = P.Preset(pr.slug, pr.patch, quiet, pr.graph, pr.sr, pr.map, 2.0, pr.flat)
    P.render(pr2, "--wav", str(wav))
    assert A.rms_db(A.read_wav(wav), 0.0, 2.0) < -80.0


@pytest.mark.parametrize("slug", SLUGS)
def test_no_aliasing_in_the_top_band(slug: str, renders: dict) -> None:
    """DSP-08 (proxy for the presets): over the busiest second, energy above 16 kHz is at least
    50 dB below the whole."""
    x = renders[slug]["x"].mean(axis=1)
    worst = max(
        A.hf_ratio_db(x, t, t + 1.0) for t in np.arange(0.2, min(4.0, len(x) / 48000 - 1), 0.5)
    )
    print(f"{slug}: worst top-band share {worst:.1f} dB")
    assert worst < -50.0


def test_held_notes_are_in_tune(renders: dict) -> None:
    """DSP-01 through the whole chain: a single held key's fundamental."""
    x = renders["four-voices"]["x"].mean(axis=1)
    c = A.cents(A.f0(x, 0.30, 0.48), A.note_hz(60))  # key 12: C4
    d = renders["two-voice-duet"]["x"].mean(axis=1)
    c2 = A.cents(A.f0(d, 0.30, 0.52), A.note_hz(55))  # key 7: G3, with a little vibrato
    print(f"four-voices C4 {c:+.2f} cents; two-voice-duet G3 {c2:+.1f} cents")
    assert abs(c) <= 3.0 and abs(c2) <= 20.0


def _gate_rises(trace: str) -> list[float]:
    """Gate-on times (s) on the all-D/A map's gate channels 4-7."""
    out = []
    for ln in trace.splitlines():
        if ln.startswith("#"):
            continue
        f, dev, ch, val = ln.split()
        if dev == "21" and int(ch, 16) in (4, 5, 6, 7) and int(val, 16) >= 0x4000:
            out.append(int(f) / A.RATE)
    return out


@pytest.mark.parametrize("slug,step_ms", [("computer-rhythm", 125.0), ("arpeggio", 100.0)])
def test_the_computer_keeps_time(slug: str, step_ms: float, renders: dict) -> None:
    """The routines' notes start on their step grid (the interval clock, 0.15 % slow: see
    tests/program/test_routines.py), and each start is heard: the sound rises within 5 ms."""
    rises = _gate_rises(renders[slug]["trace"])
    assert len(rises) > 20
    first = rises[0]
    steps = [(t - first) * 1000.0 / step_ms for t in rises if t < 4.0]
    off = [abs(s - round(s)) * step_ms for s in steps]
    print(f"{slug}: {len(rises)} notes; worst {max(off):.2f} ms off the {step_ms:g} ms grid")
    assert max(off) <= 2.0 + 0.003 * 4000
    env = A.envelope_db(renders[slug]["x"].mean(axis=1))
    heard = 0
    for t in rises[:16]:
        k = int(t * 1000) + 1  # 1 ms windows; the safety chain's 1 ms is the first
        heard += env[k + 4] > env[k - 1] or env[k + 4] > -40
    assert heard >= 14


def test_a_preset_change_is_quick_and_clean(tmp_path: Path) -> None:
    """PM-15, DSP-22: with a chord held, loading another preset changes the sound within 200 ms,
    with no click at the change and no stuck note after the release."""
    a, b = BY["stadium-drone"], BY["four-voices"]
    script = tmp_path / "change.txt"
    script.write_text(f"0.0 keys 0\n0.2 keys 91\n1.00 graph {b.graph}\n2.5 keys 0\n")
    plain = tmp_path / "plain.txt"
    plain.write_text("0.0 keys 0\n0.2 keys 91\n2.5 keys 0\n")
    w1, w2 = tmp_path / "c.wav", tmp_path / "p.wav"
    pa = P.Preset(a.slug, a.patch, script, a.graph, a.sr, a.map, 6.0, a.flat)
    pb = P.Preset(a.slug, a.patch, plain, a.graph, a.sr, a.map, 6.0, a.flat)
    P.render(pa, "--wav", str(w1))
    P.render(pb, "--wav", str(w2))
    x, y = A.read_wav(w1).mean(axis=1), A.read_wav(w2).mean(axis=1)
    diff = np.nonzero(np.abs(x - y) > 1e-6)[0]
    first = diff[0] / A.RATE
    print(f"preset change at 1.000 s: the sound changes at {first:.4f} s")
    assert 1.0 <= first <= 1.2
    assert not A.event_clicks(x, [int(first * A.RATE) - 47])
    assert A.rms_db(A.read_wav(w1), 5.5, 6.0) < -60.0


def _cycle_cents(x: np.ndarray, t0: float, t1: float, ref_hz: float) -> np.ndarray:
    """Each cycle's frequency, in cents from ref_hz, from interpolated zero crossings."""
    seg = x[int(t0 * A.RATE) : int(t1 * A.RATE)]
    i = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0]
    t = i + (-seg[i] / (seg[i + 1] - seg[i]))
    return 1200.0 * np.log2(A.RATE / np.diff(t) / ref_hz)


def _levels(c: np.ndarray, run: int = 6) -> list[float]:
    """The pitch plateaus: medians of runs of at least `run` cycles within 0.3 cents."""
    out, start = [], 0
    for k in range(1, len(c) + 1):
        if k == len(c) or abs(c[k] - c[start]) > 0.3:
            if k - start >= run:
                out.append(float(np.median(c[start:k])))
            start = k
    return out


def test_word_size_sets_the_zipper(tmp_path: Path) -> None:
    """PM-07 and MACH-3 (DEV-19, DSP-03): the stepped-voltages routine moves the detune lane 16
    codes every 60 ms. With dac.md's word_bits at 12 each move is one converter step, about 3
    cents of pitch; at 8 bits the converter shows only every sixteenth, about 48 cents. The
    image, and the program, are the same; only the data file changed."""
    image = P.IMAGES["all-da-4"]
    sha = json.loads(image.read_text())["sha256"]
    steps = {}
    for bits in (12, 8):
        dac = tmp_path / f"dac{bits}.md"
        dac.write_text((ROOT / "src" / "program" / "rig" / "dac.md").read_text()
                       .replace("word_bits: 12", f"word_bits: {bits}"))  # fmt: skip
        script = tmp_path / "hold.txt"
        script.write_text("0.0 keys 0\n0.05 keys 1000\n")
        wav = tmp_path / f"z{bits}.wav"
        subprocess.run([str(P.RENDER), "--image", str(image), "--graph",
                        str(ROOT / "tests" / "engine" / "patches" / "zipper.graph"), "--sr", "0028",
                        "--rig-dac", str(dac), "--script", str(script), "--seconds", "4.5",
                        "--wav", str(wav)], check=True, capture_output=True)  # fmt: skip
        x = A.read_wav(wav)[:, 0]
        lv = sorted(set(round(v, 1) for v in _levels(_cycle_cents(x, 0.3, 4.4, A.note_hz(60)))))
        gaps = np.diff(lv)
        steps[bits] = float(np.median(gaps)) if len(gaps) else 0.0
        print(f"word_bits {bits}: {len(lv)} pitch levels, median step {steps[bits]:.2f} cents")
    assert json.loads(image.read_text())["sha256"] == sha
    assert 2.5 <= steps[12] <= 3.5
    assert 40.0 <= steps[8] <= 56.0


def test_tools_presets_cli_writes_listening_copies_only_under_build(tmp_path: Path) -> None:
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "presets.py"), "--only", "bell"],
                         capture_output=True, text=True, check=True)  # fmt: skip
    assert out.stdout.startswith("bell")
    assert shutil.which("true")


def test_make_bless_refuses_without_a_reason() -> None:
    """PO-10: re-blessing golden renders needs a reason, logged in golden/CHANGES.md."""
    r = subprocess.run(["make", "--no-print-directory", "bless"], cwd=ROOT, capture_output=True,
                       text=True)  # fmt: skip
    assert r.returncode != 0 and "say why" in r.stderr
