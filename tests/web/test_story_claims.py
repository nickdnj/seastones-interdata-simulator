"""STORY-2 release check: no visitor-visible item uses a claim that is not at Tier 1 (CT-02, CT-10).

Every visitor-facing item binds the claims it makes to slots in content/slots.md. An item
the visitor can see (status ready, in the visitor order) may bind only slots that are
`confirmed` and `ready`. The unsourced drafts are kept, flagged, for Doug's review: they must
be `draft-hidden`, and each unconfirmed or withheld claim slot must be tagged `not-shippable`
or itself be draft-hidden. A planted violation must fail the check (QA: a gate that cannot
fail is not a gate).

This is the content half of the release gate (CT-05's scripts/release-gate.sh should call
`check()` or this test); the page half is tests/web/ui/story.spec.mjs.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTENT = os.path.join(ROOT, "content")
sys.path.insert(0, os.path.join(ROOT, "src"))

from content.tool.index import build_index  # noqa: E402
from content.tool.parse import load_content_dir  # noqa: E402

VISITOR_COLLECTIONS = ("screens", "captions", "code", "presets", "passages")


def check(content_dir: str) -> list[str]:
    """Every STORY-2 problem in a content folder, as plain sentences."""
    index = build_index(load_content_dir(content_dir), "check")
    slots = index["slots"]
    problems: list[str] = []
    for coll in VISITOR_COLLECTIONS:
        visible = set(index["order"].get(coll, []))
        for item in index["collections"].get(coll, []):
            bound = item.get("slots") or []
            for sid in bound:
                s = slots.get(sid)
                if s is None:
                    problems.append(
                        f"{item['file']}: names slot '{sid}', which slots.md does not declare"
                    )
                    continue
                shippable = s["claim"] == "confirmed" and s["status"] == "ready"
                if item["slug"] in visible and not item.get("error_card") and not shippable:
                    problems.append(
                        f"{item['file']}: a visitor screen uses claim '{sid}' ({s['claim']}, "
                        f"{s['status']}); it must not ship until the claim is confirmed and cited"
                    )
    for sid, s in slots.items():
        if s["kind"] in ("claim", "media") and s["claim"] in ("unconfirmed", "withheld"):
            if s["status"] != "draft-hidden":
                problems.append(
                    f"slots.md: '{sid}' is {s['claim']} but not draft-hidden; it cannot be ready until it is confirmed"
                )
    return problems


def test_the_shipped_content_passes_the_story_2_check():
    assert check(CONTENT) == []


def test_the_three_prd_claims_are_present_and_not_shippable():
    index = build_index(load_content_dir(CONTENT), "check")
    slots = index["slots"]
    for sid in ("claim-lesh-mid-show", "claim-716-16bit-core", "claim-hour-from-here"):
        assert slots[sid]["claim"] == "unconfirmed", sid
        assert slots[sid]["status"] == "draft-hidden", sid
        assert "not-shippable" in slots[sid]["tags"], sid
    # each is kept in a draft screen for review, never in the visitor order
    drafts = [s for s in index["collections"]["screens"] if s["status"] == "draft-hidden"]
    bound = {sid for s in drafts for sid in s["slots"]}
    assert {"claim-lesh-mid-show", "claim-716-16bit-core", "claim-hour-from-here"} <= bound
    assert not set(index["order"]["screens"]) & {s["slug"] for s in drafts}


def test_the_withheld_slots_exist():
    slots = build_index(load_content_dir(CONTENT), "check")["slots"]
    for sid in (
        "media-lagin-photographs",
        "media-lagin-quotation",
        "credit-line",
        "field-engineer-account",
        "corrected-channel-map",
    ):
        assert slots[sid]["claim"] == "withheld", sid


@pytest.mark.parametrize(
    "plant",
    [
        # a ready screen that uses an unconfirmed claim
        (
            "screens/02-seastones.md",
            "slots: claim-seastones-name, claim-live-1974",
            "slots: claim-seastones-name, claim-lesh-mid-show",
        ),
        # a draft flipped to ready without its claim being confirmed
        ("screens/94-interdata-draft.md", "status: draft-hidden", "status: ready"),
        # a claim quietly marked shippable
        (
            "slots.md",
            "status: draft-hidden\nclaim: unconfirmed\nsource: none yet (PRD 1.1",
            "status: ready\nclaim: unconfirmed\nsource: none yet (PRD 1.1",
        ),
    ],
)
def test_a_planted_violation_fails_the_check(tmp_path, plant):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT, dst)
    rel, old, new = plant
    f = dst / rel
    text = f.read_text(encoding="utf-8")
    assert old in text, rel
    f.write_text(text.replace(old, new, 1), encoding="utf-8")
    assert check(str(dst)) != []
