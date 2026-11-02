"""The patch wall as it follows from an engine-format patch: a line-for-line Python port of the
UI's src/web/app/wallmodel.js (layoutOf, jacksOf, cablesOf, reachesOut, evalIndex, fill), so
rigd's `patch` message carries the same `layout` and wall cables the page and the fake engine
compute. tests/rigd/test_wall.py runs wallmodel.js under node over every preset and compares.

Plus what wallmodel.js only documents and rigd must do: the engine port behind each wall jack
(`engine_ends`), used to turn wall cable edits into a patch for sx_patch_load:

    v<n>.pitch -> the template's $pitch inputs for voice n-1    v<n>.gate -> its $gate inputs
    v<n>.out   -> the template's $out source                     v<n>.<tid>-<port> -> <tid><n-1>.<port>
    <id>.<port>, dac.<k>, gate.<k> -> themselves
"""

from __future__ import annotations

import re

WILD = re.compile(r"^([a-z][a-z0-9_]*)\*\.([a-z0-9_]+)$")
VOICE_JACK = re.compile(r"^v(\d)\.(pitch|gate|out|([a-z][a-z0-9_]*)-([a-z0-9_]+))$")
SHORT = {"square": "SQR", "sh": "S&H", "cutoff": "CUT", "resonance": "RES"}
NAMED = {"send": "ECHO SEND", "busl": "LEFT", "busr": "RIGHT", "out": "OUTPUT", "vib": "VIBRATO",
         "soft": "SLEW"}  # fmt: skip
TYPE_TITLE = {"lfo": "LFO", "mixer": "MIXER", "echo": "ECHO", "slew": "SLEW", "noise": "NOISE",
              "vcf": "FILTER", "vco": "VCO", "env": "ENVELOPE", "vca": "VCA", "out": "OUTPUT"}  # fmt: skip


def eval_index(expr: str, i: int) -> int:
    """Whole-number arithmetic over i with + - * / % and brackets (/ rounds down), as sxpatch."""
    src = re.sub(r"\s+", "", str(expr))
    toks = re.findall(r"i|\d+|[-+*/%()]", src)
    if "".join(toks) != src:
        raise ValueError(f"bad expression {{{expr}}}")
    k = 0

    def peek():
        return toks[k] if k < len(toks) else None

    def atom() -> int:
        nonlocal k
        t = peek()
        k += 1
        if t == "(":
            v = total()
            if peek() != ")":
                raise ValueError(f"bad expression {{{expr}}}")
            k += 1
            return v
        if t == "-":
            return -atom()
        if t == "i":
            return i
        if t is not None and t.isdigit():
            return int(t)
        raise ValueError(f"bad expression {{{expr}}}")

    def prod() -> int:
        nonlocal k
        v = atom()
        while peek() in ("*", "/", "%"):
            op = toks[k]
            k += 1
            r = atom()
            v = v * r if op == "*" else v // r if op == "/" else v % r  # Python: floor, never <0
        return v

    def total() -> int:
        nonlocal k
        v = prod()
        while peek() in ("+", "-"):
            op = toks[k]
            k += 1
            r = prod()
            v = v + r if op == "+" else v - r
        return v

    v = total()
    if k != len(toks):
        raise ValueError(f"bad expression {{{expr}}}")
    return v


def fill(s: str, i: int) -> str:
    return re.sub(r"\{([^{}]*)\}", lambda m: str(eval_index(m.group(1), i)), str(s))


def port_label(p: str) -> str:
    m = re.match(r"^in(\d)$", p)
    return p[2:] if m else SHORT.get(p, p.upper())


def layout_of(patch: dict, registry: dict) -> dict:
    """registry: {type: {"inputs": [{"name"}], "outputs": [{"name"}]}}."""
    voices = patch.get("voices") or {"count": 0}
    count = max(0, min(8, voices.get("count") or 0))
    ports: list[dict] = []
    seen: set[str] = set()
    for a, b in patch.get("cables") or []:
        for end in (a, b):
            m = WILD.match(end)
            if m and f"{m[1]}-{m[2]}" not in seen:
                seen.add(f"{m[1]}-{m[2]}")
                ports.append({"id": f"{m[1]}-{m[2]}", "label": port_label(m[2]), "out": end == a})
    labels = [p["label"] for p in ports]
    for p in ports:  # two template ports with the same name keep their module in the label
        if labels.count(p["label"]) > 1:
            p["label"] = f"{p['id'].split('-')[0].upper()} {p['label']}"
    mods = list(patch.get("modules") or [])
    if not any(m["id"] == "out" for m in mods):
        mods.append({"id": "out", "type": "out"})
    by_type: dict[str, int] = {}
    for m in mods:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1
    nth: dict[str, int] = {}
    modules = []
    for m in mods:
        reg = registry.get(m["type"], {"inputs": [], "outputs": []})
        nth[m["type"]] = nth.get(m["type"], 0) + 1
        base = NAMED.get(m["id"]) or TYPE_TITLE.get(m["type"]) or m["type"].upper()
        title = (
            f"{base} {nth[m['type']]}" if m["id"] not in NAMED and by_type[m["type"]] > 1 else base
        )
        modules.append({"id": m["id"], "type": m["type"], "title": title,
                        "ins": [p["name"] for p in reg["inputs"]],
                        "outs": [p["name"] for p in reg["outputs"]]})  # fmt: skip
    gates = isinstance(voices.get("gate"), str) and voices["gate"].startswith("gate.")
    return {"map": patch.get("map") or "", "rail": {"gates": gates},
            "voices": {"count": count, "ports": ports}, "modules": modules}  # fmt: skip


def jacks_of(layout: dict) -> list[dict]:
    out = [{"id": f"dac.{k}", "kind": "source", "plate": "rail"} for k in range(16)]
    if layout["rail"]["gates"]:
        out += [{"id": f"gate.{k}", "kind": "gate", "plate": "rail"} for k in range(8)]
    for n in range(1, layout["voices"]["count"] + 1):
        out.append({"id": f"v{n}.pitch", "label": "PITCH", "kind": "in", "plate": f"v{n}"})
        out.append({"id": f"v{n}.gate", "label": "GATE", "kind": "in", "plate": f"v{n}"})
        for p in layout["voices"]["ports"]:
            out.append({"id": f"v{n}.{p['id']}", "label": p["label"],
                        "kind": "out" if p["out"] else "in", "plate": f"v{n}"})  # fmt: skip
        out.append({"id": f"v{n}.out", "label": "OUT", "kind": "out", "plate": f"v{n}"})
    for m in layout["modules"]:
        for p in m["ins"]:
            out.append(
                {"id": f"{m['id']}.{p}", "label": port_label(p), "kind": "in", "plate": m["id"]}
            )
        for p in m["outs"]:
            out.append({"id": f"{m['id']}.{p}", "label": port_label(p), "kind": "out",
                        "plate": m["id"]})  # fmt: skip
    return out


def cables_of(patch: dict, layout: dict) -> list[dict]:
    out = []
    v = patch.get("voices") or {}
    for i in range(layout["voices"]["count"]):
        n = i + 1
        if v.get("pitch"):
            out.append({"from": fill(v["pitch"], i), "to": f"v{n}.pitch"})
        if v.get("gate"):
            out.append({"from": fill(v["gate"], i), "to": f"v{n}.gate"})
        if v.get("out"):
            out.append({"from": f"v{n}.out", "to": fill(v["out"], i)})

    def end(e: str, n: int) -> str:
        m = WILD.match(e)
        return f"v{n}.{m[1]}-{m[2]}" if m else e

    for a, b in patch.get("cables") or []:
        if WILD.match(a) or WILD.match(b):
            for n in range(1, layout["voices"]["count"] + 1):
                out.append({"from": end(a, n), "to": end(b, n)})
        else:
            out.append({"from": a, "to": b})
    return out


def reaches_out(cables: list[dict], layout: dict) -> bool:
    adj: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)

    for c in cables:
        link(c["from"], c["to"])
    for m in layout["modules"]:
        if m["type"] == "out":
            continue
        for i in m["ins"]:
            for o in m["outs"]:
                link(f"{m['id']}.{i}", f"{m['id']}.{o}")
    outm = next((m for m in layout["modules"] if m["type"] == "out"), {"ins": []})
    sinks = {f"out.{p}" for p in outm["ins"]}

    def fed(jack: str) -> bool:
        seen, q = {jack}, [jack]
        while q:
            n = q.pop(0)
            if re.match(r"^(dac|gate)\.\d+$", n):
                return True
            for c in cables:
                o = c["to"] if c["from"] == n else c["from"] if c["to"] == n else None
                if o and o not in seen:
                    seen.add(o)
                    q.append(o)
        return False

    for n in range(1, layout["voices"]["count"] + 1):
        if not fed(f"v{n}.gate"):
            continue
        seen, q = {f"v{n}.out"}, [f"v{n}.out"]
        while q:
            j = q.pop(0)
            if j in sinks:
                return True
            for k in adj.get(j, ()):
                if k not in seen:
                    seen.add(k)
                    q.append(k)
    return False


# --- the engine port behind each wall jack (rigd only) --------------------------------------


def voice_template(patch: dict) -> tuple[dict, list[list[str]]]:
    v = patch.get("voices") or {}
    tpl = (patch.get("templates") or {}).get(v.get("template"), {})
    return tpl, [list(c) for c in tpl.get("cables", [])]


def engine_ends(jack: str, patch: dict) -> list[str]:
    """The engine jacks a wall jack stands for (a voice's pitch or gate may feed several)."""
    m = VOICE_JACK.match(jack)
    if not m:
        return [jack]
    i = int(m[1]) - 1
    _, tcables = voice_template(patch)

    def inst(e: str) -> str:  # a template endpoint for voice i: osc.pitch -> osc<i>.pitch
        mod, _, port = fill(e, i).partition(".")
        return f"{mod}{i}.{port}"

    kind = m[2]
    if kind in ("pitch", "gate"):
        return [inst(t) for s, t in tcables if s == f"${kind}"]
    if kind == "out":
        return [inst(s) for s, t in tcables if t == "$out"]
    return [f"{m[3]}{i}.{m[4]}"]


def internal_cables(patch: dict, count: int) -> list[tuple[str, str]]:
    """The template's own cables inside each voice: not on the wall, always in the patch."""
    _, tcables = voice_template(patch)
    out = []
    for i in range(count):
        for s, t in tcables:
            if s.startswith("$") or t.startswith("$"):
                continue
            ends = []
            for e in (s, t):
                mod, _, port = fill(e, i).partition(".")
                ends.append(f"{mod}{i}.{port}")
            out.append((ends[0], ends[1]))
    return out


def engine_cables(wall_cables: list[dict], patch: dict, count: int) -> list[tuple[str, str]]:
    """The engine's flat cable list for these wall cables over this patch's modules."""
    out = list(internal_cables(patch, count))
    for c in wall_cables:
        for a in engine_ends(c["from"], patch):
            for b in engine_ends(c["to"], patch):
                if (a, b) not in out:
                    out.append((a, b))
    return out
