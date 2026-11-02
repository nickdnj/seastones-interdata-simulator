"""GAT-17: every release gate fails on a violation planted at run time, in a temp copy of a staged
install (never committed; no audio is ever written outside pytest's temp folder). The clean
staged install passes the rights gate G1, and `release-gate.py` exits non-zero when G1 fails.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "release-gate.py"
spec = importlib.util.spec_from_file_location("release_gate", GATE)
rg = importlib.util.module_from_spec(spec)
sys.modules["release_gate"] = rg  # dataclasses look their module up while the class is made
spec.loader.exec_module(rg)


@pytest.fixture(scope="module")
def staged(tmp_path_factory) -> Path:
    img = tmp_path_factory.mktemp("staged") / "image"
    p = subprocess.run(["bash", str(ROOT / "scripts/install-station.sh"), "--apply", "--root",
                        str(img), "--platform", "linux", "--allow-missing-build",
                        "--kiosk-user", "kiosk"], capture_output=True, text=True)  # fmt: skip
    assert p.returncode == 0, p.stdout + p.stderr
    return img


@pytest.fixture
def image(staged, tmp_path) -> Path:
    img = tmp_path / "image"
    shutil.copytree(staged, img, symlinks=True)
    return img


def run_gate(img: Path, gate: str, repo: Path = ROOT) -> rg.Result:
    return rg.GATES[gate](rg.Ctx(img, repo))


CONTENT = "opt/seastones/content-baked"


# ------------------------------------------------------------------ G1, the rights gate


def test_g1_passes_on_the_clean_install(staged):
    r = run_gate(staged, "G1")
    assert r.status == "PASS", r.problems


@pytest.mark.parametrize("plant", [
    "riff", "renamed-flac", "derived-score", "derived-json-slot", "passage", "ledger-score",
    "research", "passage-slot", "layer6-on",
])  # fmt: skip
def test_g1_fails_on_each_kind_of_rights_violation(image, plant):
    c = image / CONTENT
    if plant == "riff":
        (c / "presets" / "x.dat").write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(32))
        want = "RIFF/WAVE"
    elif plant == "renamed-flac":
        (image / "opt/seastones/src/web/assets/fonts/extra.woff2").write_bytes(b"fLaC" + bytes(60))
        want = "FLAC"
    elif plant == "derived-score":
        (c / "tide.score").write_text("format: seastones.score/1\norigin: seastones-derived\n")
        want = "seastones-derived"
    elif plant == "derived-json-slot":
        (c / "presets" / "x.patch.json").write_text('{"slug": "x", "tags": ["seastones-derived"]}')
        want = "seastones-derived"
    elif plant == "passage":
        (c / "passages").mkdir()
        (c / "passages" / "side-one.md").write_text("title: Side one\nstatus: draft-hidden\n\nx\n")
        want = "Layer 6 passage"
    elif plant == "ledger-score":
        (c / "demo.score").write_text("format: seastones.score/1\nledger: RS-0007\n")
        want = "research ledger"
    elif plant == "research":
        (image / "opt/seastones/research").mkdir()
        (image / "opt/seastones/research/notes.md").write_text("x\n")
        want = "research/ folder"
    elif plant == "passage-slot":
        with open(c / "slots.md", "a") as fh:
            fh.write("\n## passage-side-one\nkind: passage\nstatus: draft-hidden\n")
        want = "passage slot"
    else:
        with open(c / "kiosk.conf", "a") as fh:
            fh.write("layer6 = on\n")
        want = "Layer 6 on"
    r = run_gate(image, "G1")
    assert r.status == "FAIL"
    assert any(want in p for p in r.problems), r.problems


def test_g1_failure_fails_the_release_check_command(image):
    (image / CONTENT / "presets" / "hidden.bin.txt").write_bytes(b"OggS" + bytes(40))
    p = subprocess.run([sys.executable, str(GATE), "--image", str(image), "--gates", "G1",
                        "--no-record"], capture_output=True, text=True)  # fmt: skip
    assert p.returncode == 1
    assert "THE RIGHTS GATE FAILED" in p.stdout and "Ogg audio" in p.stdout
    assert "hidden.bin.txt" in p.stdout, "the message names the file"


def test_g1_with_nothing_installed_fails_closed(tmp_path):
    (tmp_path / "empty").mkdir()
    assert run_gate(tmp_path / "empty", "G1").status == "FAIL"


# ------------------------------------------------------------------ the other gates


def test_g3_fails_on_an_off_machine_url_and_an_open_firewall(image):
    js = image / "opt/seastones/src/web/app/app.js"
    js.write_text(js.read_text() + '\nfetch("https://example.org/track");\n')
    nft = image / "etc/nftables.d/seastones.nft"
    nft.write_text(nft.read_text().replace("hook output priority filter; policy drop",
                                           "hook output priority filter; policy accept"))  # fmt: skip
    r = run_gate(image, "G3")
    assert r.status == "FAIL"
    assert any("https://example.org/track" in p for p in r.problems)
    assert any("chain output is not default-deny" in p for p in r.problems)


def test_g3_clean_install_needs_only_the_box_checks(staged):
    r = run_gate(staged, "G3")
    assert r.problems == [] and r.status == "NEEDS-HUMAN" and "ss -tulpn" in r.human[0]


def test_g4_fails_when_the_notices_are_missing(image):
    (image / "opt/seastones/THIRD-PARTY-NOTICES").unlink()
    r = run_gate(image, "G4")
    assert r.status == "FAIL" and any("not on the image" in p for p in r.problems)


def test_g5_fails_on_a_pdf_and_a_tape(image):
    (image / "opt/seastones/docs/manual.pdf").write_bytes(b"%PDF-1.4\n")
    (image / CONTENT / "boot.pt").write_bytes(b"\x00" * 16)
    r = run_gate(image, "G5")
    assert r.status == "FAIL" and len(r.problems) == 2


def test_g6_fails_on_a_public_repo_or_a_publish_step(image, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github/workflows/pages.yml").write_text("jobs:\n  p:\n    steps:\n"
                                                      "      - uses: actions/deploy-pages@v4\n")  # fmt: skip
    r = run_gate(image, "G6", repo)
    assert r.status == "FAIL" and any("publish step" in p for p in r.problems)
    (repo / ".github/workflows/pages.yml").unlink()
    monkeypatch.setenv("SX_GATE_VISIBILITY", "PUBLIC")
    r = run_gate(image, "G6", repo)
    assert r.status == "FAIL" and any("not private" in p for p in r.problems)
    monkeypatch.delenv("SX_GATE_VISIBILITY")
    r = run_gate(image, "G6", repo)
    assert r.problems == [] and any("no remote yet" in n for n in r.notes)


def test_g7_fails_on_an_unconfirmed_claim_on_a_visible_screen(image):
    screen = image / CONTENT / "screens" / "01-a-computer-on-stage.md"
    text = screen.read_text().replace(
        "slots: claim-live-1974", "slots: claim-in-the-middle, claim-live-1974"
    )
    screen.write_text(text)
    with open(image / CONTENT / "slots.md", "a") as fh:
        fh.write("\n## claim-in-the-middle\nkind: claim\nstatus: draft-hidden\nclaim: unconfirmed\n"
                 "tags: not-shippable\n")  # fmt: skip
    r = run_gate(image, "G7")
    assert r.status == "FAIL"
    assert any("claim-in-the-middle" in p and "must not ship" in p for p in r.problems), r.problems


def test_g8_fails_on_a_banned_phrase_and_a_seastones_preset(image):
    bell = image / CONTENT / "presets" / "bell.md"
    bell.write_text(bell.read_text().replace("title: Bell", "title: Seastones Bell")
                    + "\nThis is Ned Lagin's original program.\n")  # fmt: skip
    r = run_gate(image, "G8")
    assert r.status == "FAIL"
    assert any("Ned Lagin's original program" in p for p in r.problems)
    assert any("named after Seastones" in p for p in r.problems)


def test_g8_allows_the_disclosures_own_negation(staged):
    r = run_gate(staged, "G8")
    assert not [p for p in r.problems if "endorsed" in p], r.problems


def test_g9_fails_on_a_teaser_and_lagin_material(image):
    js = image / "opt/seastones/src/web/app/attract.js"
    js.write_text(js.read_text() + '\nconst t = "Seastones playback coming soon";\n')
    (image / CONTENT / "nedbase-photo-3.txt").write_text("x")
    r = run_gate(image, "G9")
    assert r.status == "FAIL"
    assert any("coming soon" in p.lower() for p in r.problems)
    assert any("nedbase" in p for p in r.problems)


def test_g10_fails_on_a_test_profile_engine(image):
    test_lib = (
        ROOT / "build/host" / ("libsxhost.dylib" if sys.platform == "darwin" else "libsxhost.so")
    )
    if not test_lib.exists():
        pytest.skip("needs `make host` (the test-profile library)")
    host = image / "opt/seastones/build/prod/host"
    host.mkdir(parents=True, exist_ok=True)
    shutil.copy2(test_lib, host / test_lib.name)
    r = run_gate(image, "G10")
    assert r.status == "FAIL" and any("test profile" in p for p in r.problems), r.problems


def test_g11_fails_on_a_long_story_screen_and_a_form(image):
    screen = image / CONTENT / "screens" / "02-seastones.md"
    screen.write_text(screen.read_text().rstrip() + " " + " ".join(["word"] * 80) + "\n")
    html = image / "opt/seastones/src/web/index.html"
    html.write_text(html.read_text().replace("</body>", '<form><input name="email"></form></body>'))
    r = run_gate(image, "G11")
    assert r.status == "FAIL"
    assert any("story screen of" in p for p in r.problems)
    assert any("<form" in p for p in r.problems)


def test_every_gate_reports_a_status_and_evidence_on_the_clean_install(staged):
    for g in rg.GATES:
        if g in ("G2", "G10"):
            continue  # the slow ones (git history, two rebuilds) have their own runs: make release-check
        r = run_gate(staged, g)
        assert r.status in ("PASS", "FAIL", "NEEDS-HUMAN")
        assert r.evidence or r.problems, g
