"""PM-06 acceptance: the seastones.patch/1 validator and compiler (CNT-05, DSP-12, DSP-22).

Plain-English problems with file and line; unknown fields are errors; parameters are clamped
with a warning; a patch with no path to `out` is legal (a note, the PATCH-4 hint); voices must
match the channel map (PRG-12). The module registry the validator uses is the engine's own
(`sx-render --modules`), checked against the build. Fuzzed: 10^4 mutated patches never crash.
"""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

from sxpatch import check, compile_graph, load, registry  # noqa: E402
from sxpatch.__main__ import main as sxpatch_main  # noqa: E402

PRESETS = ROOT / "content" / "presets"
DRONE = PRESETS / "stadium-drone.patch.json"


def problems_of(obj: dict, name: str = "x.patch.json") -> list[str]:
    text = json.dumps(obj, indent=2)
    return [str(p) for p in check(obj, text, name)[0]]


def base() -> dict:
    return json.loads(DRONE.read_text())


def test_every_shipped_patch_is_clean() -> None:
    for p in sorted(PRESETS.glob("*.patch.json")):
        problems, flat = load(p)
        assert not [x for x in problems if x.level == "error"], [str(x) for x in problems]
        assert flat["modules"]["out"][0] == "out"


def test_the_compiled_graph_is_deterministic_and_flat() -> None:
    _, a = load(DRONE)
    _, b = load(DRONE)
    ga, gb = compile_graph(a), compile_graph(b)
    assert ga == gb and ga.startswith("graph 1\n") and ga.endswith("end\n")
    assert "module osc0 vco" in ga and "module osc3 vco" in ga
    assert "cable dac.7 eg3.gate" in ga and "cable lfo.sine flt2.cutoff" in ga
    assert "$" not in ga and "*" not in ga and "{" not in ga


@pytest.mark.parametrize(
    "edit,want",
    [
        (lambda o: o.update(colour="red"), "unknown field 'colour'"),
        (lambda o: o.update(schema="x"), "'schema' must be"),
        (lambda o: o.update(map="moon"), "'map' must name a channel map"),
        (lambda o: o.update(auth="jitter"), "'auth' must be one of"),
        (lambda o: o["program"].update(routine="dance"), "routine must be one of"),
        (lambda o: o["voices"].update(count=8), "has 4 voices but the patch makes 8"),
        (lambda o: o["voices"].update(gate="gate.{i}"), "voice 1's gate is gate.0 but the map"),
        (lambda o: o["modules"].append({"id": "x", "type": "moog"}), "no module type 'moog'"),
        (lambda o: o["cables"].append(["mix0.out", "busl.in1"]), "busl.in1 already has a cable"),
        (lambda o: o["cables"].append(["dac.16", "echo.time"]), "dac.16: there are 16 dac lines"),
        (lambda o: o["cables"].append(["echo.l", "dac.3"]), "it can only be the start"),
        (lambda o: o["cables"].append(["echo.left", "echo.time"]), "a echo has no output 'left'"),
        (lambda o: o["cables"].append(["dac.9", "nope*.cutoff"]), "no module is called nope0"),
        (lambda o: o.update(slug="seastones-ish"), "may not be named after the record"),
    ],
)
def test_errors_are_plain_english_with_file_and_line(edit, want) -> None:
    o = base()
    edit(o)
    got = problems_of(o, "stadium-drone.patch.json" if "slug" not in want else "x.patch.json")
    hits = [p for p in got if want in p]
    assert hits, got
    file, line, *_ = hits[0].split(":")
    assert file.endswith(".patch.json") and int(line) >= 1


def test_a_parameter_out_of_range_is_clamped_with_a_warning() -> None:
    o = base()
    o["modules"][0]["params"]["rate"] = 99
    probs, flat = check(o, json.dumps(o, indent=2), "stadium-drone.patch.json")
    assert [p.level for p in probs] == ["warning"] and "it will be 8" in probs[0].msg
    assert flat["modules"]["lfo"][1]["rate"] == 8.0


def test_no_path_to_the_speaker_is_legal_and_said() -> None:
    o = base()
    o["cables"] = [c for c in o["cables"] if not c[1].startswith("out.")]
    probs, _ = check(o, json.dumps(o, indent=2), "stadium-drone.patch.json")
    assert [p.level for p in probs] == ["note"] and "Nothing reaches the speaker" in probs[0].msg


def test_the_program_block_becomes_the_switch_register() -> None:
    o = base()
    o["program"] = {"routine": "arpeggio", "variant": 6, "transpose": -2}
    _, flat = check(o, json.dumps(o), "stadium-drone.patch.json")
    assert flat["program"]["sr"] == 0x0E36  # transpose -2 (E), routine 3, variant 6


def test_voice_number_arithmetic() -> None:
    o = base()
    o["voices"]["out"] = "mix{i%2}.in{i/2+1}"
    _, flat = check(o, json.dumps(o), "stadium-drone.patch.json")
    assert ("amp3.out", "mix1.in2") in flat["cables"]
    o["voices"]["out"] = "mix{import os}.in1"
    probs = problems_of(o, "stadium-drone.patch.json")
    assert any("{import os}" in p for p in probs), probs


def test_cli_writes_graph_and_switch_register(tmp_path: Path) -> None:
    assert sxpatch_main([str(DRONE), "-o", str(tmp_path)]) == 0
    assert (tmp_path / "stadium-drone.graph").read_text().startswith("graph 1")
    assert (tmp_path / "stadium-drone.sr").read_text() == "0000\n"
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{ not json")
    assert sxpatch_main([str(bad)]) == 1


FUZZ = int(os.environ.get("SX_PATCH_FUZZ", "10000"))


def test_fuzzed_patches_never_crash() -> None:
    rng = random.Random(1974)
    print(f"seed 1974, {FUZZ} mutated patches")
    src = base()
    leaves = ["x", 1, -1e9, None, [], {}, "dac.99", "osc*.pitch", "{i/0}", True, 0.5, "out.l"]
    for _ in range(FUZZ):
        o = copy.deepcopy(src)
        for _ in range(rng.randint(1, 5)):
            node, key = o, None
            path = []
            while isinstance(node, (dict, list)) and node and rng.random() < 0.8:
                key = rng.choice(list(node)) if isinstance(node, dict) else rng.randrange(len(node))
                path.append((node, key))
                node = node[key]
            if path:
                parent, key = path[-1]
                parent[key] = rng.choice(leaves)
        probs, _ = check(o, json.dumps(o), "f.patch.json")
        for p in probs:
            assert p.line >= 1 and p.msg


@pytest.mark.lockstep
def test_the_registry_copy_matches_the_engine() -> None:
    """The validator's modules.json is the engine's registry as built: regenerate with
    `build/engine/sx-render --modules > src/toolchain/sxpatch/modules.json`."""
    render = ROOT / "build" / "engine" / "sx-render"
    if not render.exists():
        pytest.skip("run `make engine`")
    out = subprocess.run([str(render), "--modules"], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == json.loads(
        (ROOT / "src" / "toolchain" / "sxpatch" / "modules.json").read_text()
    )
    assert set(registry()) == {"vco", "vcf", "vca", "env", "lfo", "noise", "slew", "mixer",
                               "echo", "out", "reverb"}  # fmt: skip
