"""The patch wall in rigd equals the UI's wallmodel.js, and wall cable edits reach the engine's
real ports, for all ten presets (PM-10, PM-12, PM-13, PM-14).

1. wallmodel.js under node over every preset in content/presets/ (layout, wall cables, jacks,
   reaches_out, the {i} arithmetic) equals rigd's Python port (src/rigd/wall.py).
2. For an untouched preset, the wall cables mapped to engine ports are exactly sxpatch's own
   expansion of the preset.
3. Every wall cable of every preset, disconnected and connected again through PatchWall, takes
   out and puts back exactly its engine cables in the graph handed to sx_patch_load.
4. A real rigd's patch message equals wallmodel.js for each preset on that rigd's map, and
   pulling every voice's GATE cable on the real engine silences it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import numpy as np
import pytest
from conftest import ROOT, rms, sounding

from rigd import wall
from rigd.patchwall import PatchWall

sys.path.insert(0, str(ROOT / "src" / "toolchain"))
import sxpatch  # noqa: E402

PRESETS = sorted((ROOT / "content" / "presets").glob("*.patch.json"))
MODULES = json.loads((ROOT / "src" / "toolchain" / "sxpatch" / "modules.json").read_text())
REG = {m["type"]: m for m in MODULES["modules"]}
WALLMODEL = ROOT / "src" / "web" / "app" / "wallmodel.js"
RATE = 48000


def slug(p) -> str:
    return p.name.removesuffix(".patch.json")


def doc(p):
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def node_walls(tmp_path_factory):
    node = shutil.which("node")
    if not node or not WALLMODEL.exists():
        pytest.skip("node or src/web/app/wallmodel.js missing (UNVERIFIED)")
    tmp = tmp_path_factory.mktemp("wall")
    probe = tmp / "probe.mjs"
    probe.write_text(
        f"import * as w from {json.dumps(WALLMODEL.as_uri())};\n"
        "import { readFileSync } from 'node:fs';\n"
        "const [reg, files] = [JSON.parse(readFileSync(process.argv[2], 'utf8')),"
        " JSON.parse(readFileSync(process.argv[3], 'utf8'))];\n"
        "const out = {};\n"
        "for (const f of files) { const d = JSON.parse(readFileSync(f, 'utf8'));"
        " const layout = w.layoutOf(d, reg); const cables = w.cablesOf(d, layout);"
        " out[f] = { layout, cables, jacks: w.jacksOf(layout), reaches: w.reachesOut(cables, layout) }; }\n"
        "out.fill = [w.fill('mix{i%2}.in{i/2+1}', 3), w.fill('dac.{i+4}', 2), w.evalIndex('(i-5)/2', 2),"
        " w.evalIndex('(i+1)*2', 3), w.evalIndex('i-5', 2)];\n"
        "console.log(JSON.stringify(out));\n"
    )
    (tmp / "reg.json").write_text(json.dumps(REG))
    (tmp / "files.json").write_text(json.dumps([str(p) for p in PRESETS]))
    r = subprocess.run([node, str(probe), str(tmp / "reg.json"), str(tmp / "files.json")],
                       capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
    return json.loads(r.stdout)


def test_the_python_port_equals_wallmodel_js_on_every_preset(node_walls):
    assert len(PRESETS) >= 10
    for p in PRESETS:
        d, ref = doc(p), node_walls[str(p)]
        layout = wall.layout_of(d, REG)
        assert layout == ref["layout"], p.name
        cables = wall.cables_of(d, layout)
        assert cables == ref["cables"], p.name
        assert wall.jacks_of(layout) == ref["jacks"], p.name
        assert wall.reaches_out(cables, layout) is ref["reaches"] is True, p.name
    assert node_walls["fill"] == [wall.fill("mix{i%2}.in{i/2+1}", 3), wall.fill("dac.{i+4}", 2),
                                  wall.eval_index("(i-5)/2", 2), wall.eval_index("(i+1)*2", 3),
                                  wall.eval_index("i-5", 2)]  # fmt: skip


def test_untouched_presets_map_to_exactly_sxpatchs_expansion():
    for p in PRESETS:
        d = doc(p)
        _, flat = sxpatch.load(p)
        layout = wall.layout_of(d, REG)
        mapped = wall.engine_cables(wall.cables_of(d, layout), d, layout["voices"]["count"])
        assert set(mapped) == {tuple(c) for c in flat["cables"]}, p.name


class FakeRig:
    """Records the graphs PatchWall hands the engine (no audio)."""

    def __init__(self):
        self.graphs: list[str] = []

    def modules_json(self):
        return MODULES

    def patch_load(self, graph):
        self.graphs.append(graph)
        return 0, ""

    def command(self, *a, **k):
        return 0


def graph_cables(graph: str) -> set[tuple[str, str]]:
    return {tuple(ln.split()[1:3]) for ln in graph.splitlines() if ln.startswith("cable ")}


@pytest.mark.parametrize("path", PRESETS, ids=slug)
def test_every_wall_cable_edit_reaches_its_engine_ports(path):
    d = doc(path)
    rig = FakeRig()
    pw = PatchWall(rig, [path.parent], d["map"])
    assert pw.load(slug(path)) == "ack"
    start = graph_cables(rig.graphs[-1])
    count = pw.layout["voices"]["count"]
    for c in list(pw.cables):
        ends = {
            (a, b) for a in wall.engine_ends(c["from"], d) for b in wall.engine_ends(c["to"], d)
        }
        assert ends and ends <= start, (slug(path), c)
        assert pw.disconnect(c["from"], c["to"]) == "ack", (slug(path), c)
        gone = graph_cables(rig.graphs[-1])
        assert not ends & gone and start - gone == ends, (slug(path), c)
        assert pw.message()["preset"] is None
        # reconnect, dragged from the input end this time: the page may drag either way
        assert pw.connect(c["to"], c["from"]) == "ack", (slug(path), c)
        assert graph_cables(rig.graphs[-1]) == start, (slug(path), c)
    # a cable to a free card or module input on every voice, through the mapping
    assert pw.connect("v1.pitch", "v2.pitch") == "bad_args"  # input to input
    assert pw.connect("dac.0", "nowhere.in") == "bad_args"
    assert pw.connect("dac.15", "v1.pitch") == "bad_args"  # its pitch input already has one
    assert len(pw.cables) == len(wall.cables_of(d, pw.layout)) and count >= 4


def test_a_staff_save_keeps_its_wall_and_loads_back(tmp_path):
    p = ROOT / "content" / "presets" / "big-steps.patch.json"
    rig = FakeRig()
    pw = PatchWall(rig, [p.parent, tmp_path], "all-da-4")
    assert pw.load("big-steps") == "ack"
    c = next(x for x in pw.cables if x["to"] == "v2.flt-cutoff")
    assert pw.disconnect(c["from"], c["to"]) == "ack"
    assert pw.connect("dac.10", "v2.flt-cutoff") == "ack"
    assert ("dac.10", "flt1.cutoff") in graph_cables(rig.graphs[-1])
    pw.save(tmp_path / "staff-x.patch.json", "staff-x")
    edited = list(pw.cables)
    assert pw.load("big-steps") == "ack" and pw.cables != edited
    assert pw.load("staff-x") == "ack" and pw.cables == edited


def test_real_rigd_patch_messages_equal_wallmodel(rigd_factory, client_factory, node_walls):
    for map_name in ("all-da-4", "latch-8"):
        r = rigd_factory("--no-midi", "--map", map_name, "--preset",
                         "four-voices" if map_name == "all-da-4" else "eight-voices")  # fmt: skip
        c = client_factory(r.url)
        for p in PRESETS:
            ref = node_walls[str(p)]
            reply = c.command({"t": "patch.load", "slug": slug(p)})
            if doc(p)["map"] != map_name:
                assert reply["code"] == "bad_args", (map_name, slug(p))
                continue
            assert reply["t"] == "ack", (map_name, slug(p))
            name = slug(p)
            m = c.until(lambda m, s=name: m["t"] == "patch" and m["preset"] == s)
            assert m["layout"] == ref["layout"] and m["cables"] == ref["cables"], slug(p)
            assert m["reaches_out"] is True
        assert not c.invalid
        r.stop()


def test_pulling_every_voice_gate_on_the_real_engine_silences_it(rigd_factory, client_factory):
    r = rigd_factory("--no-midi", "--preset", "four-voices", capture=True)
    c = client_factory(r.url)
    c.touch(1 << 12)
    c.until(sounding)
    gates = [x for x in c.last("patch")["cables"] if x["to"].endswith(".gate")]
    assert [x["to"] for x in gates] == ["v1.gate", "v2.gate", "v3.gate", "v4.gate"]
    for x in gates:
        assert c.command({"t": "patch.disconnect", "from": x["from"], "to": x["to"]})["t"] == "ack"
    c.until(lambda m: m["t"] == "patch" and not m["reaches_out"])  # PATCH-4: no voice is gated
    c.pump(0.5)
    f0 = c.last("state")["frames"]
    c.pump(0.4)
    quiet = r.at_frames(f0, f0 + RATE // 4)
    assert len(quiet) and np.max(np.abs(quiet)) < 1e-3, "no envelope opens: silent"
    for x in gates:
        assert c.command({"t": "patch.connect", "from": x["from"], "to": x["to"]})["t"] == "ack"
    c.touch(0)
    c.pump(0.1)
    c.touch(1 << 12)
    c.pump(0.3)
    f1 = c.last("state")["frames"]
    c.pump(0.3)
    assert rms(r.at_frames(f1, f1 + RATE // 5)) > 0.01
    assert not c.invalid
