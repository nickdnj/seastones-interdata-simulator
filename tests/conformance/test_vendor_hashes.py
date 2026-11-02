"""SP-S3A / CNF-06 pin audit: vendored SIMH files equal the pin; patches stay in their lane.

1. Every vendored file's SHA-256 equals its row in PROVENANCE.md.
2. Every vendored file equals the upstream blob at the pinned commit (needs the pinned
   clone in $SX_CACHE/open-simh; skipped with a message if absent, never silently).
3. Nothing else lives under src/engine/simh/ (no unlisted file, no unlisted patch).
4. Every patch applies cleanly to the vendored files, and reverse-applying it to the patched
   result gives back the pinned bytes.
5. Every hunk of every patch lies inside a whitelisted function (cycle cost, device table,
   loader) and none touches an opcode case body (S-3 GO criterion 4).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SIMH = ROOT / "src" / "engine" / "simh"
PROV = SIMH / "PROVENANCE.md"
CACHE = Path(os.environ.get("SX_CACHE", Path.home() / ".cache" / "seastones"))

#: patch -> (file it may touch, functions or tables its hunks may sit in, forbidden region)
WHITELIST = {
    "0001-cycle-cost.patch": ("Interdata/id16_cpu.c", {"sim_instr", "<file scope>"}),
    "0002-emulated-rtc.patch": ("Interdata/id_uvc.c", {"pic_svc", "lfc_svc", "pic_reset"}),
    "0003-idle-in-engine.patch": ("Interdata/id16_cpu.c", {"sim_instr"}),
    "0004-devices.patch": ("Interdata/id16_sys.c", {"sim_devices", "sim_load", "<file scope>"}),
}


def pin(key: str) -> str:
    for line in (ROOT / "deploy" / "simh.pin").read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            return v.strip()
    raise AssertionError(f"deploy/simh.pin has no {key}")


def provenance_files() -> dict[str, str]:
    rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|", PROV.read_text(), flags=re.M)
    return {p: h for p, h in rows if not p.endswith(".patch")}


def provenance_patches() -> dict[str, tuple[str, str]]:
    rows = re.findall(
        r"^\| `(\d{4}-[^`]+\.patch)` \| `([^`]+)` \| `([0-9a-f]{64})` \|", PROV.read_text(), re.M
    )
    return {name: (target, h) for name, target, h in rows}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_provenance_names_the_pin() -> None:
    text = PROV.read_text()
    assert pin("commit") in text and pin("ref") in text


def test_every_vendored_file_matches_its_recorded_hash() -> None:
    files = provenance_files()
    assert len(files) >= 6, "PROVENANCE.md lists too few files"
    for rel, h in files.items():
        assert (SIMH / rel).is_file(), f"{rel} is listed but missing"
        assert sha(SIMH / rel) == h, (
            f"{rel} differs from the pin (no patch may be applied in place)"
        )


def test_every_vendored_file_keeps_its_copyright_header() -> None:
    for rel in provenance_files():
        head = (SIMH / rel).read_text(encoding="latin-1").splitlines()[:12]
        assert any("Copyright" in ln and "Supnik" in ln for ln in head), rel


def test_nothing_unlisted_under_simh() -> None:
    listed = set(provenance_files()) | {"PROVENANCE.md"}
    listed |= {f"patches/{n}" for n in provenance_patches()}
    found = {
        str(p.relative_to(SIMH)) for p in SIMH.rglob("*") if p.is_file() and p.name != ".gitkeep"
    }
    assert found == listed, f"unlisted: {sorted(found - listed)}; missing: {sorted(listed - found)}"


def test_vendored_files_equal_upstream_blobs() -> None:
    clone = CACHE / "open-simh"
    commit = pin("commit")
    probe = subprocess.run(
        ["git", "-C", str(clone), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True
    )
    if probe.returncode != 0:
        pytest.skip(f"pinned clone not at {clone}; run scripts/build-oracle.sh --source")
    for rel in provenance_files():
        up = subprocess.run(
            ["git", "-C", str(clone), "show", f"{commit}:{rel}"], capture_output=True, check=True
        ).stdout
        assert (SIMH / rel).read_bytes() == up, f"{rel} is not the upstream file at {commit}"


def test_patches_are_listed_with_their_hashes() -> None:
    on_disk = {p.name for p in (SIMH / "patches").glob("*.patch")}
    listed = provenance_patches()
    assert on_disk == set(listed), f"patches dir {sorted(on_disk)} vs PROVENANCE {sorted(listed)}"
    for name, (target, h) in listed.items():
        assert re.fullmatch(r"000[1-4]-[a-z-]+\.patch", name), f"{name}: not one of 0001-0004"
        assert sha(SIMH / "patches" / name) == h, f"{name} changed without regenerating PROVENANCE"
        assert name in WHITELIST and WHITELIST[name][0] == target, f"{name} targets {target}"


def patched_copy(tmp: Path) -> Path:
    work = tmp / "simh"
    shutil.copytree(SIMH, work)
    for name in sorted(provenance_patches()):
        subprocess.run(
            ["patch", "-p1", "-s", "--no-backup-if-mismatch", "-i", str(SIMH / "patches" / name)],
            cwd=work,
            check=True,
        )
    return work


def test_patches_apply_and_reverse_to_the_pin(tmp_path: Path) -> None:
    files = provenance_files()
    work = patched_copy(tmp_path)
    for name in sorted(provenance_patches(), reverse=True):
        subprocess.run(
            [
                "patch",
                "-p1",
                "-R",
                "-s",
                "--no-backup-if-mismatch",
                "-i",
                str(SIMH / "patches" / name),
            ],
            cwd=work,
            check=True,
        )
    for rel, h in files.items():
        assert sha(work / rel) == h, f"reverse-applying the patches does not restore {rel}"


FUNC_START = re.compile(r"^(?:[A-Za-z_][\w \t\*]*?)\b([A-Za-z_]\w*)\s*\([^;]*$")
TABLE_START = re.compile(r"^[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\[[^\]]*\]\s*=")
COMMENT_OR_LITERAL = re.compile(
    r"/\*.*?\*/" r"|//[^\n]*" r'|"(?:\\.|[^"\\\n])*"' r"|'(?:\\.|[^'\\\n])*'", re.S
)


def strip_comments_and_strings(text: str) -> str:
    """Blank out comments and string/char literals, keeping every newline, so braces in
    them cannot confuse the scope scan."""
    return COMMENT_OR_LITERAL.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def scopes(text: str) -> list[str]:
    """For each line, the name of the top-level function or table it belongs to, or
    "<file scope>". A definition owns its header line, its body and its closing brace."""
    names: list[str] = []
    depth, header, current = 0, None, "<file scope>"
    pending: list[int] = []  # header lines seen at depth 0 before the opening brace
    for ln in strip_comments_and_strings(text).split("\n"):
        if depth == 0:
            m = TABLE_START.match(ln) or FUNC_START.match(ln)
            if m:
                header, pending = m.group(1), []
        opens, closes = ln.count("{"), ln.count("}")
        if depth == 0 and opens:
            current = header or "<anonymous>"
            for i in pending:
                names[i] = current
            pending = []
        names.append(current if (depth > 0 or opens) else "<file scope>")
        if depth == 0 and not opens and header:
            pending.append(len(names) - 1)  # e.g. `t_stat sim_instr (void)` before its `{`
        depth = max(0, depth + opens - closes)
        if depth == 0 and (opens or closes):
            current, header, pending = "<file scope>", None, []
    return names


def enclosing(lines: list[str], idx: int) -> str:
    """Name of the function or table definition that contains line `idx` (0-based)."""
    return scopes("\n".join(lines))[idx]


def hunk_lines(patch_text: str) -> list[int]:
    """0-based line numbers, in the patched file, of every added or context-changed line."""
    out, new_ln = [], 0
    for ln in patch_text.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            new_ln = int(m.group(1)) - 1
            continue
        if ln.startswith(("+++", "---")):
            continue
        if ln.startswith("+"):
            out.append(new_ln)
            new_ln += 1
        elif ln.startswith("-"):
            out.append(new_ln)  # a removed line sits just before new_ln
        elif ln.startswith(" "):
            new_ln += 1
    return out


def test_every_hunk_is_inside_a_whitelisted_function(tmp_path: Path) -> None:
    patches = provenance_patches()
    if not patches:
        pytest.skip("no patches yet")
    work = patched_copy(tmp_path)
    for name in patches:
        target, allowed = WHITELIST[name]
        lines = (work / target).read_text(encoding="latin-1").splitlines()
        text = (SIMH / "patches" / name).read_text()
        owner = scopes("\n".join(lines))
        for idx in hunk_lines(text):
            fn = owner[idx]
            assert fn in allowed, f"{name}: line {idx + 1} of {target} is in {fn}, not {allowed}"
            if fn == "<file scope>":
                # At file scope a patch may add only preprocessor lines (the SX_CYC default)
                # and extern declarations (patch 0004 naming our devices).
                ln = lines[idx].strip()
                assert ln == "" or ln.startswith("#") or re.match(r"extern DEVICE [\w, ]+;", ln), (
                    f"{name}: line {idx + 1} changes file-scope code: {lines[idx]!r}"
                )
            if fn == "sim_instr":
                # The opcode dispatch starts at `switch (op)`; nothing at or after it may change.
                dispatch = next(i for i, ln in enumerate(lines) if "switch (op) {" in ln)
                assert idx < dispatch, f"{name}: line {idx + 1} touches the opcode case bodies"


def test_the_whitelist_rejects_a_semantic_patch(tmp_path: Path) -> None:
    """The audit must be able to fail: the S-3 negative-test mutation (a flipped carry rule
    inside the CLHR case body) is exactly what GO criterion 4 forbids."""
    mutation = ROOT / "tests" / "conformance" / "mutations" / "flip-clh-carry.patch"
    work = patched_copy(tmp_path)
    subprocess.run(
        ["patch", "-p1", "-s", "--no-backup-if-mismatch", "-i", str(mutation)], cwd=work, check=True
    )
    lines = (work / "Interdata/id16_cpu.c").read_text(encoding="latin-1").splitlines()
    dispatch = next(i for i, ln in enumerate(lines) if "switch (op) {" in ln)
    idxs = hunk_lines(mutation.read_text())
    assert idxs and all(enclosing(lines, i) == "sim_instr" for i in idxs)
    assert all(i > dispatch for i in idxs), "the audit would have let a semantic patch through"
