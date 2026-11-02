"""RS-04 / RSC-03: analysis toolkit on generated signals only, and notebook hygiene.

Signals come from research/tools/synth.py with fixed seeds (printed in the test ids). No
file is read from any audio folder.

The pitch, step and zipper tests need only numpy. The onset and rhythm tests need
librosa and skip without it; run the whole set in the research venv:
    .venv-research/bin/python -m pytest tests/research
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from research.tools import analysis as A  # noqa: E402
from research.tools import synth  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SR = synth.SR


def steps_of(**kw):
    fl = kw.pop("frame_length", 1024)
    hop = kw.pop("hop_length", 128)
    y, truth = synth.stepped_sine(**kw)
    track = A.pitch_track(y, SR, fmin=300, fmax=1000, frame_length=fl, hop_length=hop)
    return A.detect_steps(track), truth


def test_dac_step_size_of_the_default_word():
    assert synth.dac_step_cents(12, 10.24) == pytest.approx(3.0)
    assert A.implied_dac_bits(3.0, 10.24) == pytest.approx(12.0)


def test_peak_tracker_is_sub_cent_on_a_steady_tone():
    y, _ = synth.stepped_sine(step_cents=0.0, duration=1.0, snr_db=40, seed=11)
    track = A.pitch_track(y, SR, fmin=300, fmax=1000)
    assert np.nanmedian(np.abs(track.cents)) < 0.5


# The RS-04 acceptance criterion: 3-cent steps, step size within 20%, update rate within 10%.
@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("snr_db", [None, 40.0, 30.0])
def test_recovers_3_cent_steps_and_update_rate(seed, snr_db):
    s, truth = steps_of(step_cents=3.0, update_hz=25.0, duration=4.0, snr_db=snr_db, seed=seed)
    print(f"seed={seed} snr={snr_db} step={s.step_cents:.3f} q={s.quantum_cents:.3f} "
          f"rate={s.update_hz:.3f}")  # fmt: skip
    assert abs(s.step_cents - truth["step_cents"]) <= 0.20 * truth["step_cents"]
    assert abs(s.update_hz - truth["update_hz"]) <= 0.10 * truth["update_hz"]
    assert len(s.plateau_cents) >= 0.5 * (truth["n_updates"] + 1)


def test_quantum_found_when_steps_are_multiples():
    s, truth = steps_of(codes_per_update=[1, 2, -1, 3], update_hz=50.0, duration=4.0,
                        frame_length=512, hop_length=64, seed=4)  # fmt: skip
    assert s.quantum_cents == pytest.approx(truth["step_cents"], rel=0.05)
    assert s.update_hz == pytest.approx(truth["update_hz"], rel=0.05)


def test_smooth_tone_is_not_called_stepped():
    y, _ = synth.glide(cents=600, duration=2.0, steps=None, seed=5)
    s = A.detect_steps(A.pitch_track(y, SR, fmin=200, fmax=1000))
    assert len(s.plateau_cents) < 3
    assert any("not enough to call this stepped" in n for n in s.notes)


def test_zipper_detected_and_counted():
    y, _ = synth.glide(cents=1200, duration=2.0, steps=20, seed=6)
    z = A.zipper(A.pitch_track(y, SR, fmin=200, fmax=1000))
    assert z.is_zipper
    assert abs(z.n_steps - 19) <= 2  # 20 levels, 19 jumps inside the sweep
    assert z.jump_fraction > 0.9


def test_smooth_glide_is_not_zipper():
    y, _ = synth.glide(cents=1200, duration=2.0, steps=None, seed=7)
    z = A.zipper(A.pitch_track(y, SR, fmin=200, fmax=1000))
    assert not z.is_zipper
    assert z.jump_fraction < 0.3


def test_loop_length_from_known_onsets():
    _, truth = synth.rhythm_loop(pattern_ms=(200, 100, 100, 400), repeats=5, seed=8)
    est = A.loop_length(np.array(truth["onsets_s"]))
    assert est.period_onsets == 4
    assert est.loop_s == pytest.approx(0.8, abs=1e-6)


def test_no_loop_in_irregular_onsets():
    rng = np.random.default_rng(9)
    onsets = np.cumsum(rng.uniform(0.1, 0.6, 20))
    assert A.loop_length(onsets) is None


def test_bad_pitch_method_rejected():
    with pytest.raises(ValueError, match="'peak' or 'yin'"):
        A.pitch_track(np.zeros(4096), SR, method="crepe")


# ---------------------------------------------------------------- librosa


def test_onsets_and_loop_on_a_generated_rhythm():
    pytest.importorskip("librosa")
    y, truth = synth.rhythm_loop(seed=3)
    on = A.onsets(y, SR)
    true = np.array(truth["onsets_s"])
    assert len(on) == len(true)
    assert np.max(np.abs(on - true)) < 0.010
    est = A.loop_length(on, tolerance_s=0.015)
    assert est is not None and est.period_onsets == len(truth["pattern_ms"])
    assert est.loop_s == pytest.approx(truth["loop_ms"] / 1000, rel=0.02)


def test_onsets_with_jitter_still_find_the_loop():
    pytest.importorskip("librosa")
    y, truth = synth.rhythm_loop(jitter_ms=3.0, seed=12)
    est = A.loop_length(A.onsets(y, SR), tolerance_s=0.020)
    assert est is not None
    assert est.loop_s == pytest.approx(truth["loop_ms"] / 1000, rel=0.03)


def test_yin_option_runs():
    pytest.importorskip("librosa")
    y, _ = synth.stepped_sine(duration=0.5, seed=13)
    track = A.pitch_track(y, SR, fmin=300, fmax=1000, method="yin")
    assert np.nanmedian(np.abs(track.cents)) < 30  # coarse, but on the right note


# ---------------------------------------------------------------- RSC-03 notebook hygiene

NOTEBOOKS = sorted(p for p in (REPO_ROOT / "research").rglob("*.ipynb"))
EMBEDDED = ("image/", "audio/", "data:audio", "data:image", "IPython.display.Audio")


def test_there_is_a_template():
    assert (REPO_ROOT / "research/notebook-templates/passage-analysis.ipynb") in NOTEBOOKS


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_committed_notebooks_are_stripped(path):
    nb = json.loads(path.read_text(encoding="utf-8"))
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] == "code":
            assert cell.get("outputs") == [], f"cell {i} has outputs"
            assert cell.get("execution_count") is None, f"cell {i} has an execution count"
        assert not cell.get("attachments"), f"cell {i} has attachments"
    raw = path.read_text(encoding="utf-8")
    sources = "".join("".join(c["source"]) for c in nb["cells"])
    for marker in EMBEDDED:
        assert marker not in raw.replace(sources, ""), marker


def test_template_calls_the_env_guard_first():
    nb = json.loads((REPO_ROOT / "research/notebook-templates/passage-analysis.ipynb").read_text())
    first_code = next(c for c in nb["cells"] if c["cell_type"] == "code")
    assert "env.check()" in "".join(first_code["source"])


def test_nbstripout_filter_is_named():
    attrs = (REPO_ROOT / "research" / ".gitattributes").read_text()
    assert "*.ipynb filter=nbstripout" in attrs


def test_nbstripout_strips_a_notebook_with_outputs(tmp_path):
    pytest.importorskip("nbstripout")
    nbf = pytest.importorskip("nbformat")
    nb = nbf.v4.new_notebook()
    cell = nbf.v4.new_code_cell("print(1)")
    cell.outputs = [nbf.v4.new_output("display_data", data={"image/png": "iVBORw0KGgo="})]
    cell.execution_count = 3
    nb.cells = [cell]
    f = tmp_path / "dirty.ipynb"
    nbf.write(nb, str(f))
    exe = Path(sys.executable).parent / "nbstripout"
    subprocess.run([str(exe), str(f)], check=True)
    clean = json.loads(f.read_text())
    assert clean["cells"][0]["outputs"] == []
    assert clean["cells"][0]["execution_count"] is None


def test_sp02_hook_rejects_a_notebook_with_outputs():
    hook = REPO_ROOT / "scripts" / "check-private.py"
    if not hook.exists():
        pytest.skip("UNVERIFIED: scripts/check-private.py (SP-02, lane A) is not on this branch; "
                    "re-run after the lanes merge")  # fmt: skip
    pytest.skip("SP-02's command-line interface is not known on this branch; wire this test "
                "to it after merge (see docs/qa/results/overnight-2026-10-31-research.md)")  # fmt: skip
