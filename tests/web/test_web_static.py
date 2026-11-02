"""Static checks over the page's own files (VS-15, UI-04, UI-32, UI-35, CT-06, PM-18, CONT-1).

These read src/web/ and content/ as text. They fail the build when:
- a lamp, meter or anything else could be driven by randomness (UI-04: no Math.random or
  crypto.getRandomValues anywhere in src/web/);
- the page could make a sound (UI-32, AUDIO-1, D6: no AudioContext, Audio(), media element,
  speech, or audio asset);
- the page could reach off the machine (KIOSK-6: no http(s) URL in served code);
- layer 6 or a teaser leaks into the visitor build (UI-35, CT-06, SEA-5);
- a drawing carries a raster image or a protected name (PM-18, PR-05, B-05);
- the protocol grows a memory-writing message (CODE-4);
- a caption the page asks for does not exist in content (CONT-1).
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB = os.path.join(ROOT, "src", "web")
APP = os.path.join(WEB, "app")
CONTENT = os.path.join(ROOT, "content")


def _files(base: str, exts: tuple[str, ...]) -> list[str]:
    out = []
    for dirpath, _, names in os.walk(base):
        for n in names:
            if n.endswith(exts):
                out.append(os.path.join(dirpath, n))
    return sorted(out)


def _code(path: str) -> str:
    """The file without // and /* */ comments, so a comment may name what is forbidden."""
    text = open(path, encoding="utf-8").read()
    if path.endswith((".js", ".mjs", ".css")):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", text)
    if path.endswith(".html"):
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


SERVED = _files(WEB, (".js", ".mjs", ".css", ".html"))


def test_the_page_exists():
    assert os.path.exists(os.path.join(WEB, "index.html"))
    assert len(SERVED) > 10


def test_no_random_source_anywhere_in_the_page():
    for f in SERVED:
        code = _code(f)
        assert "Math.random" not in code, f
        assert "getRandomValues" not in code, f


def test_the_page_makes_no_sound():
    banned = re.compile(
        r"AudioContext|webkitAudioContext|new\s+Audio\s*\(|<audio|<video|speechSynthesis|HTMLMediaElement|\.play\s*\("
    )
    for f in SERVED:
        m = banned.search(_code(f))
        assert not m, f"{f}: {m.group(0)}"
    for f in _files(WEB, (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aiff", ".opus")):
        raise AssertionError(f"audio asset in the page: {f}")


def test_no_request_off_the_machine():
    for f in SERVED:
        # the SVG namespace is a name, not a request
        m = re.search(r"https?://(?!127\.0\.0\.1|localhost|www\.w3\.org/2000/svg)", _code(f))
        assert not m, f"{f}: {m.group(0)}"


def test_no_layer_6_or_teaser_in_the_visitor_build():
    banned = re.compile(r"coming soon|seastones playback|best guess|layer[ -]?6", re.I)
    for f in SERVED + _files(CONTENT, (".md", ".conf")):
        m = banned.search(_code(f))
        assert not m, f"{f}: {m.group(0)}"


def test_drawings_are_vector_and_carry_no_protected_name():
    assert not _files(WEB, (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
    protected = re.compile(r"\bE-?mu\b|\bARP\b|Buchla|Moog|Steal Your Face", re.I)
    for name in ("patchwall.js", "panel.js", "attract.js", "story-art.js", "shell.js"):
        code = _code(os.path.join(APP, name))
        assert "<image" not in code, name
        m = protected.search(code)
        assert not m, f"{name}: {m.group(0)}"


def test_the_protocol_has_no_memory_writing_message():
    code = open(os.path.join(APP, "protocol.js"), encoding="utf-8").read()
    types = re.findall(r't: "([a-z.]+)"', code)
    assert set(types) == {
        "keys.touch",
        "machine.speed",
        "machine.step",
        "machine.home",
        "patch.connect",
        "patch.disconnect",
        "patch.load",
        "audio.volume",
        "audio.mute",
    }
    for f in SERVED:
        assert not re.search(r"[\"'`](machine\.sr|passage\.)|deposit", _code(f)), f
        # Staff commands (PIN-gated, ARCHITECTURE 4.4) live in staff.js and nowhere else.
        if os.path.basename(f) != "staff.js":
            assert not re.search(r"[\"'`]staff\.[a-z]", _code(f)), f


def test_staff_commands_match_the_schema_and_write_no_memory():
    """KP-07 to KP-09: the page's staff set is exactly the schema's staff set, and no staff
    command (or field) touches memory, the switch register or a passage (CODE-4)."""
    import json  # noqa: PLC0415

    code = _code(os.path.join(APP, "staff.js"))
    m = re.search(r"STAFF_TYPES = \[(.*?)\];", code, flags=re.S)
    assert m
    page = set(re.findall(r'"(staff\.[a-z_]+)"', m.group(1)))
    schema = json.load(open(os.path.join(ROOT, "tests/web/fake-engine/schema/protocol-v1.json")))
    staff = {t: s for t, s in schema["client"].items() if t.startswith("staff.")}
    assert page == set(staff)
    for t, s in staff.items():
        assert not re.search(r"mem|dep|sr\b|switch|passage|addr|word", t), t
        for prop in s["properties"]:
            assert not re.search(r"mem|addr|word|data|sr\b", prop), (t, prop)
    # every staff.* string the page sends is in that list
    sent = set(re.findall(r"[\"\'`](staff\.[a-z_]+)[\"\'`]", code))
    assert sent <= page, sent - page


def _captions() -> dict[str, set[str]]:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from content.tool.index import build_index  # noqa: PLC0415
    from content.tool.parse import load_content_dir  # noqa: PLC0415

    index = build_index(load_content_dir(CONTENT), "check")
    out: dict[str, set[str]] = {}
    for c in index["collections"]["captions"]:
        keys: set[str] = set()
        for b in c.get("blocks", []):
            if b["type"] == "cards":
                keys.update(i["title"] for i in b["items"] if i.get("text"))
                keys.update(f"{i['title']}.meta" for i in b["items"] if i.get("meta"))
        out[c["slug"]] = keys
    return out


#: Captions the page builds from a variable: area, key pattern, values.
DYNAMIC = {
    ("frame", "dock-{}"): ["play", "computer", "code", "patch", "story"],
    ("play", "station-{}"): ["1", "2", "3", "4", "5"],
    ("speed", "{}"): ["run", "div30", "div300", "div3000", "crawl", "step"],
    ("faults", "{}"): ["computer", "sound"],
    ("faults", "stage-{}"): ["computer", "program", "synth", "output"],
    ("faults", "staff-{}"): [
        "disconnected",
        "starting",
        "program_stalled",
        "dsp_fault",
        "audio_device_missing",
        "audio_stalled",
        "image_missing",
        "image_hash_mismatch",
        "config_invalid",
        "engine_load_failed",
    ],
}


def test_every_caption_the_page_asks_for_exists_in_content():
    caps = _captions()
    missing = []
    for f in _files(APP, (".js",)):
        code = _code(f)
        for fn, area, key in re.findall(r'\b([SM])\("([a-z]+)",\s*"([a-z0-9_.-]+)"', code):
            want = key if fn == "S" else f"{key}.meta"
            if want not in caps.get(area, set()):
                missing.append(f"{os.path.basename(f)}: {fn}({area}, {key})")
    for (area, pattern), values in DYNAMIC.items():
        for v in values:
            key = pattern.format(v)
            if key not in caps.get(area, set()):
                missing.append(f"dynamic {area}/{key}")
    assert not missing, missing
    # the variants with a second line need it too
    for v in ["computer", "sound", "starting"]:
        assert f"{v}.meta" in caps["faults"], v
    for n in range(1, 6):
        assert f"station-{n}.meta" in caps["play"]


def test_every_program_block_has_exactly_one_code_note():
    """CODE-2 / PR-10: the code view shows one note per `*@block` of today's program. A
    program change that adds or renames a block (ADR-009 did both) must bring its note, and
    a note for a block that no longer exists is stale copy on the floor."""
    blocks = set()
    # every source the program is assembled from: the Makefile's PROGRAM_S, so a new file
    # (polyphony added voices.s, routines.s and memory.s) cannot slip past this check
    mk = open(os.path.join(ROOT, "Makefile"), encoding="utf-8").read()
    m = re.search(r"(?m)^PROGRAM_S\s*:=\s*((?:.*\\\n)*.*)$", mk)
    assert m, "no PROGRAM_S in the Makefile"
    sources = m.group(1).replace("\\\n", " ").split()
    assert len(sources) >= 3, sources
    for name in sources:
        text = open(os.path.join(ROOT, name), encoding="utf-8").read()
        blocks |= set(re.findall(r"(?m)^\*@block\s+([a-z0-9-]+)", text))
    notes: dict[str, str] = {}
    code_dir = os.path.join(CONTENT, "code")
    for f in sorted(os.listdir(code_dir)):
        if f.endswith(".md"):
            m = re.search(r"(?m)^block:\s*([a-z0-9-]+)", open(os.path.join(code_dir, f)).read())
            assert m, f"{f}: no block: field"
            assert m.group(1) not in notes, f"{f} and {notes.get(m.group(1))} share a block"
            notes[m.group(1)] = f
    assert blocks, "no *@block markers found in src/program"
    assert sorted(blocks - set(notes)) == [], "blocks without a note"
    assert sorted(set(notes) - blocks) == [], "notes for blocks the program no longer has"


def test_the_about_page_has_every_part_it_must_carry():
    """CT-09 AC 2 (the web half; the content validator is CT-03's): credits, notices and the
    privacy statement exist in content, with the LEGAL-REVIEW 5 and 7 wording's key parts."""
    caps = _captions()
    about = caps.get("about", set())
    for key in ("heading", "credits", "notices", "privacy", "close"):
        assert key in about, key
    sys.path.insert(0, os.path.join(ROOT, "src"))
    text = open(os.path.join(CONTENT, "captions", "about.md"), encoding="utf-8").read()
    assert "open-simh" in text and "Robert M. Supnik" in text
    assert "collects no personal information" in text
    disclosure = open(os.path.join(CONTENT, "captions", "disclosure.md"), encoding="utf-8").read()
    body = disclosure.split("\n\n", 1)[1]
    assert len(body.split()) == 52, "the full disclosure is the UX 8.3 52-word text"


# The longest each short fixed caption may be, in characters: the layout holds these at the
# design sizes (tests/web/ui/long-content.spec.mjs LIMITS renders them). Prose (story, block
# notes) has word limits instead and steps its size down when it reaches them (fit.js).
CAPTION_LIMITS = {
    ("play", "station-1", "meta"): 56,
    ("play", "station-2", "meta"): 56,
    ("play", "station-3", "meta"): 42,  # four voice rows above it
    ("play", "station-4", "meta"): 56,
    ("play", "station-5", "meta"): 28,
    **{("speed", k, "text"): 80 for k in ("run", "div30", "div300", "div3000", "crawl", "step")},
    ("speed", "estimate", "text"): 70,
}


def test_short_captions_fit_their_boxes():
    """UI-38: a caption longer than its box holds is caught here, before it reaches a card."""
    too_long = []
    for (area, key, field), limit in CAPTION_LIMITS.items():
        text = open(os.path.join(CONTENT, "captions", f"{area}.md"), encoding="utf-8").read()
        m = re.search(rf"(?ms)^## {re.escape(key)}\n(.*?)(?=^## |\Z)", text)
        assert m, f"{area}/{key} missing"
        f = re.search(rf"(?m)^{field}: (.*)$", m.group(1))
        assert f, f"{area}/{key} has no {field}"
        if len(f.group(1)) > limit:
            too_long.append(f"{area}/{key}.{field}: {len(f.group(1))} > {limit}")
    assert not too_long, too_long
