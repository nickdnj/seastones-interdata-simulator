"""CT-01 / CNT-01, CNT-04 (indexer half): the ported content tool.

The sample tree in tests/content/sample/content/ uses placeholder words only. Broken files
are planted in a temporary copy at run time.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from content.tool.index import build, build_index, dumps  # noqa: E402
from content.tool.parse import load_content_dir  # noqa: E402

SAMPLE = REPO_ROOT / "tests" / "content" / "sample" / "content"


@pytest.fixture
def tree(tmp_path):
    dst = tmp_path / "content"
    shutil.copytree(SAMPLE, dst)
    return dst


def index_of(root: Path) -> dict:
    return build_index(load_content_dir(str(root)))


def entry(index, collection, slug):
    return next(e for e in index["collections"][collection] if e["slug"] == slug)


def errors(index):
    return [p["text"] for p in index["problems"] if p["level"] == "error"]


# ---------------------------------------------------------------- builds


def test_sample_builds_clean(tmp_path):
    index = build(str(SAMPLE), str(tmp_path / "out"))
    assert errors(index) == []
    on_disk = json.loads((tmp_path / "out" / "index.json").read_text())
    assert on_disk == json.loads(dumps(index))
    assert (tmp_path / "out" / "report.txt").read_text().startswith("content index")


def test_every_collection_is_indexed():
    index = index_of(SAMPLE)
    for name in ("screens", "captions", "code", "presets", "passages", "rig"):
        assert index["collections"][name], name
    assert (
        entry(index, "presets", "sample-drone")["pair"] == "content/presets/sample-drone.patch.json"
    )
    assert entry(index, "rig", "dac")["values"] == {
        "word_bits": "12",
        "range_v": "10.24",
        "output_hz": "1000",
    }


def test_visitor_order_and_review_order():
    index = index_of(SAMPLE)
    assert index["order"]["screens"] == ["sample-one"]
    assert index["review_order"]["screens"] == ["sample-one", "sample-two"]
    assert index["order"]["passages"] == []  # draft-hidden passages never in the visitor order
    assert index["layer6_available"] is False


def test_staff_fields_kept_apart_and_pin_not_exported():
    index = index_of(SAMPLE)
    one = entry(index, "screens", "sample-one")
    assert one["staff"]["note"].startswith("staff-only")
    visible = json.dumps([one["title"], one["blocks"]])
    assert "staff-only" not in visible
    assert "staff_pin" not in index["conf"]


def test_deterministic_bytes():
    assert dumps(index_of(SAMPLE)) == dumps(index_of(SAMPLE))


# ---------------------------------------------------------------- CNT-04: broken is visible


def test_broken_file_becomes_an_error_card_not_a_crash(tree):
    (tree / "screens" / "01-sample-one.md").write_bytes(b"title: Sample\n\xff\xfe broken\n")
    index = index_of(tree)
    card = entry(index, "screens", "sample-one")
    assert card["error_card"] is True
    assert card["title"] == "Sample: this part could not load."
    assert card["staff"]["why"]
    # The broken screen keeps its place in the visitor order, so the gap is visible.
    assert "sample-one" in index["order"]["screens"]
    # Everything else still renders.
    assert entry(index, "captions", "sample-caption")["error_card"] is False
    assert index["counts"]["error_cards"] == 1


@pytest.mark.parametrize(
    "rel,text,rule",
    [
        ("screens/03-bad.md", "title: x\nstatus: maybe\nslug: bad\n\nbody\n", "status-not-valid"),
        ("screens/04-bad.md", "title: x\nslug: Not A Slug\nstatus: ready\n\nb\n", "slug-shape"),
        ("screens/05-bad.md", "status: ready\nslug: noname\n\nbody\n", "missing-required-key"),
        ("screens/06-bad.md", "title: x\nthis line has no colon\n\nb\n", "header-line-unreadable"),
        ("presets/lonely.md", "title: x\nstatus: ready\n\nb\n", "pair-missing"),
        ("presets/junk.md", "title: x\nstatus: ready\n\nb\n", "patch-unreadable"),
        ("passages/p2.md", "title: x\nstatus: draft-hidden\n\nb\n", "score-invalid"),
    ],
)
def test_each_unrenderable_problem_gives_an_error_card(tree, rel, text, rule):
    path = tree / rel
    path.write_text(text)
    if rel == "presets/junk.md":
        (tree / "presets" / "junk.patch.json").write_text("{not json")
    if rel == "passages/p2.md":
        (tree / "passages" / "p2.score").write_text("score: 1\ntitle: x\n")
    index = index_of(tree)
    rules = {p["rule"] for p in index["problems"] if p["file"] == f"content/{rel}"}
    assert rule in rules, rules
    collection = rel.split("/")[0]
    cards = [e for e in index["collections"][collection] if e["file"] == f"content/{rel}"]
    assert cards and cards[0]["error_card"] is True


def test_orphan_machine_half_reported(tree):
    (tree / "presets" / "ghost.patch.json").write_text('{"schema": "seastones.patch/1"}')
    assert any("ghost.patch.json" in t and "no words file" in t for t in errors(index_of(tree)))


def test_unknown_slot_and_duplicate_slug(tree):
    (tree / "screens" / "07-dup.md").write_text(
        "title: x\nslug: sample-one\nstatus: ready\nslots: nope\n\nb\n"
    )
    errs = errors(index_of(tree))
    assert any("slug 'sample-one'" in t for t in errs)
    assert any("slot 'nope'" in t for t in errs)


def test_ready_passage_prints_rights_reminder_and_needs_ledger(tree):
    p = tree / "passages" / "sample-passage.md"
    p.write_text(p.read_text().replace("status: draft-hidden", "status: ready"))
    index = index_of(tree)
    rules = {x["rule"] for x in index["problems"]}
    assert "passage-ready-rights" in rules
    assert "passage-ready-without-ledger" in rules


def test_missing_content_dir_is_a_problem_not_a_crash(tmp_path):
    index = index_of(tmp_path / "nowhere")
    assert any("no content folder" in t for t in errors(index))


def test_smart_quotes_crlf_and_bom_tolerated(tree):
    path = tree / "captions" / "sample-caption.md"
    path.write_bytes(
        b"\xef\xbb\xbftitle: Sample caption\r\nstatus: ready\r\n\r\nIt\xe2\x80\x99s fine.\r\n"
    )
    index = index_of(tree)
    cap = entry(index, "captions", "sample-caption")
    assert cap["error_card"] is False
    assert cap["blocks"][0]["text"] == "It's fine."
    assert any(p["rule"] == "smart-quotes" for p in index["problems"])


# ---------------------------------------------------------------- CNT-01: words live in content


def test_changing_a_visitor_word_touches_no_file_under_src(tree):
    before = dumps(index_of(tree))
    src_before = {p: p.read_bytes() for p in (REPO_ROOT / "src").rglob("*") if p.is_file()}
    path = tree / "screens" / "01-sample-one.md"
    path.write_text(path.read_text().replace("Sample paragraph", "Changed paragraph"))
    after = index_of(tree)
    assert dumps(after) != before
    assert entry(after, "screens", "sample-one")["blocks"][0]["text"].startswith("Changed")
    src_after = {p: p.read_bytes() for p in (REPO_ROOT / "src").rglob("*") if p.is_file()}
    assert src_after == src_before


def test_sample_words_do_not_appear_in_src():
    words = ["Sample paragraph for the first screen", "A sample caption", "Sample drone"]
    for p in (REPO_ROOT / "src").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for w in words:
            assert w not in text, (p, w)


# ---------------------------------------------------------------- CLI


def test_cli_build_and_check(tree, tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    cmd = [sys.executable, "-m", "content.tool"]
    ok = subprocess.run(cmd + ["check", str(tree)], env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    out = tmp_path / "out"
    b = subprocess.run(
        cmd + ["build", str(tree), str(out)], env=env, capture_output=True, text=True
    )
    assert b.returncode == 0 and (out / "index.json").exists()
    (tree / "screens" / "09-bad.md").write_text("title: x\nstatus: nope\nslug: bad\n\nb\n")
    bad = subprocess.run(cmd + ["check", str(tree)], env=env, capture_output=True, text=True)
    assert bad.returncode == 1
    assert "status is 'nope'" in bad.stdout
    still = subprocess.run(
        cmd + ["build", str(tree), str(out)], env=env, capture_output=True, text=True
    )
    assert still.returncode == 0  # a broken file never stops the station


def test_a_preset_the_engine_would_refuse_is_an_error_card(tree):
    """The engine's patch format is the one source of truth (sxpatch): the content tool runs
    the engine's own check, so a preset rigd would refuse never reaches the Play strip."""
    f = tree / "presets" / "sample-drone.patch.json"
    doc = json.loads(f.read_text())
    doc["cables"].append(["nowhere.out", "out.r"])  # a module that does not exist
    f.write_text(json.dumps(doc, indent=2))
    index = index_of(tree)
    errs = [e for e in errors(index) if "sample-drone.patch.json" in e]
    assert errs, errors(index)
    assert entry(index, "presets", "sample-drone").get("error_card")
