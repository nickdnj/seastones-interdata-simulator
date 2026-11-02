#!/usr/bin/env python3
"""The release gate: G1 to G11 of QA-STRATEGY 8 (CT-05, CT-16, GAT-01 to GAT-16).

    make release-check                      stage the production install, run every gate
    python3 scripts/release-gate.py [--image DIR] [--gates G1,G4] [--record-dir DIR]

It runs against an **installed image**, not the working tree: by default it stages one with
``scripts/install-station.sh --apply --root build/release/image --platform linux`` (exactly the
files the station would get, the production build included) and scans that, plus the repo
for the gates that are about the repo (G2 history, G6 visibility, G10 rebuilds). ``--image``
points it at a mounted or unpacked real image instead.

Each gate reports PASS, FAIL or NEEDS-HUMAN with the evidence (file paths, hashes, commands)
and, for NEEDS-HUMAN, what a person must check and who. A gate whose automated part fails is
FAIL; one whose automated part passes but which also has a box or sign-off part is
NEEDS-HUMAN. The exit status is 1 if any gate FAILs, so **the rights gate G1 always fails the
build**: any Layer 6 passage, Seastones-derived file, recording, research folder, or score
pointing at the research ledger on the image. A release record (Markdown and JSON, GAT-16) is
written to ``--record-dir`` (default build/release/); copy it into docs/qa/results/ with the
human sign-offs for an actual release.

Every gate also has a planted-violation test (GAT-17) in tests/deploy/test_release_gate.py.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import derived_guard  # noqa: E402

DEST = "opt/seastones"
TEXT_EXT = (".md", ".json", ".conf", ".txt", ".html", ".js", ".mjs", ".css", ".score")
WEB_CODE = (".html", ".js", ".mjs", ".css", ".json")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg", ".heic")


@dataclass
class Result:
    gate: str
    title: str
    problems: list[str] = field(default_factory=list)
    human: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.problems:
            return "FAIL"
        return "NEEDS-HUMAN" if self.human else "PASS"

    def as_dict(self) -> dict:
        return {"gate": self.gate, "title": self.title, "status": self.status,
                "problems": self.problems, "human": self.human, "evidence": self.evidence,
                "notes": self.notes}  # fmt: skip


class Ctx:
    def __init__(self, image: Path, repo: Path = ROOT):
        self.image, self.repo = image, repo
        self.dest = image / DEST
        self.content_dirs = [d for d in (self.dest / "content-baked", image / "data" / "content",
                                         image / "Users/Shared/Seastones/data/content") if d.is_dir()]  # fmt: skip
        self.web = self.dest / "src" / "web"

    def rel(self, p: Path) -> str:
        try:
            r = str(p.relative_to(self.image))
            return "image:/" + ("" if r == "." else r)
        except ValueError:
            return str(p)

    def files(self, base: Path, exts: tuple[str, ...] | None = None) -> list[Path]:
        if not base.is_dir():
            return []
        out = []
        for p in sorted(base.rglob("*")):
            if (
                p.is_file()
                and "__pycache__" not in p.parts
                and (exts is None or p.suffix.lower() in exts)
            ):
                out.append(p)
        return out


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_only(path: Path, text: str) -> str:
    """The file without comments (a comment may name what is forbidden; tests/web does this too)."""
    if path.suffix in (".js", ".mjs", ".css"):
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", text)
    if path.suffix == ".html":
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


def visitor_text(p: Path) -> list[tuple[int, str]]:
    """The lines of a content .md a visitor can read: the body, and title/text/eyebrow/label
    values. Header fields (status, note, source, auth, ...) and comments are not shown."""
    out = []
    lines = read(p).splitlines()
    in_header = True
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if in_header:
            if not s:
                in_header = False
                continue
            m = re.match(r"^(title|eyebrow|label|name):\s*(.*)$", s)
            if m:
                out.append((n, m.group(2)))
            continue
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([a-z_-]+):\s*(.*)$", s)
        if m:
            if m.group(1) in ("text", "title", "label", "caption"):
                out.append((n, m.group(2)))
            continue
        out.append((n, s))
    return out


def content_md(ctx: Ctx) -> list[Path]:
    return [p for d in ctx.content_dirs for p in ctx.files(d, (".md",))
            if p.name not in ("README.md", "slots.md") and "rig" not in p.relative_to(d).parts[:1]]  # fmt: skip


# ============================================================================ G1 rights


def g1(ctx: Ctx) -> Result:
    r = Result(
        "G1",
        "No Seastones-derived file or recording on the production image (GAT-01; FAILS THE BUILD)",
    )
    if not ctx.dest.is_dir():
        r.problems.append(
            f"no installed tree at {ctx.rel(ctx.dest)}: nothing to check means nothing is proven"
        )
        return r
    for f in derived_guard.scan(ctx.image, image=True):
        r.problems.append(f"{ctx.rel(f.path)}: {f.reason}")
    for p in ctx.files(ctx.image):
        rel = p.relative_to(ctx.image)
        low = str(rel).lower()
        if "passages" in rel.parts or re.search(r"(^|/)passage[^/]*\.(md|score|json)$", low):
            r.problems.append(
                f"{ctx.rel(p)}: a Layer 6 passage is on the image; Layer 6 is off for v1 (SEA-1, SEA-3)"
            )
            continue
        if p.suffix.lower() in TEXT_EXT:
            text = read(p)
            if p.suffix == ".score" and re.search(r"(?m)^\s*ledger\s*:", text):
                r.problems.append(f"{ctx.rel(p)}: a score that points at the research ledger "
                                  "(a transcription of a recording) is on the image")  # fmt: skip
            if p.suffix == ".md" and re.search(r"(?m)^kind:\s*passage\s*$", text):
                r.problems.append(f"{ctx.rel(p)}: a passage item is on the image (Layer 6)")
    for d in ctx.content_dirs:
        slots = d / "slots.md"
        for m in re.finditer(r"(?ms)^## (\S+)\n(.*?)(?=^## |\Z)", read(slots)):
            body = m.group(2)
            if re.search(r"(?m)^kind:\s*passage\b", body):
                r.problems.append(
                    f"{ctx.rel(slots)}: slot '{m.group(1)}' is a passage slot (Layer 6)"
                )
    conf = [read(d / "kiosk.conf") for d in ctx.content_dirs]
    for c in conf:
        if re.search(r"(?im)^\s*layer_?6\w*\s*=\s*(on|yes|true|1)\b", c):
            r.problems.append("kiosk.conf switches Layer 6 on")
    r.evidence.append(f"scanned every file under {ctx.rel(ctx.image)} by content (audio magic bytes, "
                      "the seastones-derived tag), passages, ledger-linked scores, research/")  # fmt: skip
    return r


# ============================================================================ G2 git


def g2(ctx: Ctx) -> Result:
    r = Result("G2", "No recordings in git: tree, history, hook (GAT-02)")
    cp = ctx.repo / "scripts" / "check-private.py"
    for args in (["--tree"], ["--all-history"]):
        p = subprocess.run(
            [sys.executable, str(cp), *args], cwd=ctx.repo, capture_output=True, text=True
        )
        tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
        r.evidence.append(
            f"check-private.py {' '.join(args)}: exit {p.returncode}: {tail[0][:160]}"
        )
        if p.returncode != 0:
            r.problems.append(f"check-private.py {' '.join(args)} found private material:\n"
                              + (p.stdout + p.stderr).strip()[:2000])  # fmt: skip
    hook = None
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ctx.repo,
                                capture_output=True, text=True).stdout.strip()  # fmt: skip
        hp = subprocess.run(["git", "config", "core.hooksPath"], cwd=ctx.repo,
                            capture_output=True, text=True).stdout.strip()  # fmt: skip
        base = Path(hp) if hp else Path(common) / "hooks"
        if not base.is_absolute():
            base = ctx.repo / base
        hook = base / "pre-commit"
    except OSError:
        pass
    if hook is None or not hook.exists() or "check-private" not in read(hook):
        r.human.append(f"the pre-commit hook is not installed here ({hook}): run "
                       "scripts/dev-setup.sh on every machine that commits (owner: Nick)")  # fmt: skip
    else:
        r.evidence.append(f"pre-commit hook present: {hook}")
    return r


# ============================================================================ G3 offline


LOOPBACK_URL = re.compile(
    r"^(?:https?|wss?)://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+|:\*)?(?:/|$)"
)
URL = re.compile(r"\b(?:https?|wss?)://[^\s\"'`<>)]+")
NAMESPACE_URLS = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink",
                  "http://www.w3.org/1999/xhtml")  # fmt: skip


def g3(ctx: Ctx) -> Result:
    r = Result("G3", "No network egress, offline (GAT-03)")
    for p in ctx.files(ctx.web, WEB_CODE):
        text = code_only(p, read(p))
        for m in URL.finditer(text):
            u = m.group(0).rstrip(".,;")
            if u in NAMESPACE_URLS or LOOPBACK_URL.match(u):
                continue
            r.problems.append(f"{ctx.rel(p)}: a request off the machine could be made to {u}")
        if re.search(r"<link[^>]+href=[\"']?https?:", text, re.I):
            r.problems.append(f"{ctx.rel(p)}: an external <link>")
    serve = read(ctx.web / "serve.py")
    csp = re.search(r"CSP = \((.*?)\)", serve, re.S)
    csp_text = "".join(re.findall(r'"([^"]*)"', csp.group(1))) if csp else ""
    if "default-src 'self'" not in csp_text:
        r.problems.append("the page server's Content-Security-Policy is missing default-src 'self'")
    m = re.search(r"connect-src ([^;]*)", csp_text)
    for src in m.group(1).split() if m else ["(none)"]:
        if src != "'self'" and not LOOPBACK_URL.match(src.replace(":*", ":1")):
            r.problems.append(f"the CSP's connect-src allows {src}, which is not loopback")
    for f, needle in ((ctx.dest / "src/rigd/__main__.py", "refusing to listen beyond loopback"),
                      (ctx.web / "serve.py", "refusing to listen beyond loopback")):  # fmt: skip
        if needle not in read(f):
            r.problems.append(f"{ctx.rel(f)} no longer refuses a non-loopback address")
    units = ctx.image / "etc/systemd/system"
    if units.is_dir():
        for u in ("seastones-rigd.service", "seastones-web.service", "seastones-playable.service"):
            t = read(units / u)
            if "IPAddressDeny=any" not in t or "IPAddressAllow=localhost" not in t:
                r.problems.append(
                    f"{ctx.rel(units / u)}: not limited to localhost (IPAddressDeny=any)"
                )
        for u in sorted(units.glob("*.service")):
            if re.search(r"(?m)^ExecStart=.*\b(sshd|avahi|nginx|apache2|smbd|telnetd)\b", read(u)):
                r.problems.append(f"{ctx.rel(u)} starts a network service")
        nft = read(ctx.image / "etc/nftables.d/seastones.nft")
        for chain in ("input", "forward", "output"):
            mm = re.search(rf"chain {chain} \{{[^}}]*?policy (\w+);", nft, re.S)
            if not mm or mm.group(1) != "drop":
                r.problems.append(f"nftables: chain {chain} is not default-deny")
        r.evidence.append("units: IPAddressDeny=any; nftables input/forward/output policy drop")
    else:
        r.notes.append(
            "no systemd tree in this image (a macOS install): the unit and firewall checks did not run"
        )
    r.evidence.append(
        f"web tree scanned for off-machine URLs: {len(ctx.files(ctx.web, WEB_CODE))} files"
    )
    r.human.append("on the box (SYS-09, owner QA): `ss -tulpn` shows only 127.0.0.1:8080 and "
                   ":7690; nft list ruleset is loaded; rfkill shows Wi-Fi and Bluetooth blocked; no "
                   "SSH; 24 h capture shows no packet from the box; the LAN dial test finds nothing")  # fmt: skip
    return r


# ============================================================================ G4 notices


def g4(ctx: Ctx) -> Result:
    r = Result("G4", "Licence notices (GAT-04)")
    shipped = ctx.dest / "THIRD-PARTY-NOTICES"
    repo_n = ctx.repo / "THIRD-PARTY-NOTICES"
    if not shipped.exists():
        r.problems.append("THIRD-PARTY-NOTICES is not on the image")
    elif not repo_n.exists() or sha256(shipped) != sha256(repo_n):
        r.problems.append("the image's THIRD-PARTY-NOTICES differs from the repo's")
    p = subprocess.run([sys.executable, str(ctx.repo / "scripts/notices.py"), "--check"],
                       capture_output=True, text=True)  # fmt: skip
    r.evidence.append(f"scripts/notices.py --check: exit {p.returncode}")
    if p.returncode != 0:
        r.problems.append(
            "THIRD-PARTY-NOTICES is stale or cannot be generated: " + (p.stdout + p.stderr).strip()
        )
    text = read(shipped)
    for need in ("Robert M. Supnik", "Permission is hereby granted", "SIL OPEN FONT LICENSE",
                 "open-simh"):  # fmt: skip
        if need not in text:
            r.problems.append(f"THIRD-PARTY-NOTICES lacks {need!r}")
    prov = read(ctx.repo / "src/engine/simh/PROVENANCE.md")
    rows = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|", prov, re.M)
    for name, h in rows:
        if "/" in name or name.endswith((".c", ".h")):
            f = ctx.repo / "src/engine/simh" / name
            if not f.exists() or sha256(f) != h:
                r.problems.append(
                    f"src/engine/simh/{name}: differs from its PROVENANCE.md hash (header altered?)"
                )
    r.evidence.append(f"PROVENANCE.md: {len(rows)} hashed entries checked")
    for d in ctx.content_dirs[:1]:
        about = read(d / "captions/about.md")
        for key in ("credits", "notices", "privacy"):
            if f"## {key}\n" not in about:
                r.problems.append(f"the About page has no '{key}' card")
    review = (
        text.split("6. For review by a person", 1)[1] if "6. For review by a person" in text else ""
    )
    items = [i.strip() for i in re.split(r"\n  - ", review)[1:]]
    for i in items:
        if not i.startswith("No GPL"):
            r.human.append("THIRD-PARTY-NOTICES review item (Doug or counsel, HUM-10): "
                           + " ".join(i.split()))  # fmt: skip
    return r


# ============================================================================ G5 vendor binaries


def g5(ctx: Ctx) -> Result:
    r = Result("G5", "No vendor binaries or manual scans (GAT-05)")
    for p in ctx.files(ctx.image):
        low = p.name.lower()
        head = p.read_bytes()[:8]
        if low.endswith(".pdf") or head.startswith(b"%PDF"):
            r.problems.append(f"{ctx.rel(p)}: a PDF is on the image (no manual scans, RIGHTS-6)")
        elif low.endswith((".pt", ".tape", ".bin", ".tap", ".ptp")):
            r.problems.append(f"{ctx.rel(p)}: a tape or binary image is on the image (RIGHTS-6)")
    hashlist = os.environ.get("SX_PRIVATE_HASHLIST", "")
    if hashlist and Path(hashlist).is_file():
        listed = set(re.findall(r"\b[0-9a-f]{64}\b", Path(hashlist).read_text()))
        for p in ctx.files(ctx.image):
            if sha256(p) in listed:
                r.problems.append(f"{ctx.rel(p)}: matches the private hash list of vendor material")
        r.evidence.append(f"checked against the private hash list ({len(listed)} hashes)")
    else:
        r.human.append("the private hash list of Interdata/Perkin-Elmer tapes and bitsavers PDFs "
                       "lives outside the repo: run with SX_PRIVATE_HASHLIST=<file> (owner: Nick)")  # fmt: skip
    imgs = [p for p in ctx.files(ctx.image, IMAGE_EXT)]
    if [p for p in imgs if p.suffix.lower() != ".svg"]:
        r.human.append("raster images on the image need the perceptual-hash check against the "
                       "listed manual figures: " + ", ".join(ctx.rel(p) for p in imgs if p.suffix.lower() != ".svg"))  # fmt: skip
    r.evidence.append(f"no PDF, tape or .bin among {len(ctx.files(ctx.image))} files; "
                      f"{len(imgs)} image file(s)")  # fmt: skip
    return r


# ============================================================================ G6 private repo


PUBLISH = re.compile(r"actions/deploy-pages|actions/upload-pages-artifact|gh-pages|"
                     r"softprops/action-gh-release|\bgh release\b|npm publish|twine upload|"
                     r"docker push|actions/create-release", re.I)  # fmt: skip


def g6(ctx: Ctx) -> Result:
    r = Result("G6", "Private repo, no publish step (GAT-06)")
    remotes = subprocess.run(["git", "remote", "-v"], cwd=ctx.repo, capture_output=True,
                             text=True).stdout.strip()  # fmt: skip
    vis = os.environ.get("SX_GATE_VISIBILITY")  # tests, or an operator who checked by hand
    if not remotes:
        r.notes.append("no remote yet: nothing is pushed anywhere, so nothing can be public")
        r.evidence.append("git remote -v: (none)")
        if vis and vis.lower() != "private":
            r.problems.append(f"repository visibility is {vis!r}, not private")
    else:
        r.evidence.append("git remote -v: " + " | ".join(sorted(set(remotes.splitlines()))))
        if vis is None and shutil.which("gh") and os.environ.get("SX_GATE_NETWORK") == "1":
            p = subprocess.run(["gh", "repo", "view", "--json", "visibility", "-q", ".visibility"],
                               cwd=ctx.repo, capture_output=True, text=True)  # fmt: skip
            vis = p.stdout.strip() or None
        if vis is None:
            r.human.append("a remote exists: confirm it is private and has no public fork, Pages "
                           "or release assets (gh repo view --json visibility; SX_GATE_NETWORK=1)")  # fmt: skip
        elif vis.lower() != "private":
            r.problems.append(f"repository visibility is {vis!r}, not private")
        else:
            r.evidence.append("visibility: private")
    for wf in sorted((ctx.repo / ".github" / "workflows").glob("*.y*ml")):
        for n, line in enumerate(read(wf).splitlines(), 1):
            if PUBLISH.search(line) and not line.lstrip().startswith("#"):
                r.problems.append(f"{wf.relative_to(ctx.repo)}:{n}: a publish step: {line.strip()}")
    for pj in ctx.repo.rglob("package.json"):
        if "node_modules" in pj.parts:
            continue
        try:
            if json.loads(read(pj)).get("private") is not True:
                r.problems.append(f'{pj.relative_to(ctx.repo)}: not "private": true')
        except ValueError:
            r.problems.append(f"{pj.relative_to(ctx.repo)}: unreadable")
    r.human.append("the outreach-text and contact denylist lives outside the repo: scan the "
                   "tree with it before release (owner: Nick); check-private.py covers emails and phones")  # fmt: skip
    return r


# ============================================================================ G7 claims


def load_claims_check():
    spec = importlib.util.spec_from_file_location(
        "sx_story_claims", ROOT / "tests/web/test_story_claims.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check


def g7(ctx: Ctx) -> Result:
    r = Result("G7", "Claims evidence (GAT-07)")
    if not ctx.content_dirs:
        r.problems.append("no content on the image")
        return r
    check = load_claims_check()
    for d in ctx.content_dirs:
        for problem in check(str(d)):
            r.problems.append(f"{ctx.rel(d)}: {problem}")
        slots = read(d / "slots.md")
        for m in re.finditer(r"(?ms)^## (\S+)\n(.*?)(?=^## |\Z)", slots):
            body = m.group(2)
            if re.search(r"(?m)^kind:\s*claim", body) and re.search(r"(?m)^claim:\s*confirmed", body) \
                    and re.search(r"(?m)^status:\s*ready", body):  # fmt: skip
                if not re.search(r"(?m)^source:\s*\S", body):
                    r.problems.append(
                        f"{ctx.rel(d)}/slots.md: '{m.group(1)}' is confirmed with no source"
                    )
                if not re.search(
                    r"evidence_kind:?\s*(dated-photo|document|on-record-statement)", body
                ):
                    r.problems.append(
                        f"{ctx.rel(d)}/slots.md: '{m.group(1)}' has no accepted evidence_kind"
                    )
    r.evidence.append("tests/web/test_story_claims.check() over each content set; every ready "
                      "confirmed slot has a source and an evidence_kind")  # fmt: skip
    r.human.append("HUM-12: each confirmed claim read against its citation by someone who did not "
                   "write it (the machine proves a citation exists, not what it says)")  # fmt: skip
    return r


# ============================================================================ G8 phrasings


BANNED = (
    (r"ned lagin'?s original program", "Ned Lagin's original program"),
    (r"lagin'?s code", "Lagin's code"),
    (r"the real seastones", "the real Seastones"),
    (r"\bofficial\b", "official"),
    (r"\bauthori[sz]ed\b", "authorised"),
    (r"grateful dead exhibit", "Grateful Dead exhibit"),
    (r"\bauthentic\b", "authentic (about our program)"),
    (r"\bendorsed by\b", "endorsed by (outside the disclosure's negation)"),
)  # fmt: skip


def g8(ctx: Ctx) -> Result:
    r = Result("G8", "Required and banned phrasings (GAT-08, GAT-09, CNT-11)")
    if not ctx.content_dirs:
        r.problems.append("no content on the image")
        return r
    d = ctx.content_dirs[0]
    for p in content_md(ctx):
        for n, line in visitor_text(p):
            low = line.lower()
            for pat, label in BANNED:
                for m in re.finditer(pat, low):
                    before = low[max(0, m.start() - 40) : m.start()]
                    if label.startswith("endorsed") and re.search(r"\bnot\b[^.]*$", before):
                        continue  # "Not affiliated with or endorsed by ...": the disclosure itself
                    r.problems.append(
                        f"{ctx.rel(p)}:{n}: banned phrasing '{label}': {line.strip()[:120]}"
                    )
    for p in ctx.files(d / "presets", (".md", ".json")):
        t = read(p)
        name = re.search(r'(?m)^title:\s*(.*)$|"(?:title|name)"\s*:\s*"([^"]*)"', t)
        if name and "seastones" in (name.group(1) or name.group(2) or "").lower():
            r.problems.append(f"{ctx.rel(p)}: a preset named after Seastones (RIGHTS-4)")
    disclosure = read(d / "captions/disclosure.md").split("\n\n", 1)
    body = disclosure[1] if len(disclosure) > 1 else ""
    if len(body.split()) < 52:
        r.problems.append(
            f"the disclosure has {len(body.split())} words; the approved minimum is 52 (CONT-5)"
        )
    frame = read(d / "captions/frame.md")
    attract = read(d / "captions/attract.md")
    if "a recreation" not in frame.lower():
        r.problems.append("the footer on every layer no longer says 'a recreation' (CONT-5)")
    if not re.search(r"recreat", attract, re.I):
        r.problems.append("the attract lockup carries no recreation signal (D3, RIGHTS-4)")
    if "simulated" not in frame.lower():
        r.problems.append("the header no longer says 'simulated' (CONT-5)")
    r.evidence.append(
        f"banned phrasings scanned over the visitor text of {len(content_md(ctx))} content files"
    )
    r.human.append("Doug approves the title wording (Q-M1, DG-01), the disclosure and the story copy "
                   "(HUM-11); 'with the Grateful Dead' as branding needs a person's read")  # fmt: skip
    return r


# ============================================================================ G9 Lagin material, teaser


TEASER = re.compile(
    r"coming soon|seastones playback|reconstructed passage|best guess|layer[ -]?6", re.I
)


def g9(ctx: Ctx) -> Result:
    r = Result("G9", "No Lagin material, band art or teaser (GAT-10, GAT-11)")
    for p in ctx.files(ctx.image):
        if re.search(r"nedbase|spiritcats|steal.?your.?face|dancing.?bear", p.name, re.I):
            r.problems.append(f"{ctx.rel(p)}: a file named after Lagin's or the band's material")
    for d in ctx.content_dirs:
        for m in re.finditer(r"(?ms)^## (\S+)\n(.*?)(?=^## |\Z)", read(d / "slots.md")):
            body = m.group(2)
            if re.search(r"(?m)^kind:\s*media", body) and re.search(r"(?m)^status:\s*ready", body) \
                    and re.search(r"(?im)^source:.*(lagin|nedbase|spiritcats)", body):  # fmt: skip
                r.problems.append(f"{ctx.rel(d)}/slots.md: media slot '{m.group(1)}' is sourced to "
                                  "Lagin and ready (only withheld is allowed, STORY-4)")  # fmt: skip
    for p in ctx.files(ctx.web, WEB_CODE):
        text = code_only(p, read(p))
        for m in TEASER.finditer(text):
            r.problems.append(f"{ctx.rel(p)}: teaser or layer-6 string {m.group(0)!r}")
    for p in content_md(ctx):
        for n, line in visitor_text(p):
            for m in TEASER.finditer(line):
                r.problems.append(f"{ctx.rel(p)}:{n}: teaser or layer-6 string {m.group(0)!r}")
    fonts = ctx.web / "assets" / "fonts"
    manifest = read(fonts / "MANIFEST.txt")
    for f in ctx.files(fonts, (".woff2", ".woff", ".ttf", ".otf")):
        if f.name not in manifest:
            r.problems.append(f"{ctx.rel(f)}: a font with no entry in the asset manifest")
    for f in ctx.files(ctx.image, IMAGE_EXT):
        rel = f.relative_to(ctx.image)
        if f.suffix.lower() == ".svg" and "src" in rel.parts:
            continue  # the page's own drawings: checked by tests/web (no raster, no protected name)
        r.problems.append(f"{ctx.rel(f)}: an image with no licence manifest entry")
    r.evidence.append("file names, media slots, the web tree and visitor text scanned")
    r.human.append("manifest review for band artwork and logos (perceptual-hash denylist kept "
                   "outside the repo; owner: Doug with counsel)")  # fmt: skip
    return r


# ============================================================================ G10 reproducible


def g10(ctx: Ctx) -> Result:
    r = Result("G10", "Reproducible build (GAT-12)")
    srcs = ["src/program/rig.s", "src/program/scan.s", "src/program/voices.s", "src/program/routines.s",
            "src/program/score.s", "src/program/memory.s", "src/program/tables.s"]  # fmt: skip
    hashes: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="sx-g10-") as tmp:
        for i in (1, 2):
            out = Path(tmp) / f"b{i}"
            for name, cmap in (("rig", "channel-map.md"), ("rig8", "channel-map-8.md")):
                cmd = [sys.executable, "-m", "sxasm", *srcs, "--subset",
                       "src/program/subset/m74-portable-1.txt", "--dac", "src/program/rig/dac.md",
                       "--map", f"src/program/rig/{cmap}", "-o", str(out), "--name", name]  # fmt: skip
                p = subprocess.run(cmd, cwd=ctx.repo, capture_output=True, text=True,
                                   env=dict(os.environ, PYTHONPATH=str(ctx.repo / "src/toolchain")))  # fmt: skip
                if p.returncode != 0:
                    r.problems.append(
                        f"sxasm failed ({name}): {(p.stdout + p.stderr).strip()[:300]}"
                    )
                    return r
            idx = Path(tmp) / f"idx{i}"
            from content.tool.index import build

            build(str(ctx.repo / "content"), str(idx), "baked")
            hashes.append({
                "rig.img.json": sha256(out / "rig.img.json"),
                "rig8.img.json": sha256(out / "rig8.img.json"),
                "content index.json": sha256(idx / "index.json"),
            })  # fmt: skip
    for k in hashes[0]:
        if hashes[0][k] != hashes[1][k]:
            r.problems.append(
                f"{k}: two builds differ ({hashes[0][k][:12]} vs {hashes[1][k][:12]})"
            )
        else:
            r.evidence.append(f"{k}: {hashes[0][k]} (two builds identical)")
    shipped = ctx.dest / "build/prod/program/rig.img.json"
    if shipped.exists():
        if sha256(shipped) != hashes[0]["rig.img.json"]:
            r.problems.append("the image's rig.img.json is not what this source builds")
        else:
            r.evidence.append("the image's rig.img.json equals a fresh build")
    else:
        r.problems.append("no production program image on the image (make host-production)")
    lib = next((p for p in (ctx.dest / "build/prod/host").glob("libsxhost.*")), None) \
        if (ctx.dest / "build/prod/host").is_dir() else None  # fmt: skip
    host_lib = (
        ctx.repo
        / "build/prod/host"
        / ("libsxhost.dylib" if sys.platform == "darwin" else "libsxhost.so")
    )
    probe = (
        lib
        if lib is not None and lib.suffix == host_lib.suffix
        else (host_lib if host_lib.exists() else None)
    )
    if probe is None:
        r.human.append("the engine library for the station's platform is not on this staged image "
                       "(built on the station: make host-production), so its profile was not checked here")  # fmt: skip
    else:
        code = ("import sys; sys.path.insert(0, sys.argv[2]); from rigd import engine as e; "
                "lib = e.load_library(__import__('pathlib').Path(sys.argv[1])); "
                "print(e.ffi.string(lib.sxh_profile()).decode())")  # fmt: skip
        p = subprocess.run([sys.executable, "-c", code, str(probe), str(ctx.repo / "src")],
                           capture_output=True, text=True)  # fmt: skip
        prof = p.stdout.strip()
        r.evidence.append(f"{ctx.rel(probe)}: profile {prof or '?'}")
        if prof != "production":
            r.problems.append(f"the engine on the image is the {prof or 'unknown'!s} profile, not "
                              "production (test hooks must not ship, VS-27)")  # fmt: skip
    pin = read(ctx.repo / "deploy/simh.pin")
    if not re.search(r"\b[0-9a-f]{40}\b", pin):
        r.problems.append("deploy/simh.pin has no commit")
    r.human.append("GAT-12 in full: a fresh checkout on the release machine, built twice, hashes "
                   "into the release record (this run rebuilt the program and content index only)")  # fmt: skip
    return r


# ============================================================================ G11 readability, privacy


def words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’./-]*", s))


def syllables(w: str) -> int:
    w = w.lower().strip(".,;:!?'’\"")
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups) - (1 if w.endswith("e") and len(groups) > 1 and not w.endswith("le") else 0)
    return max(1, n)


def fk_grade(text: str) -> float:
    sents = max(1, len(re.findall(r"[.!?](\s|$)", text)))
    ws = re.findall(r"[A-Za-z][A-Za-z'’]*", text)
    if not ws:
        return 0.0
    return 0.39 * len(ws) / sents + 11.8 * sum(syllables(w) for w in ws) / len(ws) - 15.59


PRIVACY = re.compile(r"<form\b|<input\b|mailto:|analytics|gtag\(|googletagmanager|qrcode|"
                     r"navigator\.sendBeacon|localStorage\.setItem|indexedDB|getUserMedia", re.I)  # fmt: skip


def g11(ctx: Ctx) -> Result:
    r = Result("G11", "Readability budget and privacy surface (GAT-13, GAT-14)")
    if not ctx.content_dirs:
        r.problems.append("no content on the image")
        return r
    d = ctx.content_dirs[0]
    over_grade = []
    for p in ctx.files(d / "screens", (".md",)):
        t = read(p)
        if re.search(r"(?m)^status:\s*draft-hidden", t):
            continue
        body = " ".join(s for _n, s in visitor_text(p)[1:])  # the body, not the title
        n = words(body)
        if n > 70:
            r.problems.append(f"{ctx.rel(p)}: story screen of {n} words (at most 70, NFR-11)")
        g = fk_grade(body)
        if g > 8.0:
            over_grade.append(f"{p.name} {g:.1f}")
    for p in ctx.files(d / "code", (".md",)):
        body = " ".join(s for _n, s in visitor_text(p)[1:])
        if words(body) > 40:
            r.problems.append(
                f"{ctx.rel(p)}: code note of {words(body)} words (at most 40, CODE-2)"
            )
    for p in ctx.files(d / "captions", (".md",)):
        if p.name in ("disclosure.md", "about.md"):
            continue  # the full disclosure is 52 words by decision (UX 8.3); About is a document
        for n, line in visitor_text(p):
            if words(line) > 45:
                r.problems.append(f"{ctx.rel(p)}:{n}: caption of {words(line)} words (at most 45)")
    for p in ctx.files(ctx.web, (".html", ".js", ".mjs")):
        text = code_only(p, read(p))
        for m in PRIVACY.finditer(text):
            r.problems.append(f"{ctx.rel(p)}: privacy surface {m.group(0)!r} (NFR-16: no form, "
                              "analytics, QR, save UI or microphone)")  # fmt: skip
    if over_grade:
        r.human.append("Flesch-Kincaid above grade 8 by this gate's estimate (record an override "
                       "or simplify; owner: Doug): " + ", ".join(over_grade))  # fmt: skip
    r.evidence.append(
        "word limits: story 70, captions 45, code notes 40; privacy patterns over the web tree"
    )
    return r


GATES = {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6, "G7": g7, "G8": g8,
         "G9": g9, "G10": g10, "G11": g11}  # fmt: skip


def stage(image: Path) -> None:
    if image.exists():
        shutil.rmtree(image)
    p = subprocess.run(["bash", str(ROOT / "scripts/install-station.sh"), "--apply", "--root",
                        str(image), "--platform", "linux", "--allow-missing-build",
                        "--kiosk-user", "kiosk"], capture_output=True, text=True)  # fmt: skip
    if p.returncode != 0:
        raise SystemExit(f"release-gate: staging the install failed:\n{p.stdout}{p.stderr}")
    # the staged Linux image has no .so on a Mac; the host platform's production build stands in
    # for the profile check (G10 says which it used)


def record(results: list[Result], image: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()  # fmt: skip
    data = {"schema": "seastones.release-record/1", "commit": commit, "image": str(image),
            "gates": [x.as_dict() for x in results],
            "signoffs_required": ["HUM-09 docent handoff (Doug)", "HUM-10 counsel review",
                                  "HUM-11 content approvals (Doug)", "HUM-12 truthfulness read",
                                  "DES-3 listening gate (Nick + listener)"],
            "signoffs": []}  # fmt: skip
    (out / "release-record.json").write_text(json.dumps(data, indent=1) + "\n")
    lines = [f"# Release record (GAT-16): commit {commit[:12]}", "",
             f"Image scanned: `{image}`. Generated by scripts/release-gate.py. A release is refused "
             "while any gate is FAIL or any human sign-off below is unsigned.", "",
             "| Gate | Status | Title |", "|---|---|---|"]  # fmt: skip
    for x in results:
        lines.append(f"| {x.gate} | {x.status} | {x.title} |")
    for x in results:
        lines += ["", f"## {x.gate}: {x.status}", ""]
        lines += [f"- FAIL: {p}" for p in x.problems] + [f"- needs-human: {h}" for h in x.human]
        lines += [f"- evidence: {e}" for e in x.evidence] + [f"- note: {n}" for n in x.notes]
    lines += ["", "## Human sign-offs (name, date, hash reviewed)", ""]
    lines += [f"- [ ] {s}" for s in data["signoffs_required"]]
    (out / "release-record.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="release-gate.py")
    ap.add_argument("--image", type=Path, help="an installed tree (default: stage one)")
    ap.add_argument("--gates", default=",".join(GATES), help="comma-separated, e.g. G1,G4")
    ap.add_argument("--record-dir", type=Path, default=ROOT / "build" / "release")
    ap.add_argument("--no-record", action="store_true")
    args = ap.parse_args(argv)
    wanted = [g.strip().upper() for g in args.gates.split(",") if g.strip()]
    unknown = [g for g in wanted if g not in GATES]
    if unknown:
        ap.error(f"unknown gate(s): {', '.join(unknown)}")
    image = args.image
    if image is None:
        image = ROOT / "build" / "release" / "image"
        print(f"release-gate: staging the production install under {image}")
        stage(image)
    if not image.is_dir():
        print(f"release-gate: {image} is not a directory", file=sys.stderr)
        return 2
    ctx = Ctx(image.resolve())
    results = []
    for g in wanted:
        res = GATES[g](ctx)
        results.append(res)
        print(f"\n{res.gate} {res.status:<11} {res.title}")
        for p in res.problems:
            print(f"    FAIL: {p}")
        for h in res.human:
            print(f"    needs-human: {h}")
        for e in res.evidence:
            print(f"    evidence: {e}")
        for n in res.notes:
            print(f"    note: {n}")
    if not args.no_record:
        record(results, image, args.record_dir)
        print(f"\nrelease record: {args.record_dir / 'release-record.md'}")
    failed = [x.gate for x in results if x.status == "FAIL"]
    human = [x.gate for x in results if x.status == "NEEDS-HUMAN"]
    print(f"\nrelease-gate: {len(results) - len(failed) - len(human)} pass, {len(failed)} fail"
          f"{' (' + ', '.join(failed) + ')' if failed else ''}, {len(human)} need a person"
          f"{' (' + ', '.join(human) + ')' if human else ''}")  # fmt: skip
    if "G1" in failed:
        print("release-gate: THE RIGHTS GATE FAILED. Nothing Seastones-derived, no Layer 6 "
              "passage and no recording may be on the station. The build stops here.")  # fmt: skip
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
