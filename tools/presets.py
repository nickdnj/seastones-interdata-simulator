#!/usr/bin/env python3
"""Render the presets through the real engine: golden renders, analysis, and listening copies.

    python3 tools/presets.py                 render every preset with its script; print levels
    python3 tools/presets.py --listen        also write build/listen/<slug>.wav (git-ignored)
    python3 tools/presets.py --only bell     one preset

A preset is a patch file (content/presets/<slug>.patch.json, seastones.patch/1) plus the routine
it pairs with in the 7/16 program (its `program` block, which becomes the switch register). Each
has a key script, tests/engine/scripts/presets/<slug>.txt, written to show it off. Nothing here
reads a recording: the only sound is the engine's, from the program's own D/A writes.

Needs `make engine program`. WAVs go only under build/ (sx-render refuses anywhere else in the
tree, VS-12); the repo keeps hashes and feature JSON, never audio (QA-STRATEGY 13.2).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "toolchain"))

from sxpatch import compile_file  # noqa: E402

PRESETS = ROOT / "content" / "presets"
SCRIPTS = ROOT / "tests" / "engine" / "scripts" / "presets"
RENDER = ROOT / "build" / "engine" / "sx-render"
IMAGES = {"all-da-4": ROOT / "build" / "program" / "rig.img.json",
          "latch-8": ROOT / "build" / "program" / "rig8.img.json"}  # fmt: skip
GRAPHS = ROOT / "build" / "presets"
LISTEN = ROOT / "build" / "listen"


@dataclass
class Preset:
    slug: str
    patch: Path
    script: Path
    graph: Path
    sr: int
    map: str
    seconds: float
    flat: dict


def seconds_of(script: Path) -> float:
    """The script's length: its last event plus a tail line `# seconds N`."""
    for ln in script.read_text().splitlines():
        if ln.startswith("# seconds "):
            return float(ln.split()[2])
    return 1.0 + max(float(ln.split()[0]) for ln in script.read_text().splitlines()
                     if ln and not ln.startswith("#"))  # fmt: skip


def presets() -> list[Preset]:
    out = []
    GRAPHS.mkdir(parents=True, exist_ok=True)
    for p in sorted(PRESETS.glob("*.patch.json")):
        slug = p.name.removesuffix(".patch.json")
        graph, flat = compile_file(p)
        g = GRAPHS / f"{slug}.graph"
        g.write_text(graph)
        script = SCRIPTS / f"{slug}.txt"
        mapname = __import__("json").loads(p.read_text())["map"]
        out.append(Preset(slug, p, script, g, flat["program"]["sr"], mapname, seconds_of(script),
                          flat))  # fmt: skip
    return out


def render(pr: Preset, *extra: str) -> subprocess.CompletedProcess:
    args = [str(RENDER), "--image", str(IMAGES[pr.map]), "--graph", str(pr.graph),
            "--sr", f"{pr.sr:04X}", "--script", str(pr.script), "--seconds", f"{pr.seconds:g}",
            *extra]  # fmt: skip
    r = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"sx-render {pr.slug}: {r.stderr.strip()}")
    return r


def extras() -> list[tuple[str, Preset, list[str], str]]:
    """Listening comparisons beyond the presets: the selectable zipper (ARCHITECTURE 6.4)."""
    LISTEN.mkdir(parents=True, exist_ok=True)
    dac8 = LISTEN / "dac-8bit.md"
    dac8.write_text((ROOT / "src" / "program" / "rig" / "dac.md").read_text()
                    .replace("word_bits: 12", "word_bits: 8"))  # fmt: skip
    by = {p.slug: p for p in presets()}
    s = by["slow-steps"]
    return [
        ("slow-steps-8bit", s, ["--rig-dac", str(dac8)],
         "Slow steps through an 8-bit converter: the same program, coarser steps"),
        ("slow-steps-analog", s, ["--auth", "1"],
         "Slow steps in analog mode: each step rounded by the converter's 2 kHz output stage"),
        ("big-steps-8bit", by["big-steps"], ["--rig-dac", str(dac8)],
         "Big steps through an 8-bit converter"),
    ]  # fmt: skip


def score_demo() -> None:
    """The original demo score (research/scores/original-tide-clock.score) through the score
    player (switches 0-3 at 1), on the Slow steps patch, whose filter follows D/A 8 and whose
    tuning follows D/A 13: build/listen/score-tide-clock.wav."""
    from sxscore.compile import compile_file as compile_score
    from sxscore.compile import emit_table

    src = ROOT / "research" / "scores" / "original-tide-clock.score"
    tbl = LISTEN / "tide-clock.tbl"
    tbl.write_text(emit_table(compile_score(src), "Tide clock"))
    script = LISTEN / "tide-clock.txt"
    script.write_text(f"0.0 keys 0\n0.0 score {tbl}\n")
    graph = GRAPHS / "slow-steps.graph"
    subprocess.run([str(RENDER), "--image", str(IMAGES["all-da-4"]), "--graph", str(graph),
                    "--sr", "1000", "--script", str(script), "--seconds", "34",
                    "--wav", str(LISTEN / "score-tide-clock.wav")], check=True,
                   capture_output=True)  # fmt: skip
    print("score-tide-clock  the original demo score, twice round its 16 s loop")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", action="store_true", help="write build/listen/<slug>.wav")
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    if not RENDER.exists():
        print("tools/presets.py: run `make engine program` first", file=sys.stderr)
        return 2
    LISTEN.mkdir(parents=True, exist_ok=True)
    for pr in presets():
        if a.only and pr.slug != a.only:
            continue
        extra = ["--wav", str(LISTEN / f"{pr.slug}.wav")] if a.listen else []
        r = render(pr, *extra)
        print(f"{pr.slug:16} sr {pr.sr:04X}  {pr.seconds:5.1f} s  {r.stdout.split()[1][:16]}")
    if a.listen and not a.only:
        for name, pr, args, what in extras():
            r = render(pr, *args, "--wav", str(LISTEN / f"{name}.wav"))
            print(f"{name:16} {what}")
        score_demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
