"""KP-11: scripts/install-station.sh and uninstall-station.sh, staged under a temp root.

Nothing here touches this machine: every run is a dry run or ``--apply --root <tmp>``, which
writes only under the temp root and never runs a service manager, creates a user or chowns.
The units are linted by scripts/verify-units.sh (systemd-analyze, Docker on the Mac) and the
launch agents by plutil (here, when it exists).
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "install-station.sh"
UNINSTALL = ROOT / "scripts" / "uninstall-station.sh"
PLATFORMS = ("linux", "macos")
MAC_DATA = "/Users/Shared/Seastones/data"


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    p = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, SUDO_USER="kiosk"))  # fmt: skip
    assert p.returncode == 0, p.stdout + p.stderr
    return p


def install(root: Path, platform: str, *extra: str) -> subprocess.CompletedProcess:
    return run(INSTALL, "--platform", platform, "--root", str(root), "--allow-missing-build",
               "--kiosk-user", "kiosk", *extra)  # fmt: skip


def files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_the_default_is_a_dry_run_that_changes_nothing(tmp_path, platform):
    root = tmp_path / "root"
    p = install(root, platform)
    assert not root.exists(), "a dry run created files"
    assert "dry run" in p.stdout and "nothing was changed" in p.stdout
    want = ("/etc/systemd/system/seastones-rigd.service" if platform == "linux"
            else "/Library/LaunchAgents/local.seastones.rigd.plist")  # fmt: skip
    assert f"would install {want}" in p.stdout


@pytest.mark.parametrize("platform", PLATFORMS)
def test_apply_twice_changes_nothing_the_second_time(tmp_path, platform):
    root = tmp_path / "root"
    first = install(root, platform, "--apply")
    assert re.search(r"install: [1-9]\d* change\(s\) made", first.stdout)
    before = files(root)
    second = install(root, platform, "--apply")
    assert "install: 0 change(s) made" in second.stdout, second.stdout
    assert files(root) == before
    dest = root / "opt" / "seastones"
    for f in ("src/rigd/__main__.py", "src/web/serve.py", "src/web/index.html",
              "deploy/supervise.py", "deploy/kiosk.sh", "deploy/station.conf",
              "content-baked/kiosk.conf", "THIRD-PARTY-NOTICES", "docs/OPERATIONS.md",
              "VERSION", ".install-manifest"):  # fmt: skip
        assert (dest / f).is_file(), f
    assert os.access(dest / "deploy" / "kiosk.sh", os.X_OK)
    assert not list(dest.rglob("__pycache__"))
    data = root / (MAC_DATA.lstrip("/") if platform == "macos" else "data")
    assert (data / "content" / "kiosk.conf").is_file(), "the first install seeds the content"
    assert not (data / "staff-pin").exists(), "the installer never makes a PIN"


def test_linux_units_and_display_chain(tmp_path):
    root = tmp_path / "root"
    install(root, "linux", "--apply")
    units = root / "etc" / "systemd" / "system"
    for u in ("seastones-rigd.service", "seastones-web.service", "seastones-watchdog.timer",
              "seastones-reset.timer", "seastones-station.target", "seastones-playable.service"):  # fmt: skip
        assert (units / u).read_text() == _expected_unit(u), u
    xinitrc = (root / "home" / "kiosk" / ".xinitrc").read_text()
    assert "while true" in xinitrc and "/opt/seastones/deploy/kiosk.sh" in xinitrc
    assert "--autologin kiosk" in (units / "getty@tty1.service.d" / "autologin.conf").read_text()
    assert (
        "Storage=volatile" in (root / "etc/systemd/journald.conf.d/10-seastones.conf").read_text()
    )
    assert (
        "RuntimeWatchdogSec=60"
        in (root / "etc/systemd/system.conf.d/10-seastones-watchdog.conf").read_text()
    )
    lr = (root / "etc" / "logrotate.d" / "seastones").read_text()
    assert "size 2048k" in lr and "rotate 5" in lr
    nft = (root / "etc" / "nftables.d" / "seastones.nft").read_text()
    assert nft.count("policy drop") == 3, "input, forward and output all default-deny"
    assert 'include "/etc/nftables.d/seastones.nft"' in (root / "etc" / "nftables.conf").read_text()


def _expected_unit(name: str) -> str:
    """The repo's unit after the installer's station.conf substitutions (the defaults)."""
    return (ROOT / "deploy" / "systemd" / name).read_text()


def test_macos_agents_are_filled_and_lint(tmp_path):
    root = tmp_path / "root"
    install(root, "macos", "--apply", "--python", "/usr/local/bin/python3")
    agents = sorted((root / "Library" / "LaunchAgents").glob("local.seastones.*.plist"))
    assert [p.name.split(".")[2] for p in agents] == sorted(
        ["rigd", "web", "kiosk", "watchdog", "reset", "playable"])  # fmt: skip
    for p in agents:
        text = p.read_text()
        assert "@" not in text.split("<plist", 1)[1], f"unfilled placeholder in {p.name}"
        d = plistlib.loads(p.read_bytes())
        assert d["Label"] == p.stem and d["LimitLoadToSessionType"] == "Aqua"
        if shutil.which("plutil"):
            assert subprocess.run(["plutil", "-lint", str(p)], capture_output=True).returncode == 0
    rigd = plistlib.loads((root / "Library/LaunchAgents/local.seastones.rigd.plist").read_bytes())
    args = rigd["ProgramArguments"]
    assert args[0] == "/usr/local/bin/python3" and args[1] == "/opt/seastones/deploy/supervise.py"
    assert args[args.index("--watchdog-sec") + 1] == "5"  # rigd's heartbeat, as WatchdogSec=5
    assert rigd["KeepAlive"] is True and rigd["RunAtLoad"] is True
    assert f"{MAC_DATA}/staff-pin" in args
    reset = plistlib.loads((root / "Library/LaunchAgents/local.seastones.reset.plist").read_bytes())
    assert reset["StartCalendarInterval"] == {"Hour": 3, "Minute": 30}


def test_the_templates_lint_as_they_are():
    if not shutil.which("plutil"):
        pytest.skip("plutil is macOS-only (the installed copies are parsed with plistlib)")
    for p in sorted((ROOT / "deploy" / "launchd").glob("*.plist")):
        out = subprocess.run(["plutil", "-lint", str(p)], capture_output=True, text=True)
        assert out.returncode == 0, out.stdout + out.stderr


@pytest.mark.parametrize("platform", PLATFORMS)
def test_uninstall_removes_what_was_installed_and_keeps_the_state(tmp_path, platform):
    root = tmp_path / "root"
    install(root, platform, "--apply")
    data = root / (MAC_DATA.lstrip("/") if platform == "macos" else "data")
    (data / "staff.conf").write_text('{"cfg": {"ceiling_dba": 70}}')
    dry = run(UNINSTALL, "--platform", platform, "--root", str(root), "--kiosk-user", "kiosk")
    assert "would remove /opt/seastones/src/rigd/__main__.py" in dry.stdout
    assert (root / "opt" / "seastones" / "VERSION").exists(), "the dry run removed something"
    run(UNINSTALL, "--platform", platform, "--root", str(root), "--kiosk-user", "kiosk", "--apply")
    left = [p for p in files(root) if not p.startswith(str(data.relative_to(root)))]
    if platform == "linux":
        assert (root / "etc" / "nftables.conf").read_text().strip() == ""
        left.remove("etc/nftables.conf")  # the distribution's file, minus our include line
    assert left == [], left
    assert not (root / "opt" / "seastones").exists()
    assert (data / "staff.conf").exists(), "the museum's state survives an uninstall"
    again = run(UNINSTALL, "--platform", platform, "--root", str(root), "--kiosk-user", "kiosk",
                "--apply")  # fmt: skip
    assert "uninstall: 0 change(s) made" in again.stdout
    run(UNINSTALL, "--platform", platform, "--root", str(root), "--kiosk-user", "kiosk", "--apply",
        "--purge-data")  # fmt: skip
    assert not data.exists()


def test_a_reinstall_never_overwrites_the_stations_state(tmp_path):
    root = tmp_path / "root"
    install(root, "linux", "--apply")
    conf = root / "data" / "content" / "kiosk.conf"
    conf.write_text("idle_timeout_s = 120\n")  # the museum's own content stick copy
    (root / "data" / "staff-pin").write_text("sha256:00\n")
    out = install(root, "linux", "--apply")
    assert "install: 0 change(s) made" in out.stdout
    assert conf.read_text() == "idle_timeout_s = 120\n"
    assert (root / "data" / "staff-pin").read_text() == "sha256:00\n"


def test_a_file_dropped_from_the_tree_is_removed_on_reinstall(tmp_path):
    root = tmp_path / "root"
    install(root, "linux", "--apply")
    manifest = root / "opt" / "seastones" / ".install-manifest"
    stale = root / "opt" / "seastones" / "src" / "rigd" / "gone.py"
    stale.write_text("# from an older release\n")
    manifest.write_text(manifest.read_text() + "/opt/seastones/src/rigd/gone.py\n")
    out = install(root, "linux", "--apply")
    assert "+ remove /opt/seastones/src/rigd/gone.py" in out.stdout
    assert not stale.exists()


SECRET = re.compile(
    r"BEGIN [A-Z ]*PRIVATE KEY|(?:password|passwd|secret|api[_-]?key|auth[_-]?token)\w*\s*[:=]\s*"
    r"[\"']?[A-Za-z0-9+/_-]{6,}|\bpin\s*[:=]\s*[\"']?\d{4,8}\b|sha256:[0-9a-f]{64}",
    re.IGNORECASE,
)


def test_no_secrets_in_the_deploy_tree_or_an_install(tmp_path):
    """No PIN, password, key or token in what ships (the PIN is set on the station only)."""
    root = tmp_path / "root"
    install(root, "linux", "--apply")
    scanned = [p for p in (ROOT / "deploy").rglob("*") if p.is_file()]
    scanned += [ROOT / "scripts" / n for n in ("install-station.sh", "uninstall-station.sh",
                                               "station-lib.sh", "staff-pin.py")]  # fmt: skip
    scanned += [p for p in root.rglob("*") if p.is_file() and "content" not in p.parts]
    hits = []
    for p in scanned:
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits += [f"{p}: {m.group(0)}" for m in SECRET.finditer(text)]
    assert hits == [], hits


def test_every_path_a_unit_or_agent_runs_is_installed():
    """A unit pointing at a path nothing creates is the dullest way a kiosk fails to boot."""
    for platform, dest in (("linux", "/opt/seastones"), ("macos", "/opt/seastones")):
        paths = set(run(INSTALL, "--platform", platform, "--print-paths",
                        "--allow-missing-build").stdout.split())  # fmt: skip
        units = list((ROOT / "deploy" / "systemd").glob("*")) if platform == "linux" else \
            list((ROOT / "deploy" / "launchd").glob("*.plist"))  # fmt: skip
        for u in units:
            text = u.read_text().replace("@DEST@", dest)
            for ref in re.findall(r"/opt/seastones/[\w./-]+", text):
                if ref.endswith("/") or ref in ("/opt/seastones/src", "/opt/seastones/build/prod",
                                                "/opt/seastones/build/prod/program"):  # fmt: skip
                    continue  # a directory, which the files under it make
                if "build/prod" in ref:
                    continue  # built on the station (make host-production): preflight checks
                assert ref in paths, f"{u.name} runs {ref}, which {platform} install never makes"


def test_staff_pin_writes_a_hash_only(tmp_path):
    out = tmp_path / "staff-pin"
    p = subprocess.run(["python3", str(ROOT / "scripts" / "staff-pin.py"), str(out), "--stdin"],
                       input="4826\n", capture_output=True, text=True)  # fmt: skip
    assert p.returncode == 0, p.stderr
    text = out.read_text()
    assert text.startswith("sha256:") and "4826" not in text
    assert oct(out.stat().st_mode & 0o777) == "0o640"
    bad = subprocess.run(["python3", str(ROOT / "scripts" / "staff-pin.py"), str(out), "--stdin"],
                         input="12\n", capture_output=True, text=True)  # fmt: skip
    assert bad.returncode == 1 and out.read_text() == text
