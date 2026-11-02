"""sxasm: a two-pass assembler for the Interdata 7/16 portable subset (ADR-004, VS-07).

Source follows Interdata CAL conventions:

    LABEL  OPC   R1,ADDR(RX)      comment after the operands
    * a comment line              *@block name   starts a code-view block (CODE-1)

* A label starts in column 1. The opcode and operands are separated by blanks; operands
  contain no blanks except inside C'..'.
* Numbers are decimal; X'1F' is hexadecimal, C'AB' is characters (high byte first), `*` is
  the current location. Expressions combine terms with + and -.
* Registers are written R0-R15 or as a number or symbol 0-15.
* Directives: ORG expr, label EQU expr, DC (X'..', C'..', H'..', or expressions; each a
  halfword, C'..' padded to even), DS n (n bytes), TABLE name (words generated from the rig
  data, tables.py; PO-01), END [entry].
* With `require_blocks`, every instruction, DC, DS and TABLE must sit inside a `*@block`
  (CODE-2: the code view shows every word under a named block); the CLI requires it.

Mnemonics, opcodes and operand forms come from SIMH's own table (opcodes.py). Output is
deterministic: no timestamps, no paths, sorted symbols.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .opcodes import Op, by_name, canonical


class SxasmError(Exception):
    def __init__(self, file: str, line: int, msg: str):
        super().__init__(f"{file}:{line}: {msg}")
        self.file, self.line, self.msg = file, line, msg


@dataclass
class Line:
    file: str
    number: int
    text: str
    label: str | None = None
    opc: str | None = None
    operands: str = ""
    addr: int = 0
    words: list[int] = field(default_factory=list)
    block: str | None = None


TOKEN = re.compile(r"\s*(X'[0-9A-Fa-f]+'|C'[^']*'|[A-Za-z_@$#][A-Za-z0-9_@$#]*|\d+|\*|[+-])")


class Assembler:
    def __init__(self, subset: set[str] | None = None, tables=None, require_blocks: bool = False):
        self.subset = subset
        self.tables = tables  # an object with .words(name) -> list[int] | None (tables.py)
        self.require_blocks = require_blocks
        self.symbols: dict[str, int] = {}
        self.defined_at: dict[str, Line] = {}
        self.lines: list[Line] = []
        self.entry: int | None = None

    # --- parsing --------------------------------------------------------------------

    def parse(self, file: str, text: str) -> None:
        block = None
        for n, raw in enumerate(text.splitlines(), 1):
            ln = Line(file, n, raw.rstrip())
            body = raw.rstrip()
            if not body.strip():
                continue
            if body.lstrip().startswith("*"):
                m = re.match(r"\s*\*@block\s+(\S+)", body)
                if m:
                    block = m.group(1)
                continue
            fields = self._split(body, file, n)
            if body[0] not in " \t":
                ln.label = fields.pop(0)
            if fields:
                ln.opc = fields[0].upper()
                ln.operands = fields[1] if len(fields) > 1 else ""
            ln.block = block
            self.lines.append(ln)

    @staticmethod
    def _split(body: str, file: str, n: int) -> list[str]:
        """Label (if the line starts in column 1), opcode and operands: blank-separated,
        with quotes keeping blanks. Scanning stops once those fields are read: the rest of
        the line is the comment, and an apostrophe there means nothing."""
        want = 3 if body[0] not in " \t" else 2
        fields, cur, quote = [], "", False
        for ch in body:
            if ch == "'":
                quote = not quote
            if ch in " \t" and not quote:
                if cur:
                    fields.append(cur)
                    cur = ""
                    if len(fields) == want:
                        return fields
                continue
            cur += ch
        if quote:
            raise SxasmError(file, n, "unterminated quote")
        if cur:
            fields.append(cur)
        return fields

    # --- expressions ------------------------------------------------------------------

    def value(self, ln: Line, expr: str, here: int, final: bool) -> int:
        toks = [t for t in TOKEN.findall(expr)]
        if "".join(toks).replace(" ", "") != expr.replace(" ", "") or not toks:
            raise SxasmError(ln.file, ln.number, f"bad expression {expr!r}")
        total, sign, want_term = 0, 1, True
        for t in toks:
            if want_term:
                if t in "+-":
                    sign = -sign if t == "-" else sign
                    continue
                total += sign * self._term(ln, t, here, final)
                want_term = False
            else:
                if t not in "+-":
                    raise SxasmError(ln.file, ln.number, f"bad expression {expr!r}")
                sign, want_term = (-1 if t == "-" else 1), True
        if want_term:
            raise SxasmError(ln.file, ln.number, f"bad expression {expr!r}")
        return total

    def _term(self, ln: Line, t: str, here: int, final: bool) -> int:
        if t == "*":
            return here
        if t.isdigit():
            return int(t)
        if t.upper().startswith("X'"):
            return int(t[2:-1], 16)
        if t.upper().startswith("C'"):
            v = 0
            for ch in t[2:-1].encode("ascii"):
                v = (v << 8) | ch
            return v
        if t in self.symbols:
            return self.symbols[t]
        if final:
            raise SxasmError(ln.file, ln.number, f"undefined symbol {t!r}")
        return 0

    def reg(self, ln: Line, s: str, final: bool, even: bool = False) -> int:
        s = s.strip()
        m = re.fullmatch(r"[Rr](\d+)", s)
        v = int(m.group(1)) if m else self.value(ln, s, ln.addr, final)
        if not 0 <= v <= 15:
            raise SxasmError(ln.file, ln.number, f"bad register {s!r} (0-15)")
        if even and v & 1:
            raise SxasmError(ln.file, ln.number, f"floating-point register {s!r} must be even")
        return v

    # --- passes ---------------------------------------------------------------------

    def assemble(self) -> None:
        self._pass(final=False)
        self._pass(final=True)

    def _pass(self, final: bool) -> None:
        loc = 0
        for ln in self.lines:
            opc = ln.opc
            if opc in ("EQU",):
                if not ln.label:
                    raise SxasmError(ln.file, ln.number, "EQU needs a label")
                self._define(ln, ln.label, self.value(ln, ln.operands, loc, final), final)
                continue
            if opc == "ORG":
                loc = self.value(ln, ln.operands, loc, final)
                if loc & 1:
                    raise SxasmError(ln.file, ln.number, "ORG must be even")
                ln.addr = loc
                continue
            if opc in ("DC", "DS", "TABLE") or (opc and opc in by_name()):
                loc = (loc + 1) & ~1
                if self.require_blocks and ln.block is None:
                    raise SxasmError(ln.file, ln.number, f"{opc} is outside any *@block (CODE-2)")
            ln.addr = loc
            if ln.label:
                self._define(ln, ln.label, loc, final)
            if opc is None:
                continue
            if opc == "END":
                if ln.operands:
                    self.entry = self.value(ln, ln.operands, loc, final)
                break
            if opc == "DC":
                ln.words = self._dc(ln, loc, final)
            elif opc == "TABLE":
                ln.words = self._table(ln)
            elif opc == "DS":
                n = self.value(ln, ln.operands, loc, final)
                if n < 0:
                    raise SxasmError(ln.file, ln.number, "DS size must not be negative")
                ln.words = []
                loc += (n + 1) & ~1
                continue
            else:
                ln.words = self._instruction(ln, loc, final)
            loc += 2 * len(ln.words)
            if loc > 0x10000:
                raise SxasmError(ln.file, ln.number, "past the end of the 64 KB address space")

    def _table(self, ln: Line) -> list[int]:
        name = ln.operands.strip()
        words = self.tables.words(name) if self.tables is not None else None
        if words is None:
            known = (
                "no rig data given (--map and --dac)"
                if self.tables is None
                else ("known tables: pitch, first-set-bit, last-set-bit, channel-map")
            )
            raise SxasmError(ln.file, ln.number, f"TABLE {name!r}: {known}")
        return list(words)

    def _define(self, ln: Line, name: str, v: int, final: bool) -> None:
        if not re.fullmatch(r"[A-Za-z_@$#][A-Za-z0-9_@$#]*", name) or re.fullmatch(
            r"[Rr]\d+", name
        ):
            raise SxasmError(ln.file, ln.number, f"bad label {name!r}")
        first = self.defined_at.setdefault(name, ln)
        if first is not ln:
            raise SxasmError(
                ln.file, ln.number, f"duplicate label {name!r} (first at line {first.number})"
            )
        self.symbols[name] = v & 0xFFFF

    def _dc(self, ln: Line, here: int, final: bool) -> list[int]:
        words: list[int] = []
        for item in self._operands(ln.operands):
            u = item.upper()
            if u.startswith("C'"):
                b = item[2:-1].encode("ascii")
                if len(b) % 2:
                    b += b" "
                words += [(b[i] << 8) | b[i + 1] for i in range(0, len(b), 2)]
            elif u.startswith("H'"):
                words.append(int(item[2:-1], 10) & 0xFFFF)
            else:
                v = self.value(ln, item, here, final)
                if not -0x8000 <= v <= 0xFFFF:
                    raise SxasmError(ln.file, ln.number, f"DC value {item!r} out of range")
                words.append(v & 0xFFFF)
        return words

    @staticmethod
    def _operands(s: str) -> list[str]:
        out, cur, quote, depth = [], "", False, 0
        for ch in s:
            if ch == "'":
                quote = not quote
            if ch == "(" and not quote:
                depth += 1
            if ch == ")" and not quote:
                depth -= 1
            if ch == "," and not quote and depth == 0:
                out.append(cur)
                cur = ""
            else:
                cur += ch
        if cur or s.endswith(","):
            out.append(cur)
        return out

    def _addr_index(self, ln: Line, s: str, final: bool) -> tuple[int, int]:
        m = re.fullmatch(r"(.*)\(([^()]*)\)", s.strip())
        if m:
            return self.value(ln, m.group(1), ln.addr, final), self.reg(ln, m.group(2), final)
        return self.value(ln, s, ln.addr, final), 0

    def _instruction(self, ln: Line, here: int, final: bool) -> list[int]:
        op: Op | None = by_name().get(ln.opc or "")
        if op is None:
            raise SxasmError(ln.file, ln.number, f"unknown mnemonic {ln.opc!r}")
        if self.subset is not None and canonical(op) not in self.subset:
            raise SxasmError(
                ln.file, ln.number, f"{ln.opc} ({canonical(op)}) is outside the active subset"
            )
        ops = self._operands(ln.operands)
        want = {"MR": 2, "RR": 2, "R": 1, "MX": 2, "RX": 2, "X": 1, "FF": 2, "FX": 2,
                "SI": 2, "SB": 2, "SX": 1}[op.cls]  # fmt: skip
        if len(ops) != want:
            raise SxasmError(
                ln.file, ln.number, f"{ln.opc} takes {want} operand(s), got {len(ops)}"
            )
        w = op.base
        if op.cls in ("MR", "RR", "FF"):
            even = op.cls == "FF"
            r1 = (
                self._mask(ln, ops[0], final)
                if op.cls == "MR"
                else self.reg(ln, ops[0], final, even)
            )
            w |= (r1 << 4) | self.reg(ln, ops[1], final, even)
            return [w]
        if op.cls == "R":
            return [w | self.reg(ln, ops[0], final)]
        if op.cls == "SI":
            n = self.value(ln, ops[1], here, final)
            if not 0 <= n <= 15:
                raise SxasmError(
                    ln.file, ln.number, f"short immediate {ops[1]!r} out of range 0-15"
                )
            return [w | (self.reg(ln, ops[0], final) << 4) | n]
        if op.cls in ("SB", "SX"):
            target = self.value(ln, ops[-1], here, final)
            dist = target - here
            if final and (dist % 2 or abs(dist) > 30):
                raise SxasmError(
                    ln.file, ln.number, f"short branch target {ops[-1]!r} out of reach (+-30 bytes)"
                )
            forward = dist > 0
            if op.cls == "SB":
                if final and forward != bool(op.base & 0x0100) and dist != 0:
                    way = "forward" if forward else "backward"
                    raise SxasmError(ln.file, ln.number, f"{ln.opc} cannot branch {way}")
                w |= self._mask(ln, ops[0], final) << 4
            elif forward:
                w |= 0x0100
            return [w | (abs(dist) // 2 if final else 0)]
        # MX, RX, X, FX: second halfword is the address
        if op.cls == "X":
            a, x = self._addr_index(ln, ops[0], final)
        else:
            a, x = self._addr_index(ln, ops[1], final)
            r1 = (
                self._mask(ln, ops[0], final)
                if op.cls == "MX"
                else self.reg(ln, ops[0], final, op.cls == "FX")
            )
            w |= r1 << 4
        if final and not -0x8000 <= a <= 0xFFFF:
            raise SxasmError(ln.file, ln.number, f"address {a:#x} out of range")
        return [w | x, a & 0xFFFF]

    def _mask(self, ln: Line, s: str, final: bool) -> int:
        v = self.value(ln, s, ln.addr, final)
        if not 0 <= v <= 15:
            raise SxasmError(ln.file, ln.number, f"condition mask {s!r} out of range 0-15")
        return v


def load_subset(path: Path) -> set[str]:
    names = set()
    for ln in path.read_text().splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            names.add(ln.split()[0].upper())
    return names
