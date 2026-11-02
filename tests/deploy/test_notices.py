"""CT-12 / GAT-04: THIRD-PARTY-NOTICES is generated from the vendored files, is up to date,
ships with the station, and holds every notice the About page points visitors to."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTICES = ROOT / "THIRD-PARTY-NOTICES"
sys.path.insert(0, str(ROOT / "scripts"))

import notices  # noqa: E402


def test_the_committed_file_is_what_the_generator_writes():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "notices.py"), "--check"],
                       capture_output=True, text=True)  # fmt: skip
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_simh_licence_is_verbatim_from_the_vendored_headers():
    text = NOTICES.read_text()
    head = (ROOT / "src/engine/simh/Interdata/id16_cpu.c").read_text(encoding="latin-1")
    block = head[head.index("Permission is hereby granted") : head.index("from Robert M Supnik.")]
    for line in block.splitlines():
        if line.strip():
            assert line.strip() in text, line
    assert "Robert M. Supnik" in text and "open-simh" in text
    prov = (ROOT / "src/engine/simh/PROVENANCE.md").read_text()
    commit = re.search(r"\| Commit \| `([0-9a-f]{40})` \|", prov).group(1)
    assert commit in text
    for p in sorted((ROOT / "src/engine/simh").rglob("*")):
        if p.suffix in (".c", ".h"):
            assert str(p.relative_to(ROOT / "src/engine/simh")) in text, p.name


def test_the_about_pages_notices_all_exist_in_the_file():
    """The About page (content/captions/about.md) tells visitors the full licence texts are in
    THIRD-PARTY-NOTICES and names the typefaces and open-simh: each must be there, with its
    licence text, and the file must be installed on the station."""
    about = (ROOT / "content" / "captions" / "about.md").read_text()
    text = NOTICES.read_text()
    assert "THIRD-PARTY-NOTICES" in about
    named = [f for _file, f, _lic, _name in notices.FONT_TABLE if f in about]
    assert named, "the About page names the typefaces"
    for family in named:
        assert f"  {family} (" in text, family
    for _file, family, licfile, _name in notices.FONT_TABLE:
        body = (ROOT / "licenses" / licfile).read_text()
        first = next(ln for ln in body.splitlines() if ln.strip())
        assert first.strip() in text, f"{family}: the copyright line of {licfile}"
    assert "SIL OPEN FONT LICENSE Version 1.1" in text
    assert "Apache License" in text and "Version 2.0, January 2004" in text
    for credit in ("open-simh", "Robert M. Supnik"):
        assert credit in about and credit in text
    paths = subprocess.run(["bash", str(ROOT / "scripts" / "install-station.sh"), "--print-paths",
                            "--platform", "linux", "--allow-missing-build"],
                           capture_output=True, text=True).stdout.split()  # fmt: skip
    assert "/opt/seastones/THIRD-PARTY-NOTICES" in paths
    assert all(
        f"/opt/seastones/licenses/{lic}" in paths for _f, _fam, lic, _n in notices.FONT_TABLE
    )


def test_the_licence_files_are_the_recorded_upstream_files():
    table = (ROOT / "licenses" / "SOURCES.md").read_text()
    for p in sorted((ROOT / "licenses").glob("*.txt")):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        assert f"`{p.name}`" in table and h in table, p.name


def test_each_font_licence_matches_the_fonts_own_name_table():
    fonttools = pytest.importorskip("fontTools.ttLib", reason="fontTools not installed (dev only)")
    pytest.importorskip("brotli", reason="woff2 needs brotli")
    for f, family, licfile, _name in notices.FONT_TABLE:
        names = fonttools.TTFont(ROOT / "src/web/assets/fonts" / f)["name"]
        url = names.getDebugName(14) or ""
        if licfile.startswith("OFL"):
            assert "OFL" in url, (family, url)
        else:
            assert "apache.org/licenses/LICENSE-2.0" in url, (family, url)


def test_a_missing_or_altered_notice_stops_the_generator(tmp_path, monkeypatch):
    """GAT-17 style: the generator refuses rather than writing a wrong file."""
    fake = tmp_path / "simh"
    (fake / "Interdata").mkdir(parents=True)
    src = (ROOT / "src/engine/simh/Interdata/id_io.c").read_text(encoding="latin-1")
    (fake / "Interdata" / "id_io.c").write_text(src, encoding="latin-1")
    (fake / "sim_rev.h").write_text("/* sim_rev.h\n   Copyright (c) 1993 Somebody\n   GNU General "
                                    "Public License */\n")  # fmt: skip
    monkeypatch.setattr(notices, "SIMH", fake)
    with pytest.raises(notices.NoticeError):
        notices.simh_notices()
    (fake / "sim_rev.h").unlink()
    (fake / "Interdata" / "id_io.c").write_text(src.replace("Permission is hereby", "Permit"),
                                                encoding="latin-1")  # fmt: skip
    with pytest.raises(notices.NoticeError):
        notices.simh_notices()
