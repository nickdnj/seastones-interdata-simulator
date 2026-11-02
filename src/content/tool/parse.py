"""Parse the station's content files (CT-01, CONT-1, CONT-2, CONT-6; ADR-007).

Ported from the Model 4 kiosk's ``src/content/tool/parse.py`` (the museum's
separate Model 4 kiosk project). The forgiving reader, the flat header, the small
body grammar and the plain-English ``Problem`` are kept as they were, because the same
museum staff edit both kiosks. What changed: one ``Doc`` type serves every collection
(screens, captions, code notes, presets, passages, rig data) instead of Model 4's screens
only, and the Model 4 template list is gone (the Seastones layouts are UX's, CT-03).

A file is a flat ``key: value`` header, a blank line, then the body. Deliberately not YAML
and not JSON (Model 4 A-11): no nesting, no lists, no quoting, no significant indentation.
This module is the only content parser. The page never parses content; it reads the
``index.json`` that ``index.py`` writes.

Standard library only.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# The collections and what a staff editor may write in each header
# --------------------------------------------------------------------------

#: Folder -> (required keys, optional keys). Keys outside both are a warning, not an
#: error: an unknown key never stops the station (CONT-6), but staff should know.
COLLECTIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "screens": (
        ("title", "slug", "status"),
        ("eyebrow", "template", "image", "image_caption", "slots", "claim", "note", "layer"),
    ),
    "captions": (("status",), ("title", "slots", "claim", "note", "layer")),
    "code": (("title", "status"), ("block", "slots", "claim", "note")),
    "presets": (("title", "status"), ("ledger", "slots", "claim", "note", "voices", "auth")),
    "passages": (("title", "status"), ("ledger", "label_slot", "slots", "claim", "note")),
    "rig": ((), ("title", "status", "ledger", "note")),
}

#: Collections whose items come in a pair: the words in ``<slug>.md`` and the machine
#: half beside it (ADR-007).
PAIRS = {"presets": ".patch.json", "passages": ".score"}

#: Header keys that are staff-facing drafting metadata and must never be rendered.
STAFF_KEYS = ("claim", "note", "ledger")

VALID_STATUS = ("ready", "draft-hidden")
VALID_CLAIM = ("confirmed", "unconfirmed", "withheld")
VALID_SLOT_KIND = ("claim", "media", "passage", "preset")

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Junk a Mac or a Windows box drops on a USB stick. Never a content file.
JUNK_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".Spotlight-V100",
    ".Trashes",
    ".fseventsd",
    ".TemporaryItems",
}
JUNK_PREFIXES = ("._", "~$")

#: Curly punctuation a word processor produces, and the straight version we want.
SMART_CHARS = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "′": "'",
    "″": '"',
    " ": " ",  # non-breaking space
}

_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_CARD_RE = re.compile(r"^##\s+(.*)$")
_HIGHLIGHT_RE = re.compile(r"\s*\[highlight\]\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|?$")
_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ɏ][0-9A-Za-zÀ-ɏ'’/.,$-]*")

#: Fields a card may carry as ``key: value``, mirroring the header's own syntax.
CARD_FIELDS = ("meta", "stat", "text")


# --------------------------------------------------------------------------
# Problems
# --------------------------------------------------------------------------


@dataclass
class Problem:
    """One thing wrong, said in a sentence a museum staffer can act on.

    ``message`` is the sentence; ``hint`` says what to type. Never a stack trace, never a
    Python type name.
    """

    level: str  # "error" or "warning"
    rule: str  # short machine id, e.g. "status-not-valid"
    message: str
    file: str | None = None  # path relative to the content directory's parent
    line: int | None = None
    slug: str | None = None
    hint: str | None = None

    @property
    def is_error(self) -> bool:
        return self.level == "error"

    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}, line {self.line}"
        return self.file or ""

    def format(self) -> str:
        where = self.location()
        return f"{where}: {self.message}" if where else self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "slug": self.slug,
            "message": self.message,
            "hint": self.hint,
            "text": self.format(),
        }


def error(rule: str, message: str, **kw: Any) -> Problem:
    return Problem("error", rule, message, **kw)


def warning(rule: str, message: str, **kw: Any) -> Problem:
    return Problem("warning", rule, message, **kw)


# --------------------------------------------------------------------------
# One content file, read
# --------------------------------------------------------------------------


@dataclass
class Doc:
    """One content file. ``header`` holds the raw strings as typed; ``blocks`` is the
    body in the shapes the page renders."""

    collection: str
    file: str
    header: dict[str, str] = field(default_factory=dict)
    header_lines: dict[str, int] = field(default_factory=dict)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    body_start_line: int = 0
    problems: list[Problem] = field(default_factory=list)
    fatal: Problem | None = None  # could not be read at all
    pair_file: str | None = None  # presets and passages: the machine half

    @property
    def slug(self) -> str:
        explicit = self.header.get("slug", "").strip()
        return explicit or slug_from_filename(self.file)

    @property
    def title(self) -> str:
        return self.header.get("title", "").strip()

    @property
    def status(self) -> str:
        return self.header.get("status", "").strip()

    @property
    def hidden(self) -> bool:
        return self.status != "ready"

    @property
    def number(self) -> int | None:
        m = re.match(r"^(\d+)-", os.path.basename(self.file))
        return int(m.group(1)) if m else None

    def list_of(self, key: str) -> list[str]:
        return [s.strip() for s in self.header.get(key, "").split(",") if s.strip()]

    def visitor_text(self) -> str:
        """Every word that can reach the glass."""
        parts = [self.title] if self.title else []
        for key in ("eyebrow", "image_caption"):
            if self.header.get(key):
                parts.append(self.header[key])
        parts.extend(block_text(self.blocks))
        return "\n".join(parts)

    def prose_words(self) -> int:
        total = 0
        for block in walk_blocks(self.blocks):
            if block["type"] == "paragraph":
                total += count_words(block["text"])
            elif block["type"] == "bullets":
                total += sum(count_words(item) for item in block["items"])
        return total


def slug_from_filename(path: str) -> str:
    base = os.path.basename(path)
    base = re.sub(r"\.md$", "", base, flags=re.IGNORECASE)
    return re.sub(r"^\d+-", "", base) or base


def walk_blocks(blocks: list[dict[str, Any]]):
    for block in blocks:
        yield block
        if block["type"] == "cards":
            for card in block["items"]:
                yield from walk_blocks(card.get("blocks", []))


def block_text(blocks: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "paragraph":
            out.append(block["text"])
        elif kind == "bullets":
            out.extend(block["items"])
        elif kind == "table":
            out.extend(block["headers"])
            for row in block["rows"]:
                out.extend(row)
        elif kind == "cards":
            for card in block["items"]:
                out.append(card["title"])
                out.extend(card[f] for f in CARD_FIELDS if card.get(f))
                out.extend(block_text(card.get("blocks", [])))
    return out


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


# --------------------------------------------------------------------------
# Reading the bytes a staff editor actually saved (ported unchanged in behaviour)
# --------------------------------------------------------------------------


def read_text(path: str, rel: str) -> tuple[str, list[Problem]]:
    """Read forgivingly: a byte-order mark, CRLF and CR line endings, trailing spaces and
    curly quotes are all made harmless. Non-UTF-8 bytes are an error, but the file is
    still read with replacement characters so the rest of it can be checked."""
    problems: list[Problem] = []
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        problems.append(
            error(
                "not-utf8",
                "this file has characters that aren't plain text. Re-save it from your "
                "editor as UTF-8 (in TextEdit: Format, then Make Plain Text).",
                file=rel,
            )
        )
    text, more = normalise(text, rel)
    return text, problems + more


def normalise(text: str, rel: str) -> tuple[str, list[Problem]]:
    problems: list[Problem] = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    flagged: set[int] = set()
    for number, line in enumerate(text.split("\n"), start=1):
        if number not in flagged and any(ch in SMART_CHARS for ch in line):
            flagged.add(number)
            problems.append(
                warning(
                    "smart-quotes",
                    "this line has curly quotes or a non-breaking space, the kind a word "
                    "processor inserts. They have been straightened for the screen, but "
                    "please use straight quotes (' and \") in the file.",
                    file=rel,
                    line=number,
                    hint="Retype the quote marks in a plain-text editor.",
                )
            )
    for curly, straight in SMART_CHARS.items():
        text = text.replace(curly, straight)
    return "\n".join(line.rstrip() for line in text.split("\n")), problems


def is_junk(name: str) -> bool:
    return name in JUNK_NAMES or any(name.startswith(p) for p in JUNK_PREFIXES)


# --------------------------------------------------------------------------
# Header and body (ported)
# --------------------------------------------------------------------------


def parse_header(
    lines: list[str], rel: str
) -> tuple[dict[str, str], dict[str, int], int, list[Problem]]:
    """Read ``key: value`` lines up to the first blank line."""
    header: dict[str, str] = {}
    at: dict[str, int] = {}
    problems: list[Problem] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            break
        match = _HEADER_RE.match(line)
        if not match:
            problems.append(
                error(
                    "header-line-unreadable",
                    "this line is in the header but isn't written as 'something: a value'. "
                    "If the body copy starts here, put a blank line above it.",
                    file=rel,
                    line=i + 1,
                    hint="The header is the block at the top. A blank line ends it.",
                )
            )
            i += 1
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if key in header:
            problems.append(
                error(
                    "header-key-repeated",
                    f"'{key}' is set twice in this file. Delete one of them.",
                    file=rel,
                    line=i + 1,
                )
            )
        else:
            header[key] = value
            at[key] = i + 1
        i += 1
    return header, at, i, problems


def parse_body(
    lines: list[str], offset: int, rel: str
) -> tuple[list[dict[str, Any]], list[Problem]]:
    """The whole grammar, kept small:

    plain lines   a paragraph
    - a line      a bullet (a run of them is one list)
    | a | b |     a table row (the first row is the headings)
    ## A title    starts a card; cards side by side make a row
    ---           ends the row of cards
    """
    blocks: list[dict[str, Any]] = []
    problems: list[Problem] = []
    i, n = 0, len(lines)

    def line_no(idx: int) -> int:
        return offset + idx + 1

    while i < n:
        line = lines[i].strip()
        if line in ("", "---"):
            i += 1
            continue
        if _CARD_RE.match(line):
            cards: list[dict[str, Any]] = []
            start = line_no(i)
            while i < n:
                line = lines[i].strip()
                if line == "---":
                    i += 1
                    break
                m = _CARD_RE.match(line)
                if not m:
                    if line == "":
                        i += 1
                        continue
                    break
                title = m.group(1).strip()
                highlight = bool(_HIGHLIGHT_RE.search(title))
                if highlight:
                    title = _HIGHLIGHT_RE.sub("", title).strip()
                card: dict[str, Any] = {"title": title, "highlight": highlight, "line": line_no(i)}
                i += 1
                inner: list[str] = []
                while i < n:
                    peek = lines[i].strip()
                    if peek == "---" or _CARD_RE.match(peek):
                        break
                    inner.append(lines[i])
                    i += 1
                fields, inner_blocks, inner_problems = _parse_card_inner(
                    inner, offset + (i - len(inner)), rel
                )
                card.update(fields)
                card["blocks"] = inner_blocks
                problems.extend(inner_problems)
                cards.append(card)
            blocks.append({"type": "cards", "items": cards, "line": start})
            continue
        if line.startswith("|"):
            start = line_no(i)
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                row_text = lines[i].strip()
                if not _TABLE_SEP_RE.match(row_text):
                    rows.append(_split_row(row_text))
                i += 1
            if not rows:
                continue
            headers, body_rows = rows[0], rows[1:]
            widths = {len(r) for r in body_rows}
            if widths and widths != {len(headers)}:
                problems.append(
                    error(
                        "table-ragged",
                        f"this table's heading row has {len(headers)} columns but at least "
                        "one row underneath has a different number. Every row needs the "
                        "same number of | bars.",
                        file=rel,
                        line=start,
                    )
                )
            blocks.append({"type": "table", "headers": headers, "rows": body_rows, "line": start})
            continue
        if _BULLET_RE.match(line):
            start = line_no(i)
            items: list[str] = []
            while i < n and _BULLET_RE.match(lines[i].strip()):
                items.append(_BULLET_RE.match(lines[i].strip()).group(1).strip())
                i += 1
            blocks.append({"type": "bullets", "items": items, "line": start})
            continue
        start = line_no(i)
        parts: list[str] = []
        while i < n:
            peek = lines[i].strip()
            if peek in ("", "---") or peek.startswith("|"):
                break
            if _CARD_RE.match(peek) or _BULLET_RE.match(peek):
                break
            parts.append(peek)
            i += 1
        blocks.append({"type": "paragraph", "text": " ".join(parts), "line": start})
    return blocks, problems


def _parse_card_inner(
    lines: list[str], offset: int, rel: str
) -> tuple[dict[str, str], list[dict[str, Any]], list[Problem]]:
    fields: dict[str, str] = {}
    leftover: list[str] = []
    problems: list[Problem] = []
    for idx, raw in enumerate(lines):
        match = _HEADER_RE.match(raw.strip())
        if match and match.group(1).strip().lower() in CARD_FIELDS:
            key = match.group(1).strip().lower()
            if key in fields:
                problems.append(
                    error(
                        "card-field-repeated",
                        f"this card sets '{key}' twice. Delete one of them.",
                        file=rel,
                        line=offset + idx + 1,
                    )
                )
            else:
                fields[key] = match.group(2).strip()
            leftover.append("")
        else:
            leftover.append(raw)
    inner_blocks, inner_problems = parse_body(leftover, offset, rel)
    return fields, inner_blocks, problems + inner_problems


def _split_row(row: str) -> list[str]:
    cells = row.split("|")
    if cells and cells[0].strip() == "":
        cells = cells[1:]
    if cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def parse_doc_text(text: str, collection: str, rel: str) -> Doc:
    text, problems = normalise(text, rel)
    lines = text.split("\n")
    header, at, body_offset, header_problems = parse_header(lines, rel)
    blocks, body_problems = parse_body(lines[body_offset:], body_offset, rel)
    return Doc(
        collection=collection,
        file=rel,
        header=header,
        header_lines=at,
        blocks=blocks,
        body_start_line=body_offset + 1,
        problems=problems + header_problems + body_problems,
    )


def parse_doc_file(path: str, collection: str, rel: str) -> Doc:
    """Read and parse one content file. Never raises for a content mistake."""
    try:
        text, read_problems = read_text(path, rel)
    except OSError as exc:
        doc = Doc(collection=collection, file=rel)
        doc.fatal = error(
            "file-unreadable",
            f"this file could not be read ({exc.strerror or 'unknown reason'}). Check it "
            "is still on the stick and not open in another program.",
            file=rel,
        )
        doc.problems.append(doc.fatal)
        return doc
    # read_text has already normalised, so this second pass reports nothing new.
    doc = parse_doc_text(text, collection, rel)
    doc.problems = read_problems + doc.problems
    return doc


# --------------------------------------------------------------------------
# kiosk.conf and slots.md (ported; slots extended for CONT-2)
# --------------------------------------------------------------------------


def parse_conf(path: str, rel: str) -> tuple[dict[str, str], list[Problem]]:
    """``kiosk.conf``: the same flat format, accepting ``key = value`` too."""
    conf: dict[str, str] = {}
    if not os.path.exists(path):
        return conf, []
    text, problems = read_text(path, rel)
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and (":" not in line or line.index("=") < line.index(":")):
            key, _, value = line.partition("=")
        else:
            key, _, value = line.partition(":")
        key = key.strip().lower()
        if not key:
            problems.append(
                warning(
                    "conf-line-unreadable",
                    "this line isn't written as 'setting = value' and was skipped.",
                    file=rel,
                    line=number,
                )
            )
            continue
        conf[key] = value.strip()
    return conf, problems


SLOT_FIELDS = ("status", "kind", "claim", "source", "owner", "screen", "note", "draft", "tags")


@dataclass
class Slot:
    """One named slot: a claim, a picture, a passage or a preset (CONT-2)."""

    slot_id: str
    status: str = ""
    kind: str = "claim"
    claim: str = ""
    source: str = ""
    owner: str = ""
    screen: str = ""
    note: str = ""
    draft: str = ""
    tags: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.slot_id,
            "status": self.status,
            "kind": self.kind,
            "claim": self.claim,
            "tags": [t.strip() for t in self.tags.split(",") if t.strip()],
        }


def parse_slots(path: str, rel: str) -> tuple[dict[str, Slot], list[Problem]]:
    """``slots.md``: one ``## slot-id`` card per slot."""
    slots: dict[str, Slot] = {}
    if not os.path.exists(path):
        return slots, [
            error(
                "slots-file-missing",
                "content/slots.md is missing. Every item that names a slot needs it "
                "declared there.",
                file=rel,
            )
        ]
    text, problems = read_text(path, rel)
    current: Slot | None = None
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        match = _CARD_RE.match(line)
        if match:
            slot_id = match.group(1).strip()
            if slot_id in slots:
                problems.append(
                    error(
                        "slot-declared-twice",
                        f"slot '{slot_id}' is declared twice in slots.md. Keep one block "
                        "and delete the other.",
                        file=rel,
                        line=number,
                    )
                )
            current = Slot(slot_id=slot_id, line=number)
            slots[slot_id] = current
            continue
        if current is None or not line or line.startswith("#"):
            continue
        field_match = _HEADER_RE.match(line)
        if field_match and field_match.group(1).strip().lower() in SLOT_FIELDS:
            setattr(current, field_match.group(1).strip().lower(), field_match.group(2).strip())
    return slots, problems


# --------------------------------------------------------------------------
# A whole content directory
# --------------------------------------------------------------------------


@dataclass
class Bundle:
    """Everything in one ``content/`` directory (or one content stick), read once."""

    root: str
    display_root: str = "content"
    docs: dict[str, list[Doc]] = field(default_factory=dict)
    slots: dict[str, Slot] = field(default_factory=dict)
    conf: dict[str, str] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)  # lowercased name -> real name
    problems: list[Problem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def all_problems(self) -> list[Problem]:
        out = list(self.problems)
        for docs in self.docs.values():
            for doc in docs:
                out.extend(doc.problems)
        return out


def load_content_dir(root: str, display_root: str | None = None) -> Bundle:
    """Read every collection, the slots, the config and the image list. Never raises for
    a content mistake: a missing folder, a junk file or an unreadable file all come back
    as problems on the bundle."""
    display_root = display_root or os.path.basename(os.path.normpath(root)) or "content"
    bundle = Bundle(root=root, display_root=display_root)
    if not os.path.isdir(root):
        bundle.problems.append(
            error(
                "content-dir-missing",
                f"there is no content folder at {root}. The station needs a folder with "
                "kiosk.conf, slots.md and screens/ in it.",
            )
        )
        return bundle

    bundle.conf, more = parse_conf(os.path.join(root, "kiosk.conf"), f"{display_root}/kiosk.conf")
    bundle.problems.extend(more)
    bundle.slots, more = parse_slots(os.path.join(root, "slots.md"), f"{display_root}/slots.md")
    bundle.problems.extend(more)

    images_dir = os.path.join(root, "images")
    if os.path.isdir(images_dir):
        for name in sorted(os.listdir(images_dir)):
            if is_junk(name):
                bundle.skipped.append(f"{display_root}/images/{name}")
            else:
                bundle.images[name.lower()] = name

    for collection in COLLECTIONS:
        folder = os.path.join(root, collection)
        docs: list[Doc] = []
        bundle.docs[collection] = docs
        if not os.path.isdir(folder):
            if collection == "screens":
                bundle.problems.append(
                    error(
                        "screens-dir-missing",
                        f"there is no screens folder inside {display_root}. Every story "
                        "screen lives in a file there, named like 03-the-rig.md.",
                    )
                )
            continue
        names = sorted(os.listdir(folder))
        pair_ext = PAIRS.get(collection)
        for name in names:
            path = os.path.join(folder, name)
            rel = f"{display_root}/{collection}/{name}"
            if not os.path.isfile(path):
                continue
            if is_junk(name):
                bundle.skipped.append(rel)
                continue
            if pair_ext and name.endswith(pair_ext):
                continue  # the machine half; paired below
            if not name.lower().endswith(".md"):
                bundle.problems.append(
                    warning(
                        "not-markdown",
                        f"'{name}' is in the {collection} folder but doesn't end in .md"
                        + (f" or {pair_ext}" if pair_ext else "")
                        + ", so it was ignored.",
                        file=rel,
                    )
                )
                continue
            doc = parse_doc_file(path, collection, rel)
            if pair_ext:
                pair = os.path.join(folder, name[:-3] + pair_ext)
                if os.path.isfile(pair):
                    doc.pair_file = pair
            docs.append(doc)
        if pair_ext:
            words = {n[:-3] for n in names if n.lower().endswith(".md")}
            for name in names:
                if name.endswith(pair_ext) and name[: -len(pair_ext)] not in words:
                    bundle.problems.append(
                        error(
                            "pair-orphan",
                            f"'{name}' has no words file beside it. Add "
                            f"'{name[: -len(pair_ext)]}.md' with its title and status, or "
                            "remove it.",
                            file=f"{display_root}/{collection}/{name}",
                        )
                    )
        docs.sort(key=lambda d: (d.number is None, d.number or 0, d.file))
    return bundle
