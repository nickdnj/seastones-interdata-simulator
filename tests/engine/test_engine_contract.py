"""VS-01 acceptance: header, RT-lint, reproducible-FP flags, shared library (header v2, PM-05)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "src" / "engine" / "include" / "seastones.h"


def compile_tu(tmp: Path, compiler: str, std: str, suffix: str) -> subprocess.CompletedProcess:
    tu = tmp / f"tu{suffix}"
    tu.write_text(
        '#include "seastones.h"\n'
        "typedef char api_version_is_2[SX_API_VERSION == 2 ? 1 : -1];\n"
        "int probe(void);\n"
        "int probe(void) { sx_config c; c.api_version = SX_API_VERSION;\n"
        "  return (int)(c.api_version + sizeof(sx_snapshot) + sizeof(sx_cmd)); }\n"
    )
    return subprocess.run(
        [compiler, f"-std={std}", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
         f"-I{HEADER.parent}", "-c", str(tu), "-o", str(tmp / f"tu{suffix}.o")],
        capture_output=True,
        text=True,
    )  # fmt: skip


def test_header_compiles_as_c17(tmp_path: Path) -> None:
    out = compile_tu(tmp_path, "cc", "c17", ".c")
    assert out.returncode == 0, out.stderr


def test_header_compiles_as_cxx(tmp_path: Path) -> None:
    cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        pytest.skip("no C++ compiler (UNVERIFIED)")
    out = compile_tu(tmp_path, cxx, "c++17", ".cpp")
    assert out.returncode == 0, out.stderr


def test_header_tags_every_function_with_its_thread() -> None:
    text = HEADER.read_text()
    protos = [ln for ln in text.splitlines() if re.match(r"^[a-z].*\bsx_\w+\(.*\);", ln)]
    assert len(protos) >= 9
    for ln in protos:
        assert re.search(r"/\* \[(RT|any thread|non-RT)\]", ln), f"untagged: {ln}"


def rt_lint(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(ROOT / "scripts" / "rt-lint.py"), str(root)], capture_output=True, text=True
    )


def test_rt_lint_passes_on_the_tree() -> None:
    out = rt_lint(ROOT)
    assert out.returncode == 0, out.stdout


@pytest.mark.parametrize(
    "planted, why",
    [
        ("void f(void) { char *p = malloc(4); (void)p; }", "malloc"),
        ("void f(void *p) { free(p); }", "free"),
        ("void f(void) { pthread_mutex_lock(0); }", "pthread_mutex_lock"),
        ("void f(void) { usleep(1); }", "usleep"),
        ('void f(void) { printf("x"); }', "printf"),
        ("#include <stdio.h>\nvoid f(void) {}", "stdio.h"),
    ],
)
def test_rt_lint_catches_a_planted_violation(tmp_path: Path, planted: str, why: str) -> None:
    for d in ("render", "dsp"):
        (tmp_path / "src" / "engine" / d).mkdir(parents=True)
    (tmp_path / "src" / "engine" / "render" / "planted.c").write_text(planted + "\n")
    out = rt_lint(tmp_path)
    assert out.returncode == 1 and why in out.stdout, out.stdout


def test_rt_lint_ignores_comments_and_strings(tmp_path: Path) -> None:
    for d in ("render", "dsp"):
        (tmp_path / "src" / "engine" / d).mkdir(parents=True)
    (tmp_path / "src" / "engine" / "dsp" / "ok.c").write_text(
        '/* never call malloc() here */\nstatic const char *s = "free(x)";\n'
        "int dac_read(int x) { return x; }\n"
    )
    out = rt_lint(tmp_path)
    assert out.returncode == 0, out.stdout


def make_vars() -> str:
    return subprocess.run(
        ["make", "-pn", "engine"], cwd=ROOT, capture_output=True, text=True
    ).stdout


def test_engine_flags_are_reproducible_fp() -> None:
    db = make_vars()
    for var in ("OUR_CFLAGS", "VENDOR_CFLAGS"):
        line = next(ln for ln in db.splitlines() if ln.startswith(f"{var} :="))
        assert "-ffp-contract=off" in line, var
        assert "-ffast-math" not in line and "-Ofast" not in line, var


def test_shared_library_is_built() -> None:
    lib = list((ROOT / "build" / "engine").glob("libseastones.*"))
    if not lib:
        pytest.skip("engine not built: run `make engine`")
    assert {p.suffix for p in lib} >= {".a"} and any(p.suffix in (".so", ".dylib") for p in lib)
