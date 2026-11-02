"""seastones.patch/1: validate a patch file and compile it to the engine's seastones.graph/1.

ARCHITECTURE 11.3 and ADR-007 (PM-06). A patch is JSON, written by the staff screen or by hand:

    {
      "schema": "seastones.patch/1",
      "slug": "stadium-drone",            the file is <slug>.patch.json
      "map": "all-da-4",                  the channel map it is for (src/program/rig/)
      "auth": "authentic",                authentic | analog | strobed (research jitter: never)
      "program": {"routine": "play", "variant": 0, "transpose": 0},
      "templates": {"voice": {"modules": [...], "cables": [...]}},
      "voices": {"template": "voice", "count": 4,
                 "pitch": "dac.{i}", "gate": "dac.{i+4}", "out": "mix.in{i+1}"},
      "modules": [{"id": "mix", "type": "mixer", "params": {"l1": 0.3}}],
      "cables": [["dac.8", "flt*.cutoff"], ["mix.out", "out.l"]]
    }

* Module types, ports and parameter ranges come from modules.json, the engine's own registry
  (`sx-render --modules`; a test checks the copy here against the build).
* The voice template's modules are made once per voice, named <id><i> (osc0, osc1 ...); its
  cables use `$pitch`, `$gate` and `$out`, which the `voices` block fills in per voice, with
  `{...}` holding whole-number arithmetic over the voice number i: `{i}`, `{i+4}`, `{i%2}`,
  `{i/2+1}` (so voices can alternate between two mixers, left and right). A global cable may name `id*.port` for that
  port on every voice.
* `out` is always there (the module that feeds the safety chain); declare it to set its level.
* One cable per input; an output may feed many. Parameters outside their range are clamped
  (a warning). Unknown fields are an error. A patch with no path from a D/A or gate line to
  `out` is legal: the screen shows the silence hint (PATCH-4), and the validator says so.
* The voices must match the channel map: as many as it has, each voice's pitch and gate on
  that voice's channels (PRG-12).
* `program` pairs the patch with what the 7/16 program plays (the switch register, rig.s):
  routine play, rhythm, steps or arpeggio; variant 0-15; transpose -8 to 7 semitones.

Every problem is plain English with the file and the line. Nothing here touches the engine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SCHEMA = "seastones.patch/1"
HERE = Path(__file__).resolve().parent
MODULES = HERE / "modules.json"
RIG = HERE.parents[1] / "program" / "rig"

ROUTINES = {"play": 0, "rhythm": 1, "steps": 2, "arpeggio": 3}
AUTH = ("authentic", "analog", "strobed")
TOP = {"schema", "slug", "map", "auth", "program", "templates", "voices", "modules", "cables"}
BANNED = ("seastones",)  # PM-16: no preset is named after the record
NAME = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


@dataclass
class Problem:
    file: str
    line: int
    msg: str
    level: str = "error"  # error | warning | note

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.level}: {self.msg}"


class PatchError(Exception):
    def __init__(self, problems: list[Problem]):
        super().__init__("\n".join(str(p) for p in problems))
        self.problems = problems


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    data = json.loads(MODULES.read_text())
    return {m["type"]: m for m in data["modules"]}


@lru_cache(maxsize=4)
def channel_maps() -> dict[str, dict]:
    """The channel maps the program can be built for, by their `map:` name."""
    import sys

    sys.path.insert(0, str(HERE.parent))
    from sxasm.tables import read_channel_map

    maps = {}
    for f in sorted(RIG.glob("channel-map*.md")):
        m = read_channel_map(f)
        maps[m.name] = {"voices": m.voices, "gates": m.gate_source, "pitch": m.pitch,
                        "gate": m.gate, "lanes": m.lanes}  # fmt: skip
    return maps


def _ins(t: str) -> list[str]:
    return [p["name"] for p in registry()[t]["inputs"]]


def _outs(t: str) -> list[str]:
    return [p["name"] for p in registry()[t]["outputs"]]


class _Ctx:
    def __init__(self, file: str, text: str):
        self.file, self.text, self.problems = file, text, []
        self.lines = text.splitlines()

    def line_of(self, *needles: str) -> int:
        """The first line holding every needle (as JSON strings or keys), else 1."""
        for n, ln in enumerate(self.lines, 1):
            if all(x in ln for x in needles):
                return n
        for x in needles:
            for n, ln in enumerate(self.lines, 1):
                if x in ln:
                    return n
        return 1

    def err(self, msg: str, *where: str, level: str = "error") -> None:
        self.problems.append(Problem(self.file, self.line_of(*where), msg, level))


def _sub(expr: str, i: int) -> str:
    """Fill in {..} with the voice number i: whole-number arithmetic over i with + - * / %
    (/ rounds down), e.g. {i}, {i+4}, {i%2}, {i/2+1}."""

    def rep(m: re.Match) -> str:
        body = m.group(1).replace(" ", "")
        if not re.fullmatch(r"[i0-9+\-*/%()]+", body):
            raise ValueError(f"{{{m.group(1)}}}")
        return str(int(eval(body.replace("/", "//"), {"__builtins__": {}}, {"i": i})))  # noqa: S307

    return re.sub(r"\{([^{}]*)\}", rep, expr)


def _fill(c: _Ctx, expr: object, i: int) -> str:
    """_sub for a value from the file: a problem, not a crash, if it is not a usable string."""
    if not isinstance(expr, str):
        c.err(f"{expr!r} should be a jack name such as dac.{{i}}", '"voices"')
        return "?"
    try:
        return _sub(expr, i)
    except (ValueError, ZeroDivisionError, SyntaxError, TypeError) as e:
        c.err(f"'{expr}': {{...}} holds whole-number arithmetic over i, not {e}", f'"{expr}"')
        return "?"


def _check_params(c: _Ctx, mid: str, t: str, params: object) -> dict[str, float]:
    out: dict[str, float] = {}
    if params is None:
        return out
    if not isinstance(params, dict):
        c.err(f"module '{mid}': 'params' should be a set of name: number pairs", f'"{mid}"')
        return out
    decl = {p["name"]: p for p in registry()[t]["params"]}
    for k, v in params.items():
        if k not in decl:
            c.err(
                f"module '{mid}' ({t}) has no parameter '{k}'; it has " + ", ".join(sorted(decl)),
                f'"{k}"',
            )
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            c.err(f"module '{mid}': parameter '{k}' should be a number, not {v!r}", f'"{k}"')
            continue
        lo, hi = decl[k]["min"], decl[k]["max"]
        if not lo <= v <= hi:
            c.err(
                f"module '{mid}': {k} = {v} is outside {lo:g} to {hi:g}; it will be {min(max(v, lo), hi):g}",
                f'"{k}"',
                level="warning",
            )
            v = min(max(v, lo), hi)
        out[k] = float(v)
    return out


def check(obj: object, text: str = "", file: str = "patch.json") -> tuple[list[Problem], dict]:
    """Validate a parsed patch. Returns (problems, expanded) where `expanded` is the flat
    patch: {"modules": {id: (type, params)}, "cables": [(from, to)], "auth", "program"}."""
    c = _Ctx(file, text)
    flat: dict = {"modules": {}, "cables": [], "auth": "authentic", "program": None}
    if not isinstance(obj, dict):
        c.err("a patch is a JSON object: { ... }")
        return c.problems, flat
    for k in obj:
        if k not in TOP:
            c.err(f"unknown field '{k}': a patch has only " + ", ".join(sorted(TOP)), f'"{k}"')
    if obj.get("schema") != SCHEMA:
        c.err(f"'schema' must be \"{SCHEMA}\"", '"schema"')
    slug = obj.get("slug")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        c.err("'slug' must be a short name in lower case with hyphens", '"slug"')
    else:
        stem = Path(file).name.removesuffix(".patch.json")
        if file.endswith(".patch.json") and stem != slug:
            c.err(f"the slug '{slug}' should match the file name '{stem}.patch.json'", '"slug"')
        if any(b in slug for b in BANNED):
            c.err("a preset may not be named after the record (PM-16)", '"slug"')
    auth = obj.get("auth", "authentic")
    if not isinstance(auth, str) or auth not in AUTH:
        c.err(f"'auth' must be one of {', '.join(AUTH)}, not {auth!r}", '"auth"')
        auth = "authentic"
    flat["auth"] = auth
    maps = channel_maps()
    mapname = obj.get("map")
    cmap = maps.get(mapname) if isinstance(mapname, str) else None
    if cmap is None:
        c.err(f"'map' must name a channel map: {', '.join(sorted(maps))}", '"map"')
    prog = obj.get("program", {"routine": "play"})
    if prog is None:
        prog = {}
    if not isinstance(prog, dict) or set(prog) - {"routine", "variant", "transpose"}:
        c.err("'program' has only routine, variant and transpose", '"program"')
        prog = {}
    routine = prog.get("routine", "play")
    variant = prog.get("variant", 0)
    transpose = prog.get("transpose", 0)
    if not isinstance(routine, str) or routine not in ROUTINES:
        c.err(f"routine must be one of {', '.join(ROUTINES)}, not {routine!r}", '"routine"')
        routine = "play"
    if isinstance(variant, bool) or not isinstance(variant, int) or not 0 <= variant <= 15:
        c.err("variant must be a whole number from 0 to 15", '"variant"')
        variant = 0
    if isinstance(transpose, bool) or not isinstance(transpose, int) or not -8 <= transpose <= 7:
        c.err("transpose must be a whole number of semitones from -8 to 7", '"transpose"')
        transpose = 0
    flat["program"] = {"routine": routine, "variant": variant, "transpose": transpose,
                       "sr": (transpose & 0xF) << 8 | ROUTINES[routine] << 4 | variant}  # fmt: skip

    mods: dict[str, tuple[str, dict]] = {}

    def listed(x: object, what: str) -> list:
        if x is None:
            return []
        if not isinstance(x, list):
            c.err(f"'{what}' should be a list [ ... ]", f'"{what}"')
            return []
        return x

    def add_module(m: object, suffix: str = "", where: str = "modules") -> str | None:
        if not isinstance(m, dict) or set(m) - {"id", "type", "params"}:
            c.err(f"each entry in {where} has only id, type and params", f'"{where}"')
            return None
        mid, t = m.get("id"), m.get("type")
        if not isinstance(mid, str) or not NAME.fullmatch(mid):
            c.err(f"module id {mid!r}: use 1-16 of a-z, 0-9 and _, starting with a letter",
                  f'"{mid}"')  # fmt: skip
            return None
        if not isinstance(t, str) or t not in registry():
            c.err(f"module '{mid}': no module type {t!r}; types are " + ", ".join(registry()),
                  f'"{mid}"')  # fmt: skip
            return None
        full = mid + suffix
        if full in mods:
            c.err(f"two modules are called '{full}'", f'"{mid}"')
            return None
        mods[full] = (t, _check_params(c, mid, t, m.get("params")))
        return full

    templates = obj.get("templates", {})
    if not isinstance(templates, dict):
        c.err("'templates' should be a set of name: {modules, cables}", '"templates"')
        templates = {}
    voices = obj.get("voices")
    tcables: list = []
    nvoices = 0
    if voices is not None:
        if not isinstance(voices, dict) or set(voices) - {
            "template",
            "count",
            "pitch",
            "gate",
            "out",
        }:
            c.err("'voices' has template, count, pitch, gate and out", '"voices"')
        else:
            tname = voices.get("template")
            tpl = templates.get(tname) if isinstance(tname, str) else None
            nvoices = voices.get("count", 0)
            if not isinstance(tpl, dict) or set(tpl) - {"modules", "cables"}:
                c.err(f"'voices' names template {tname!r}, which is not in 'templates'",
                      '"template"')  # fmt: skip
            elif isinstance(nvoices, bool) or not isinstance(nvoices, int) or not 1 <= nvoices <= 8:
                c.err("voice count must be from 1 to 8", '"count"')
            else:
                if cmap and nvoices != cmap["voices"]:
                    c.err(f"the map '{mapname}' has {cmap['voices']} voices but the patch makes "
                          f"{nvoices} (PRG-12: one voice card per voice)", '"count"')  # fmt: skip
                tmods = listed(tpl.get("modules"), "modules")
                tids = {m.get("id") for m in tmods
                        if isinstance(m, dict) and isinstance(m.get("id"), str)}  # fmt: skip
                for i in range(nvoices):
                    for m in tmods:
                        add_module(m, str(i), "the voice template")
                    for cab in listed(tpl.get("cables"), "cables"):
                        if not (isinstance(cab, list) and len(cab) == 2):
                            c.err("a cable is [from, to]", '"cables"')
                            continue
                        ends = []
                        for e in cab:
                            if not isinstance(e, str):
                                ends.append("?")
                                continue
                            if e.startswith("$"):
                                key = e[1:]
                                val = voices.get(key)
                                if not isinstance(val, str):
                                    c.err(f"the template uses {e} but 'voices' has no '{key}'",
                                          f'"{e}"')  # fmt: skip
                                    ends.append("?")
                                    continue
                                ends.append(_fill(c, val, i))
                            elif "." in e and e.split(".")[0] in tids:
                                mid, port = e.split(".", 1)
                                ends.append(f"{mid}{i}.{port}")
                            else:
                                ends.append(e)
                        tcables.append((ends[0], ends[1], cab))
                    if cmap:
                        _check_voice_map(c, voices, i, cmap)
    for m in listed(obj.get("modules"), "modules"):
        add_module(m)
    if "out" not in mods:
        mods["out"] = ("out", {})
    elif mods["out"][0] != "out":
        c.err("'out' is the output: it must be an out module", '"out"')

    cables: list[tuple[str, str]] = []
    for f, t, _raw in tcables:
        cables.append((f, t))
    for cab in listed(obj.get("cables"), "cables"):
        if not (isinstance(cab, list) and len(cab) == 2 and all(isinstance(e, str) for e in cab)):
            c.err('a cable is ["from", "to"]', '"cables"')
            continue
        f, t = cab
        if "*." in t:
            stem, port = t.split("*.", 1)
            hits = [m for m in mods if re.fullmatch(re.escape(stem) + r"\d", m)]
            if not hits:
                c.err(f"cable to {t}: no module is called {stem}0, {stem}1 ...", f'"{t}"')
            cables += [(f, f"{m}.{port}") for m in sorted(hits)]
        else:
            cables.append((f, t))
    taken: dict[str, str] = {}
    for f, t in cables:
        if not _endpoint(c, mods, f, output=True) or not _endpoint(c, mods, t, output=False):
            continue
        if t in taken:
            c.err(f"{t} already has a cable (from {taken[t]}): one cable per input", f'"{t}"')
            continue
        taken[t] = f
        flat["cables"].append((f, t))
    flat["modules"] = mods
    if not c.problems or all(p.level != "error" for p in c.problems):
        if not _reaches_out(flat):
            c.err("nothing from the computer reaches the speaker: the screen will show "
                  "'Nothing reaches the speaker' (PATCH-4)", level="note")  # fmt: skip
    return c.problems, flat


def _check_voice_map(c: _Ctx, voices: dict, i: int, cmap: dict) -> None:
    if i >= cmap["voices"]:
        return  # the count is already wrong, and said so
    want_p = f"dac.{cmap['pitch'][i]}"
    want_g = f"{'dac' if cmap['gates'] == 'dac' else 'gate'}.{cmap['gate'][i]}"
    got_p, got_g = _fill(c, voices.get("pitch"), i), _fill(c, voices.get("gate"), i)
    if got_p != want_p:
        c.err(f"voice {i + 1}'s pitch is {got_p} but the map puts it on {want_p}", '"pitch"')
    if got_g != want_g:
        c.err(f"voice {i + 1}'s gate is {got_g} but the map puts it on {want_g}", '"gate"')


def _endpoint(c: _Ctx, mods: dict, e: str, output: bool) -> bool:
    m = re.fullmatch(r"(dac|gate)\.(\d+)", e)
    if m:
        if not output:
            c.err(f"{e} is a line from the computer: it can only be the start of a cable",
                  f'"{e}"')  # fmt: skip
            return False
        if int(m.group(2)) > 15:
            c.err(f"{e}: there are 16 {m.group(1)} lines, 0 to 15", f'"{e}"')
            return False
        return True
    if "." not in e:
        c.err(f"{e!r} is not a jack: write module.port, dac.N or gate.N", f'"{e}"')
        return False
    mid, port = e.split(".", 1)
    if mid not in mods:
        c.err(f"cable end {e}: there is no module '{mid}'", f'"{e}"')
        return False
    t = mods[mid][0]
    ports = _outs(t) if output else _ins(t)
    if port not in ports:
        kind = "output" if output else "input"
        c.err(f"{e}: a {t} has no {kind} '{port}'; its {kind}s are " + ", ".join(ports), f'"{e}"')
        return False
    return True


def _reaches_out(flat: dict) -> bool:
    reach: set[str] = set()
    changed = True
    while changed:
        changed = False
        for f, t in flat["cables"]:
            src = f.split(".")[0]
            dst = t.split(".")[0]
            if (src in ("dac", "gate") or src in reach) and dst not in reach:
                reach.add(dst)
                changed = True
    return "out" in reach


def compile_graph(flat: dict) -> str:
    """The engine's seastones.graph/1 text for an expanded patch (deterministic)."""
    out = ["graph 1"]
    for mid, (t, params) in flat["modules"].items():
        out.append(f"module {mid} {t}")
        for k, v in params.items():
            out.append(f"param {mid} {k} {v:.9g}")
    for f, t in flat["cables"]:
        out.append(f"cable {f} {t}")
    out.append("end")
    return "\n".join(out) + "\n"


def load(path: Path) -> tuple[list[Problem], dict]:
    text = path.read_text(encoding="utf-8")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return [Problem(path.name, e.lineno, f"this is not valid JSON: {e.msg}")], {}
    return check(obj, text, path.name)


def compile_file(path: Path) -> tuple[str, dict]:
    """Validate and compile; raises PatchError on any error."""
    problems, flat = load(path)
    errors = [p for p in problems if p.level == "error"]
    if errors:
        raise PatchError(errors)
    return compile_graph(flat), flat
