"""Tables from data: the `TABLE name` directive (PO-01, PO-05; ARCHITECTURE 5.4, 6.3, 9.2).

The program's channel assignments and its pitch table are not written in the source. They are
generated at assembly from two rig data files, so a confirmed channel map from someone who worked on the original, or
a different converter, is a data edit plus a rebuild, never a code change (RETRO-1, MACH-3):

    channel-map file   which D/A channel or gate line each voice and modulation lane uses
    dac file           the converter model: word_bits, range_v, output_hz, strobe_hz

Both use the content format (ARCHITECTURE 11.2): a flat `key: value` header, a blank line, then
free text. `#` starts a comment in a value. Errors are plain English with the file and line.

Tables (`LABEL  TABLE  name` emits the words at LABEL):

    pitch           128 halfwords: note n -> the code for an IDEAL 16-bit converter at 1 V/oct
                    over 0 to range_v, 0 V at C0 (MIDI 12). The converter keeps its top
                    word_bits, so word_bits never changes this table (MACH-3).
    first-set-bit   256 bytes: for each row byte, the position of its first key (bit X'80' is
                    position 0); X'FF' for an empty row (ADR-009)
    last-set-bit    256 bytes: the position of its last key; X'FF' for an empty row
    channel-map     35 halfwords, CHANNEL_MAP_LAYOUT below

The channel-map layout is part of the program's contract (rig.s names each field with EQU).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MOD_LANES = ("cutoff", "resonance", "rate", "depth", "width", "detune", "level", "spare")
MAX_VOICES = 8

# offset (bytes) -> meaning; rig.s mirrors these as EQUs
CHANNEL_MAP_LAYOUT = {
    0: "voices: how many voices the program plays",
    2: "gate source: 0 = the gate latch, 1 = D/A channels",
    4: "8 halfwords: per voice, the D/A command byte X'80'+channel for its pitch",
    20: "8 halfwords: per voice, its gate: a latch byte mask (X'80' >> line) or a D/A command byte",
    36: "the D/A code for a gate that is on (gate_high_v)",
    38: "8 halfwords: the D/A command bytes for the lanes " + ", ".join(MOD_LANES),
    54: "8 halfwords: per voice, its latch mask inverted (X'FFFF' with the D/A gates)",
}
CHANNEL_MAP_WORDS = 35


class RigDataError(Exception):
    def __init__(self, file: str, line: int, msg: str):
        super().__init__(f"{file}:{line}: {msg}")
        self.file, self.line, self.msg = file, line, msg


@dataclass
class Header:
    file: str
    values: dict[str, str]
    lines: dict[str, int]

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def line(self, key: str) -> int:
        return self.lines.get(key, 1)

    def need(self, key: str) -> str:
        if key not in self.values:
            raise RigDataError(self.file, 1, f"the '{key}:' line is missing")
        return self.values[key]

    def number(self, key: str, lo: float, hi: float) -> float:
        v = self.need(key)
        try:
            x = float(v)
        except ValueError:
            raise RigDataError(
                self.file, self.line(key), f"'{key}' should be a number, not '{v}'"
            ) from None
        if not lo <= x <= hi:
            raise RigDataError(
                self.file, self.line(key), f"'{key}' is {v}; it must be from {lo:g} to {hi:g}"
            )
        return x

    def channels(self, key: str, count: int | None, hi: int = 15) -> list[int]:
        v = self.need(key)
        parts = v.split()
        out = []
        for p in parts:
            if not p.isdigit() or int(p) > hi:
                raise RigDataError(
                    self.file,
                    self.line(key),
                    f"'{key}' lists '{p}'; each entry must be a whole number from 0 to {hi}",
                )
            out.append(int(p))
        if count is not None and len(out) != count:
            raise RigDataError(
                self.file,
                self.line(key),
                f"'{key}' lists {len(out)} channel(s) but 'voices' says {count}",
            )
        return out


def read_header(path: Path) -> Header:
    """The key: value header of a content-format file, with line numbers."""
    name = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RigDataError(name, 1, f"cannot read the file ({e})") from None
    values: dict[str, str] = {}
    lines: dict[str, int] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            break  # the header ends at the first blank line
        body = raw.split("#", 1)[0].rstrip()
        if not body:
            continue
        m = re.fullmatch(r"([a-z_][a-z0-9_]*):\s*(.*)", body)
        if not m:
            raise RigDataError(name, n, f"expected 'key: value', found '{raw.strip()}'")
        key, val = m.group(1), m.group(2).strip()
        if key in values:
            raise RigDataError(name, n, f"'{key}' is given twice (first on line {lines[key]})")
        values[key], lines[key] = val, n
    return Header(name, values, lines)


@dataclass
class Dac:
    word_bits: int
    range_v: float
    output_hz: float
    strobe_hz: float


def read_dac(path: Path) -> Dac:
    h = read_header(path)
    bits = h.number("word_bits", 1, 16)
    if bits != int(bits):
        raise RigDataError(h.file, h.line("word_bits"), "'word_bits' must be a whole number")
    return Dac(
        int(bits),
        h.number("range_v", 0.5, 20.0),
        h.number("output_hz", 50.0, 20000.0),
        h.number("strobe_hz", 10.0, 48000.0),
    )


@dataclass
class ChannelMap:
    name: str
    voices: int
    gate_source: str  # "latch" | "dac"
    pitch: list[int]
    gate: list[int]
    gate_high_v: float
    lanes: dict[str, int]


def read_channel_map(path: Path) -> ChannelMap:
    h = read_header(path)
    name = h.need("map")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise RigDataError(h.file, h.line("map"), f"'map' should be a short slug, not '{name}'")
    voices = h.number("voices", 1, MAX_VOICES)
    if voices != int(voices):
        raise RigDataError(h.file, h.line("voices"), "'voices' must be a whole number")
    nv = int(voices)
    src = h.need("gates")
    if src not in ("latch", "dac"):
        raise RigDataError(
            h.file, h.line("gates"), f"'gates' must be 'latch' or 'dac', not '{src}'"
        )
    pitch = h.channels("pitch", nv)
    gate = h.channels("gate", nv, hi=7 if src == "latch" else 15)
    high = h.number("gate_high_v", 2.6, 10.0) if src == "dac" else 5.0
    lanes = {k: h.channels(k, 1)[0] for k in MOD_LANES}
    used: dict[int, str] = {}

    def claim(ch: int, what: str, key: str) -> None:
        if ch in used:
            raise RigDataError(
                h.file, h.line(key), f"D/A channel {ch} is used twice: {used[ch]} and {what}"
            )
        used[ch] = what

    for i, ch in enumerate(pitch):
        claim(ch, f"pitch of voice {i + 1}", "pitch")
    if src == "dac":
        for i, ch in enumerate(gate):
            claim(ch, f"gate of voice {i + 1}", "gate")
    elif len(set(gate)) != len(gate):
        raise RigDataError(h.file, h.line("gate"), "two voices share a gate line")
    for k, ch in lanes.items():
        claim(ch, f"the {k} lane", k)
    return ChannelMap(name, nv, src, pitch, gate, high, lanes)


def pitch_code(note: int, range_v: float) -> int:
    code = round((note - 12) / 12 * 65536 / range_v)
    return max(0, min(0xFFFF, code))


def volts_code(volts: float, range_v: float) -> int:
    return max(0, min(0xFFFF, round(volts * 65536 / range_v)))


def _first(b: int) -> int:
    return next((i for i in range(8) if b & (0x80 >> i)), 0xFF)


def _last(b: int) -> int:
    return next((i for i in range(7, -1, -1) if b & (0x80 >> i)), 0xFF)


def _bytes_to_words(bs: list[int]) -> list[int]:
    return [(bs[i] << 8) | bs[i + 1] for i in range(0, len(bs), 2)]


def channel_map_words(m: ChannelMap, dac: Dac) -> list[int]:
    words = [m.voices, 1 if m.gate_source == "dac" else 0]
    words += [0x80 | m.pitch[i] if i < m.voices else 0 for i in range(MAX_VOICES)]
    for i in range(MAX_VOICES):
        if i >= m.voices:
            words.append(0)
        elif m.gate_source == "latch":
            words.append(0x80 >> m.gate[i])
        else:
            words.append(0x80 | m.gate[i])
    words.append(volts_code(m.gate_high_v, dac.range_v))
    words += [0x80 | m.lanes[k] for k in MOD_LANES]
    for i in range(MAX_VOICES):
        if i < m.voices and m.gate_source == "latch":
            words.append(0xFFFF ^ (0x80 >> m.gate[i]))
        else:
            words.append(0xFFFF)
    assert len(words) == CHANNEL_MAP_WORDS
    return words


class RigTables:
    """The TABLE provider: the rig data an image is built for."""

    def __init__(self, channel_map: Path, dac: Path):
        self.map = read_channel_map(channel_map)
        self.dac = read_dac(dac)

    def words(self, name: str) -> list[int] | None:
        if name == "pitch":
            return [pitch_code(n, self.dac.range_v) for n in range(128)]
        if name == "first-set-bit":
            return _bytes_to_words([_first(b) for b in range(256)])
        if name == "last-set-bit":
            return _bytes_to_words([_last(b) for b in range(256)])
        if name == "channel-map":
            return channel_map_words(self.map, self.dac)
        return None


NAMES = ("pitch", "first-set-bit", "last-set-bit", "channel-map")
