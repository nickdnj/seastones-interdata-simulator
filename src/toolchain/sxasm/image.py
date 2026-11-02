"""`seastones.image/1` and the other sxasm outputs (ARCHITECTURE 9.2, ASM-09, ASM-10).

    rig.img.json   the image: segments of halfwords, entry PC and PSW, SHA-256
    rig.sym        NAME VALUE, sorted
    rig.dep.sim    SCP deposit commands that load the image into stock id16 (ASM-10)
    rig.lst.json   the listing: per source line its address, words, text and *@block

The SHA-256 is over a canonical byte string, so any loader can recompute it: for each
segment in address order, the address and the word count as big-endian halfwords, then the
words big-endian. Everything is deterministic: no timestamps, no absolute paths.
"""

from __future__ import annotations

import hashlib
import json
import re

FORMAT = "seastones.image/1"
VERSION = "sxasm 0.1"


def segments_from(lines) -> list[dict]:
    """Contiguous runs of assembled words, in address order."""
    words: dict[int, int] = {}
    for ln in lines:
        for i, w in enumerate(ln.words):
            words[ln.addr + 2 * i] = w
    segs: list[dict] = []
    for a in sorted(words):
        if segs and segs[-1]["addr"] + 2 * len(segs[-1]["words"]) == a:
            segs[-1]["words"].append(words[a])
        else:
            segs.append({"addr": a, "words": [words[a]]})
    return segs


def digest(segs: list[dict]) -> str:
    h = hashlib.sha256()
    for s in sorted(segs, key=lambda s: s["addr"]):
        h.update(s["addr"].to_bytes(2, "big") + len(s["words"]).to_bytes(2, "big"))
        for w in s["words"]:
            h.update(w.to_bytes(2, "big"))
    return h.hexdigest()


def build(asm, name: str, sources: list[str], subset_name: str | None) -> dict[str, str]:
    segs = segments_from(asm.lines)
    entry = asm.entry if asm.entry is not None else (segs[0]["addr"] if segs else 0)
    image = {
        "format": FORMAT,
        "assembler": VERSION,
        "name": name,
        "sources": sources,
        "subset": subset_name,
        "entry_pc": f"{entry:04X}",
        "entry_psw": "0000",
        "segments": [
            {"addr": f"{s['addr']:04X}", "words": [f"{w:04X}" for w in s["words"]]} for s in segs
        ],
        "sha256": digest(segs),
    }
    sym = "".join(f"{k} {v:04X}\n" for k, v in sorted(asm.symbols.items()))
    dep = "".join(
        f"dep 0{s['addr'] + 2 * i:X} {w:04X}\n" for s in segs for i, w in enumerate(s["words"])
    )
    dep += f"dep pc {entry:X}\ndep psw 0\n"
    lst = {
        "format": "seastones.listing/1",
        "name": name,
        "image_sha256": image["sha256"],
        "lines": [
            {
                "file": ln.file,
                "line": ln.number,
                "addr": f"{ln.addr:04X}",
                "words": [f"{w:04X}" for w in ln.words],
                "text": ln.text,
                "block": ln.block,
            }
            for ln in asm.lines
            if ln.words or ln.label
        ],
    }
    return {
        f"{name}.img.json": json.dumps(image, indent=1, sort_keys=True) + "\n",
        f"{name}.sym": sym,
        f"{name}.dep.sim": dep,
        f"{name}.lst.json": json.dumps(lst, indent=1, sort_keys=True) + "\n",
    }


HEX4 = re.compile(r"^[0-9A-F]{4}$")


def validate(image: dict) -> list[str]:
    """Problems with an image against seastones.image/1; empty means valid (ASM-09)."""
    p = []
    if image.get("format") != FORMAT:
        p.append(f"format is {image.get('format')!r}, not {FORMAT}")
    for k in ("entry_pc", "entry_psw", "sha256", "segments"):
        if k not in image:
            p.append(f"missing {k}")
    if p:
        return p
    if not HEX4.match(image["entry_pc"]) or not HEX4.match(image["entry_psw"]):
        p.append("entry_pc and entry_psw must be four upper-case hex digits")
    segs = []
    end = -1
    for s in image["segments"]:
        if not HEX4.match(s.get("addr", "")) or int(s["addr"], 16) & 1:
            p.append(f"bad segment address {s.get('addr')!r}")
            continue
        if not s.get("words") or not all(HEX4.match(w) for w in s["words"]):
            p.append(f"segment {s['addr']}: words must be non-empty four-digit hex")
            continue
        a = int(s["addr"], 16)
        if a <= end:
            p.append(f"segment {s['addr']} overlaps or is out of order")
        end = a + 2 * len(s["words"]) - 1
        if end > 0xFFFF:
            p.append(f"segment {s['addr']} runs past X'FFFF'")
        segs.append({"addr": a, "words": [int(w, 16) for w in s["words"]]})
    if not p and digest(segs) != image["sha256"]:
        p.append("image_hash_mismatch: sha256 does not match the segments")
    return p
