"""rigd's cffi declarations match the C headers, field for field (VS-14; ARCHITECTURE 4.5).

cffi in ABI mode lays structs out from its own declarations (src/rigd/engine.py), so a field
added to seastones.h or sxhost.h without the same change there would be read at the wrong
offset with no error. A C probe prints the real sizes and offsets; they must equal cffi's.
Also VS-13 AC 3: no Python can run on the audio or MIDI thread, because rigd hands C no Python
callback at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rigd.engine import CDEF, ffi  # noqa: E402

STRUCTS = ["sx_config", "sx_segment", "sx_image", "sx_cmd", "sx_snapshot", "sxh_audio_cfg",
           "sxh_audio_info", "sxh_audio_status", "sxh_sample", "sxh_midi_status"]  # fmt: skip


def fields(name: str) -> list[str]:
    return [f for f, _ in ffi.typeof(name).fields]


def test_struct_sizes_and_offsets_match_the_headers(tmp_path):
    cc = shutil.which("cc")
    if not cc:
        pytest.skip("no C compiler (UNVERIFIED)")
    lines = ["#include <stddef.h>", "#include <stdio.h>", '#include "sxhost.h"', "int main(void) {"]
    for s in STRUCTS:
        lines.append(f'printf("{s} %zu\\n", sizeof({s}));')
        for f in fields(s):
            lines.append(f'printf("{s}.{f} %zu\\n", offsetof({s}, {f}));')
    lines += ["return 0;", "}"]
    src = tmp_path / "probe.c"
    src.write_text("\n".join(lines) + "\n")
    exe = tmp_path / "probe"
    subprocess.run(
        [cc, "-std=c17", f"-I{ROOT / 'src/engine/include'}", f"-I{ROOT / 'src/host'}",
         str(src), "-o", str(exe)],
        check=True, capture_output=True,
    )  # fmt: skip
    real = dict(ln.split() for ln in subprocess.run([str(exe)], capture_output=True,
                                                     text=True).stdout.splitlines())  # fmt: skip
    for s in STRUCTS:
        assert int(real[s]) == ffi.sizeof(s), s
        for f in fields(s):
            assert int(real[f"{s}.{f}"]) == ffi.offsetof(s, f), f"{s}.{f}"


def test_every_header_function_rigd_declares_exists_in_the_headers():
    headers = (
        (ROOT / "src/engine/include/seastones.h").read_text()
        + (ROOT / "src/engine/include/seastones_test.h").read_text()
        + (ROOT / "src/host/sxhost.h").read_text()
    )
    for name in re.findall(r"\b(sxh?_\w+)\(", CDEF):
        assert re.search(rf"\b{name}\(", headers), name


def test_no_python_callback_is_ever_given_to_c():
    """VS-13 AC 3: C threads (audio callback, CoreMIDI and ALSA threads) can only call C."""
    for p in (ROOT / "src" / "rigd").rglob("*.py"):
        text = p.read_text()
        assert "ffi.callback" not in text and "def_extern" not in text, p
    assert "(*" not in CDEF, "no function-pointer types cross the binding"
    for p in (ROOT / "src" / "host").rglob("*.[ch]"):
        if "vendor" not in p.parts:
            assert "Python.h" not in p.read_text(), p
