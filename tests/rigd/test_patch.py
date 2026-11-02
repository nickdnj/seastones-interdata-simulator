"""The patch wall through rigd to the engine's patch graph (PM-13, PM-14, PM-15; engine API v2:
sx_patch_load, sx_modules_json). The sound checks are on the capture of the real engine output:
pulling the cables to `out` really silences it, putting them back really sounds."""

from __future__ import annotations

import json
import sys

import numpy as np
from conftest import ROOT, rms, sounding

from rigd import wall

sys.path.insert(0, str(ROOT / "src" / "toolchain"))
import sxpatch  # noqa: E402

KEY12 = 1 << 12
RATE = 48000
FLOOR = ["stadium-drone", "two-voice-duet", "bell", "sweep", "four-voices", "computer-rhythm",
         "slow-steps", "big-steps", "arpeggio"]  # fmt: skip


def test_start_loads_the_default_preset_and_hello_lists_its_jacks(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.pump(0.3)
    patch, hello = c.last("patch"), c.last("hello")
    assert patch["preset"] == "stadium-drone"  # kiosk.conf preset_order's first
    doc = json.loads((ROOT / "content" / "presets" / "stadium-drone.patch.json").read_text())
    reg = {m["type"]: m for m in json.loads(
        (ROOT / "src/toolchain/sxpatch/modules.json").read_text())["modules"]}  # fmt: skip
    assert patch["layout"] == wall.layout_of(doc, reg)  # the wall, as wallmodel.js has it
    assert patch["cables"] == wall.cables_of(doc, patch["layout"])  # in wall jack ids
    assert patch["reaches_out"] is True
    caps = hello["capabilities"]
    assert caps["voices"] == 4 and caps["channel_map"] == "all-da-4"
    jacks = set(caps["jacks"])
    assert {"dac.0", "dac.15", "out.l", "out.r", "v1.pitch", "v4.gate", "v4.out"} <= jacks
    assert not any(j.startswith("gate.") for j in jacks)  # no gate column on the all-D/A map
    for x in patch["cables"]:
        assert x["from"] in jacks and x["to"] in jacks
    assert not c.invalid


def test_every_floor_preset_loads_and_sets_its_program(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    for slug in FLOOR:
        r = c.command({"t": "patch.load", "slug": slug})
        assert r["t"] == "ack", (slug, r)
        p = c.until(lambda m, s=slug: m["t"] == "patch" and m["preset"] == s)
        assert len(p["cables"]) <= 64
        sr = json.loads((ROOT / "content/presets" / f"{slug}.patch.json").read_text())
        _, flat = sxpatch.check(sr)
        c.until(lambda m, v=flat["program"]["sr"]: m["t"] == "state" and m["sr"] == v)
    assert not c.invalid


def test_refused_patch_commands_leave_the_patch_as_it_was(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    c.pump(0.2)
    before = c.last("patch")
    code = lambda m: c.command(m).get("code")  # noqa: E731
    assert code({"t": "patch.load", "slug": "no-such-preset"}) == "bad_args"
    assert code({"t": "patch.load", "slug": "eight-voices"}) == "bad_args"  # the latch map's
    assert code({"t": "patch.connect", "from": "nowhere.out", "to": "out.l"}) == "bad_args"
    taken = before["cables"][0]["to"]  # an input that already has its cable
    assert code({"t": "patch.connect", "from": "lfo.tri", "to": taken}) == "bad_args"
    assert code({"t": "patch.disconnect", "from": "dac.9", "to": "out.l"}) == "bad_args"
    c.pump(0.2)
    assert c.last("patch") == before


def test_pulling_the_out_cables_silences_and_putting_them_back_sounds(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    assert c.command({"t": "patch.load", "slug": "four-voices"})["t"] == "ack"
    c.touch(KEY12)
    c.until(sounding)
    c.pump(0.4)
    outs = [x for x in c.last("patch")["cables"] if x["to"].startswith("out.")]
    assert outs
    for x in outs:
        assert c.command({"t": "patch.disconnect", "from": x["from"], "to": x["to"]})["t"] == "ack"
    p = c.until(lambda m: m["t"] == "patch" and not m["reaches_out"])
    assert p["preset"] is None  # an edited patch is no preset
    c.pump(0.3)
    f0 = c.last("state")["frames"]
    c.pump(0.4)
    quiet = rigd_proc.at_frames(f0, f0 + RATE // 4)
    assert len(quiet) and np.max(np.abs(quiet)) < 1e-4, "no path to out: silence, key still held"
    assert sounding(c.last("state")), "the program still plays the voice; nothing reaches out"
    for x in outs:
        assert c.command({"t": "patch.connect", "from": x["from"], "to": x["to"]})["t"] == "ack"
    c.until(lambda m: m["t"] == "patch" and m["reaches_out"])
    c.pump(0.2)
    f1 = c.last("state")["frames"]
    c.pump(0.4)
    assert rms(rigd_proc.at_frames(f1, f1 + RATE // 4)) > 0.01, "the cables back: it sounds"
    assert not c.invalid


def test_home_restores_the_default_preset(rigd_proc, client_factory):
    c = client_factory(rigd_proc.url)
    assert c.command({"t": "patch.load", "slug": "computer-rhythm"})["t"] == "ack"
    c.until(lambda m: m["t"] == "state" and m["sr"] != 0)
    assert c.command({"t": "machine.home"})["t"] == "ack"
    c.until(lambda m: m["t"] == "patch" and m["preset"] == "stadium-drone")
    c.until(lambda m: m["t"] == "state" and m["sr"] == 0)
