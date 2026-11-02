"""The live patch: presets and wall cable edits, applied by sx_patch_load (PM-13, PM-14, PM-15;
ARCHITECTURE 11.3, 11.4; engine API v2).

State is the loaded preset's engine-format document (seastones.patch/1: a voice template, a
voices block, global modules and cables) plus the wall's cables in wall jack ids (wall.py, the
port of the UI's wallmodel.js). The `patch` message carries both those cables and the wall's
`layout`, so the page draws exactly what rigd holds.

Every change is applied the same way: the wall cables are mapped to engine ports
(wall.engine_cables: a voice's PITCH and GATE jacks feed the template's $pitch and $gate
inputs, OUT is its $out source, a card jack <tid>-<port> is <tid><n-1>.<port>), added to the
template's own cables inside each voice, and the whole flat patch is validated by sxpatch (one
cable per input, known jacks, the voices on the map's channels) before sx_patch_load queues it
(the engine swaps it in at the next period, 5 ms crossfade, held notes carrying over). An edit
the engine would refuse is a `nack bad_args` and the live patch stays as it was. For an
untouched preset the mapping gives exactly sxpatch's own expansion (tests/rigd/test_wall.py).

Loading a preset also sets the switch register and authenticity mode its `program` block names
(bounded by sxpatch): the only way rigd ever sets the switch register (ENG-04, PANEL-4).
A staff save is the preset document plus `wall` (the fake engine's form), in <data>/presets/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import engine as eng
from . import wall

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "toolchain"))
import sxpatch  # noqa: E402  (src/toolchain/sxpatch: validator and compiler)

AUTH = {"authentic": 0, "analog": 1, "strobed": 2}


class PatchWall:
    def __init__(self, rig, preset_dirs: list[Path], map_name: str):
        self.rig = rig
        self.dirs = [Path(d) for d in preset_dirs]
        self.map = map_name
        mj = rig.modules_json()
        self.registry = {m["type"]: m for m in mj["modules"]}
        self.base: dict | None = None  # the preset's engine-format document (without `wall`)
        self.flat: dict | None = None  # sxpatch's expansion of the base: its modules
        self.layout: dict | None = None
        self.cables: list[dict] = []  # wall jack ids
        self.kinds: dict[str, str] = {}
        self.preset: str | None = None
        self.pending: str | None = None  # a graph waiting for the last swap to finish

    # ------------------------------------------------------------ files

    def find(self, slug: str) -> Path | None:
        for d in self.dirs:
            p = d / f"{slug}.patch.json"
            if p.is_file():
                return p
        return None

    def presets(self) -> list[str]:
        out = set()
        for d in self.dirs:
            out |= {p.name.removesuffix(".patch.json") for p in d.glob("*.patch.json")}
        return sorted(out)

    # ------------------------------------------------------------ applying

    def _engine_flat(self, base: dict, flat: dict, cables: list[dict]) -> dict | None:
        """The flat engine patch for these wall cables over base's modules, validated."""
        count = (base.get("voices") or {}).get("count", 0)
        prog = flat.get("program") or {"routine": "play", "variant": 0, "transpose": 0}
        obj = {
            "schema": sxpatch.SCHEMA,
            "slug": "live",
            "map": self.map,
            "auth": flat.get("auth", "authentic"),
            "program": {k: prog[k] for k in ("routine", "variant", "transpose")},
            "modules": [{"id": m, "type": t, "params": p} for m, (t, p) in flat["modules"].items()],
            "cables": [list(c) for c in wall.engine_cables(cables, base, count)],
        }
        problems, out = sxpatch.check(obj, json.dumps(obj), "live.patch.json")
        return None if any(p.level == "error" for p in problems) else out

    def _apply(self, eflat: dict, set_program: bool) -> str:
        rc, _err = self.rig.patch_load(sxpatch.compile_graph(eflat))
        if rc == eng.SX_E_AGAIN:
            self.pending = sxpatch.compile_graph(eflat)  # the tick retries after a period
        elif rc != eng.SX_OK:
            return "bad_args"
        if set_program and eflat.get("program"):
            self.rig.command(eng.CMD_SR_SET, eflat["program"]["sr"] & 0xFFFF)
            self.rig.command(eng.CMD_AUTH_MODE, AUTH.get(eflat.get("auth", "authentic"), 0))
        return "ack"

    def retry(self) -> None:
        if self.pending is not None:
            rc, _ = self.rig.patch_load(self.pending)
            if rc != eng.SX_E_AGAIN:
                self.pending = None

    def load(self, slug: str) -> str:
        path = self.find(slug)
        if path is None:
            return "bad_args"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "bad_args"
        saved_wall = doc.pop("wall", None) if isinstance(doc, dict) else None
        problems, flat = sxpatch.check(doc, json.dumps(doc), path.name)
        if any(p.level == "error" for p in problems) or doc.get("map") != self.map:
            return "bad_args"  # broken, or for the other channel map (e.g. eight-voices)
        layout = wall.layout_of(doc, self.registry)
        cables = saved_wall if isinstance(saved_wall, list) else wall.cables_of(doc, layout)
        cables = [{"from": c["from"], "to": c["to"]} for c in cables]
        eflat = self._engine_flat(doc, flat, cables)
        if eflat is None:
            return "bad_args"
        rc = self._apply(eflat, set_program=True)
        if rc == "ack":
            self.base, self.flat, self.layout, self.cables, self.preset = (
                doc, flat, layout, cables, slug)  # fmt: skip
            self.kinds = {j["id"]: j["kind"] for j in wall.jacks_of(layout)}
        return rc

    def _edit(self, cables: list[dict]) -> str:
        eflat = self._engine_flat(self.base, self.flat, cables)
        if eflat is None:
            return "bad_args"
        rc = self._apply(eflat, set_program=False)
        if rc == "ack":
            self.cables = cables
            self.preset = None  # an edited patch is no preset
        return rc

    def connect(self, a: str, b: str) -> str:
        if self.base is None:
            return "busy"
        ka, kb = self.kinds.get(a), self.kinds.get(b)
        if ka is None or kb is None or a == b:
            return "bad_args"
        outs = ("source", "gate", "out")
        if (ka in outs) == (kb in outs):
            return "bad_args"  # output to input only; the page may drag either way
        if ka not in outs:
            a, b = b, a
        if any(c["from"] == a and c["to"] == b for c in self.cables):
            return "ack"
        return self._edit(self.cables + [{"from": a, "to": b}])

    def disconnect(self, a: str, b: str) -> str:
        if self.base is None:
            return "busy"
        keep = [c for c in self.cables if (c["from"], c["to"]) not in ((a, b), (b, a))]
        if len(keep) == len(self.cables):
            return "bad_args"
        return self._edit(keep)

    # ------------------------------------------------------------ what the page sees

    def reaches_out(self) -> bool:
        return bool(self.layout) and wall.reaches_out(self.cables, self.layout)

    def jacks(self) -> list[str]:
        return [j["id"] for j in wall.jacks_of(self.layout)] if self.layout else []

    def message(self) -> dict:
        layout = self.layout or {"map": self.map, "rail": {"gates": False},
                                 "voices": {"count": 0, "ports": []}, "modules": []}  # fmt: skip
        return {"v": 1, "t": "patch", "cables": [dict(c) for c in self.cables],
                "reaches_out": self.reaches_out(), "preset": self.preset,
                "layout": layout}  # fmt: skip

    def save(self, path: Path, slug: str) -> None:
        """The preset document plus its wall (PATCH-6), written atomically."""
        obj = {**self.base, "slug": slug, "wall": [dict(c) for c in self.cables]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=1) + "\n")
        tmp.replace(path)
