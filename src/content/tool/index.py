"""Turn a content folder into the ``index.json`` the page reads (CT-01, CONT-6).

Ported from the Model 4 kiosk's indexer. The page never parses content; it fetches this
file, which holds every collection's items ready to render, the visitor order, the slots
and every problem.

A broken file never stops the station: it becomes an **error card** in its place, with the
museum's own wording from ``kiosk.conf`` (``content_error_headline``,
``content_error_body``), and everything else renders. Draft-hidden items are left out of the
visitor order but kept in the review order (CONT-3); passages are visitor-visible only when
``ready`` (SEA-3, ARCHITECTURE 11.4 rule 1).

Deterministic: same content, same bytes. No timestamps (DEV-PLAN 7.1).

The USB-or-baked fallback chain (CONT-7) is the runtime's job (CT-08); ``build`` takes the
source label as an argument.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .parse import STAFF_KEYS, Bundle, Doc, Problem, load_content_dir
from .validate import UNRENDERABLE_RULES, check_bundle

SCHEMA = "seastones.content-index/1"

#: Last resort only, for when even kiosk.conf is unreachable. The visitor-facing wording
#: lives in kiosk.conf like every other visitor word (CONT-1).
FALLBACK_ERROR_HEADLINE = "This part needs attention."
FALLBACK_ERROR_BODY = "Please tell a staff member. The rest of the rig works."

#: kiosk.conf keys never exported to the page.
PRIVATE_CONF_MARKERS = ("pin", "secret", "password", "token")


def _error_copy(conf: dict[str, str]) -> tuple[str, str]:
    return (
        conf.get("content_error_headline", "").strip() or FALLBACK_ERROR_HEADLINE,
        conf.get("content_error_body", "").strip() or FALLBACK_ERROR_BODY,
    )


def _entry(doc: Doc, problems: list[Problem], conf: dict[str, str], root: str) -> dict[str, Any]:
    own = [p for p in problems if p.file == doc.file]
    blocking = [p for p in own if p.is_error and p.rule in UNRENDERABLE_RULES]
    entry: dict[str, Any] = {
        "slug": doc.slug,
        "file": doc.file,
        "status": doc.status or None,
        "hidden": doc.hidden,
        "problems": [p.format() for p in own],
    }
    if blocking:
        headline, body = _error_copy(conf)
        entry.update(
            {
                "error_card": True,
                "title": headline,
                "blocks": [{"type": "paragraph", "text": body, "line": 0}],
                "staff": {"why": [p.format() for p in blocking]},
            }
        )
        return entry
    entry.update(
        {
            "error_card": False,
            "title": doc.title or None,
            "blocks": doc.blocks,
            "word_count": doc.prose_words(),
            "slots": doc.list_of("slots"),
            # Staff-only. Nothing under this key may ever be drawn on the glass.
            "staff": {k: (doc.header.get(k, "").strip() or None) for k in STAFF_KEYS},
        }
    )
    for key in ("eyebrow", "template", "layer", "image_caption", "block", "voices", "auth"):
        if doc.header.get(key, "").strip():
            entry[key] = doc.header[key].strip()
    if doc.header.get("image", "").strip():
        entry["image"] = f"images/{doc.header['image'].strip()}"
    if doc.collection == "passages":
        entry["label_slot"] = doc.header.get("label_slot", "").strip() or None
    if doc.pair_file:
        entry["pair"] = os.path.relpath(doc.pair_file, os.path.dirname(root)).replace(os.sep, "/")
    if doc.collection == "rig":
        entry["values"] = {
            k: v for k, v in doc.header.items() if k not in ("title", "status", "note", "ledger")
        }
    return entry


def build_index(bundle: Bundle, source: str = "usb") -> dict[str, Any]:
    problems = bundle.all_problems() + check_bundle(bundle)
    collections: dict[str, list[dict[str, Any]]] = {}
    order: dict[str, list[str]] = {}
    review_order: dict[str, list[str]] = {}
    for name, docs in bundle.docs.items():
        entries = [_entry(d, problems, bundle.conf, bundle.root) for d in docs]
        collections[name] = entries
        review_order[name] = [e["slug"] for e in entries]
        # A broken file whose status cannot be read stays in the visitor order as an
        # error card, so the gap is visible (CONT-6). Passages need an explicit ready.
        order[name] = [
            e["slug"]
            for e in entries
            if e["status"] == "ready"
            or (e["error_card"] and e["status"] is None and name != "passages")
        ]
    conf = {
        k: v
        for k, v in sorted(bundle.conf.items())
        if not any(m in k.lower() for m in PRIVATE_CONF_MARKERS)
    }
    errors = [p for p in problems if p.is_error]
    return {
        "schema": SCHEMA,
        "source": source,
        "conf": conf,
        "slots": {k: s.to_dict() for k, s in sorted(bundle.slots.items())},
        "collections": collections,
        "order": order,
        "review_order": review_order,
        "layer6_available": bool(order.get("passages")),
        "counts": {
            "errors": len(errors),
            "warnings": len(problems) - len(errors),
            "error_cards": sum(e["error_card"] for es in collections.values() for e in es),
        },
        "problems": [p.to_dict() for p in problems],
        "skipped": sorted(bundle.skipped),
    }


def dumps(index: dict[str, Any]) -> str:
    return json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def report(index: dict[str, Any]) -> str:
    lines = [
        f"content index ({index['schema']}), source: {index['source']}",
        f"{index['counts']['errors']} error(s), {index['counts']['warnings']} warning(s), "
        f"{index['counts']['error_cards']} error card(s)",
    ]
    for p in index["problems"]:
        lines.append(f"  {p['level'].upper():7} {p['text']}")
    return "\n".join(lines) + "\n"


def build(content_dir: str, out_dir: str, source: str = "usb") -> dict[str, Any]:
    """Index ``content_dir`` and write ``index.json`` and ``report.txt`` to ``out_dir``."""
    index = build_index(load_content_dir(content_dir), source)
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(dumps(index))
    os.replace(tmp, os.path.join(out_dir, "index.json"))  # atomic: the page never sees half
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write(report(index))
    return index
