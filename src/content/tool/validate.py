"""Structural checks on a content bundle (CT-01; CONT-2, CONT-6; ADR-007).

The rules here are the ones the indexer needs to draw the station safely: required keys,
status and claim values, slugs, slot references, the preset and passage pairs. The editorial
rules (banned phrasings, word limits, reading level, required phrasings, claims and ledger
labels) are CT-03, CT-04, CT-05 and CT-13, and are added to this module by those issues.

Every problem is a sentence a museum staffer can act on, with the file and line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .parse import (
    COLLECTIONS,
    SLUG_RE,
    VALID_CLAIM,
    VALID_SLOT_KIND,
    VALID_STATUS,
    Bundle,
    Doc,
    Problem,
    error,
    warning,
)

PATCH_SCHEMA = "seastones.patch/1"

#: Problems that stop an item being drawn. It becomes an error card; everything else
#: is reported but still renders (an editorial slip never blanks a screen).
UNRENDERABLE_RULES = {
    "file-unreadable",
    "not-utf8",
    "missing-required-key",
    "header-line-unreadable",
    "duplicate-slug",
    "slug-shape",
    "status-not-valid",
    "pair-missing",
    "patch-unreadable",
    "patch-invalid",
    "score-invalid",
}


def _sxpatch_check():
    """The engine's own patch validator (src/toolchain/sxpatch), the single source of truth
    for the patch format. None where the toolchain is not installed beside the content tool:
    then only the schema name is checked here, and rigd refuses a bad patch at load."""
    import sys  # noqa: PLC0415

    toolchain = Path(__file__).resolve().parents[2] / "toolchain"
    if toolchain.is_dir() and str(toolchain) not in sys.path:
        sys.path.insert(0, str(toolchain))
    try:
        from sxpatch import check  # noqa: PLC0415
    except ImportError:
        return None
    return check


def check_doc(doc: Doc, bundle: Bundle) -> list[Problem]:
    out: list[Problem] = []
    if doc.fatal:
        return out
    required, optional = COLLECTIONS[doc.collection]
    rel, slug = doc.file, doc.slug
    for key in required:
        if not doc.header.get(key, "").strip():
            out.append(
                error(
                    "missing-required-key",
                    f"this file needs a '{key}:' line in its header.",
                    file=rel,
                    slug=slug,
                    hint=f"Add a line like '{key}: ...' at the top, above the blank line.",
                )
            )
    known = set(required) | set(optional)
    for key, line in doc.header_lines.items():
        if key not in known:
            out.append(
                warning(
                    "unknown-key",
                    f"'{key}' isn't a setting {doc.collection} files use, so it is ignored. "
                    f"Check the spelling. Known: {', '.join(sorted(known))}.",
                    file=rel,
                    line=line,
                    slug=slug,
                )
            )
    status = doc.status
    if status and status not in VALID_STATUS:
        out.append(
            error(
                "status-not-valid",
                f"status is '{status}', but it must be 'ready' (shows on the floor) or "
                "'draft-hidden' (review mode only).",
                file=rel,
                line=doc.header_lines.get("status"),
                slug=slug,
            )
        )
    claim = doc.header.get("claim", "").strip()
    if claim and claim not in VALID_CLAIM:
        out.append(
            error(
                "claim-not-valid",
                f"claim is '{claim}', but it must be confirmed, unconfirmed or withheld.",
                file=rel,
                line=doc.header_lines.get("claim"),
                slug=slug,
            )
        )
    if doc.collection == "screens" and doc.header.get("slug") and not SLUG_RE.match(slug):
        out.append(
            error(
                "slug-shape",
                f"slug '{slug}' must be lower-case words joined by hyphens, like 'the-rig'.",
                file=rel,
                line=doc.header_lines.get("slug"),
                slug=slug,
            )
        )
    for slot_key in ("slots", "label_slot"):
        for slot_id in doc.list_of(slot_key):
            if slot_id not in bundle.slots:
                out.append(
                    error(
                        "slot-unknown",
                        f"this file names slot '{slot_id}', which isn't declared in "
                        "slots.md. Add it there or fix the spelling.",
                        file=rel,
                        line=doc.header_lines.get(slot_key),
                        slug=slug,
                    )
                )
    image = doc.header.get("image", "").strip()
    if image and image.lower() not in bundle.images:
        out.append(
            warning(
                "image-missing",
                f"the picture '{image}' isn't in the images folder, so the screen shows "
                "without it.",
                file=rel,
                line=doc.header_lines.get("image"),
                slug=slug,
            )
        )
    if doc.collection == "presets":
        out.extend(_check_patch(doc))
    if doc.collection == "passages":
        out.extend(_check_passage(doc))
    return out


def _check_patch(doc: Doc) -> list[Problem]:
    if doc.pair_file is None:
        return [
            error(
                "pair-missing",
                f"this preset has no patch file beside it. Add '{doc.slug}.patch.json' "
                "(saved from the staff screen) or remove the preset.",
                file=doc.file,
                slug=doc.slug,
            )
        ]
    try:
        graph = json.loads(Path(doc.pair_file).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [
            error(
                "patch-unreadable",
                f"the patch file {os.path.basename(doc.pair_file)} could not be read: it "
                "is damaged or not plain text. Save it again from the staff screen.",
                file=doc.file,
                slug=doc.slug,
            )
        ]
    if not isinstance(graph, dict) or graph.get("schema") != PATCH_SCHEMA:
        return [
            error(
                "patch-unreadable",
                f"the patch file {os.path.basename(doc.pair_file)} isn't a "
                f"{PATCH_SCHEMA} patch. Save it again from the staff screen.",
                file=doc.file,
                slug=doc.slug,
            )
        ]
    check = _sxpatch_check()
    if check is None:
        return []
    text = Path(doc.pair_file).read_text(encoding="utf-8")
    problems, _ = check(graph, text, os.path.basename(doc.pair_file))
    out: list[Problem] = []
    for p in problems:
        if p.level == "error":
            out.append(
                error(
                    "patch-invalid",
                    f"{os.path.basename(doc.pair_file)} line {p.line}: {p.msg}",
                    file=doc.file,
                    slug=doc.slug,
                )
            )
        elif p.level == "warning":
            out.append(
                warning(
                    "patch-invalid",
                    f"{os.path.basename(doc.pair_file)} line {p.line}: {p.msg}",
                    file=doc.file,
                    slug=doc.slug,
                )
            )
    return out


def _check_passage(doc: Doc) -> list[Problem]:
    out: list[Problem] = []
    if doc.pair_file is None:
        return [
            error(
                "pair-missing",
                f"this passage has no score beside it. Add '{doc.slug}.score' or remove "
                "the passage.",
                file=doc.file,
                slug=doc.slug,
            )
        ]
    from toolchain.sxscore.validate import validate_file  # src/ is on the path

    for p in validate_file(Path(doc.pair_file)):
        out.append(
            error(
                "score-invalid",
                f"the score {os.path.basename(doc.pair_file)} has a problem: {p.message}",
                file=doc.file,
                line=None,
                slug=doc.slug,
                hint=f"line {p.line} of the score" if p.line else None,
            )
        )
    if doc.status == "ready":
        if not doc.list_of("ledger"):
            out.append(
                error(
                    "passage-ready-without-ledger",
                    "a passage that is 'ready' needs a 'ledger:' line naming the research "
                    "entries it rests on.",
                    file=doc.file,
                    slug=doc.slug,
                )
            )
        out.append(
            warning(
                "passage-ready-rights",
                "this passage is 'ready', so it would play on the floor. Switching a "
                "passage on is a rights decision (Doug's, with written permission), not "
                "an edit. In v1 every passage stays 'draft-hidden'.",
                file=doc.file,
                line=doc.header_lines.get("status"),
                slug=doc.slug,
            )
        )
    return out


def check_bundle(bundle: Bundle) -> list[Problem]:
    """Cross-file and per-file checks. Appends nothing to the bundle; returns problems."""
    out: list[Problem] = []
    for collection, docs in bundle.docs.items():
        seen: dict[str, str] = {}
        for doc in docs:
            if doc.fatal:
                continue
            if doc.slug in seen:
                out.append(
                    error(
                        "duplicate-slug",
                        f"two {collection} files use the slug '{doc.slug}' (the other is "
                        f"{seen[doc.slug]}). Each one needs its own.",
                        file=doc.file,
                        slug=doc.slug,
                    )
                )
            else:
                seen[doc.slug] = doc.file
            out.extend(check_doc(doc, bundle))
    rel = f"{bundle.display_root}/slots.md"
    for slot in bundle.slots.values():
        if slot.status and slot.status not in VALID_STATUS:
            out.append(
                error(
                    "slot-status-not-valid",
                    f"slot '{slot.slot_id}' has status '{slot.status}'; use ready or draft-hidden.",
                    file=rel,
                    line=slot.line,
                )
            )
        if slot.kind and slot.kind not in VALID_SLOT_KIND:
            out.append(
                error(
                    "slot-kind-not-valid",
                    f"slot '{slot.slot_id}' has kind '{slot.kind}'; use "
                    f"{', '.join(VALID_SLOT_KIND)}.",
                    file=rel,
                    line=slot.line,
                )
            )
        if slot.claim and slot.claim not in VALID_CLAIM:
            out.append(
                error(
                    "slot-claim-not-valid",
                    f"slot '{slot.slot_id}' has claim '{slot.claim}'; use confirmed, "
                    "unconfirmed or withheld.",
                    file=rel,
                    line=slot.line,
                )
            )
    for key in ("content_error_headline", "content_error_body"):
        if not bundle.conf.get(key):
            out.append(
                warning(
                    "conf-missing-error-copy",
                    f"kiosk.conf has no '{key}', so a broken item shows the built-in "
                    "fallback words. Add the museum's own wording (CONT-1).",
                    file=f"{bundle.display_root}/kiosk.conf",
                )
            )
    return out
