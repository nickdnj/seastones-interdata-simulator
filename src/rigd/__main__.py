"""rigd's command line (VS-14). ``PYTHONPATH=src python3 -m rigd --help``.

Defaults are the station's: loopback port 7690, the default audio device, 128-frame periods,
MIDI on, mute after 10 s without a page, the staff ceiling at -12 dBFS. The test profile adds
developer switches (``--test-hooks``, ``--no-ui-mute``, ``--capture``); a production build
refuses them, so a kiosk cannot be started in a test configuration by mistake (VS-27).
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import signal
import sys
from pathlib import Path

from . import engine as eng
from .rig import AudioConfig, Rig, RigConfig
from .station import Station, StationConfig

ROOT = eng.ROOT
PRODUCTION_REFUSES = ("test_hooks", "no_ui_mute", "capture", "latency_log")


def read_kiosk_conf(path: Path) -> dict[str, str]:
    """``key = value`` lines (content/kiosk.conf, ARCHITECTURE 11.2); missing file: {}."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rigd", description="The Seastones rig engine host.")
    p.add_argument("--host", default="127.0.0.1", help="loopback only (the station is offline)")
    p.add_argument("--port", type=int, default=7690)
    p.add_argument("--build", type=Path, default=ROOT / "build", help="build tree (lib, program)")
    p.add_argument("--lib", type=Path, help="libsxhost (default: <build>/host/libsxhost.*)")
    p.add_argument("--image", type=Path, help="default: <build>/program/rig.img.json")
    p.add_argument("--listing", type=Path, help="default: <build>/program/rig.lst.json")
    p.add_argument("--content", type=Path, default=ROOT / "content", help="for kiosk.conf")
    p.add_argument("--audio", choices=("auto", "null"), default="auto")
    p.add_argument("--device", default="", help="output device name or id substring (hw:1,0)")
    p.add_argument("--rate", type=int, default=0, help="0 = the device's rate")
    p.add_argument("--period", type=int, default=128)
    p.add_argument("--periods", type=int, default=2)
    p.add_argument("--sub-period", type=int, default=32, help="engine period inside a callback")
    p.add_argument(
        "--silent-device",
        action="store_true",
        help="render and tap as usual, give the device zeros (quiet measurements)",
    )
    p.add_argument("--no-midi", action="store_true")
    p.add_argument("--midi-base-note", type=int, default=48, help="the MIDI note of key 0")
    p.add_argument(
        "--midi-source",
        default="",
        help="connect only MIDI sources whose name contains this (default: all)",
    )
    p.add_argument("--keys", type=int, default=37)
    p.add_argument(
        "--ceiling-dbfs",
        type=float,
        default=-1.0,
        help="a cap in dBFS on top of the staff ceiling (default: none, -1 = hard max)",
    )
    p.add_argument(
        "--ceiling-max-dba",
        type=int,
        default=78,
        help="dBA at -1 dBFS through the sealed amplifier (NFR-5, measured at install)",
    )
    p.add_argument("--ceiling-dba", type=int, default=67, help="the staff ceiling until changed")
    p.add_argument(
        "--data",
        type=Path,
        default=ROOT / "build" / "run" / "data",
        help="staff.conf and staff-saved presets (/data on the station)",
    )
    p.add_argument("--preset", help="the patch at start and after HOME (kiosk.conf preset_order)")
    p.add_argument("--map", default="all-da-4", help="the channel map the image was built for")
    p.add_argument("--ui-absent-mute-s", type=float, default=10.0)
    p.add_argument("--staff-pin-file", type=Path, help="a file holding the staff PIN")
    # test profile only
    p.add_argument("--no-ui-mute", action="store_true", help="test profile: never mute for no page")
    p.add_argument("--test-hooks", action="store_true", help="test profile: accept test.inject")
    p.add_argument("--capture", type=Path, help="test profile: raw float32 of the output")
    p.add_argument("--latency-log", type=Path, help="test profile: one JSON line per key press")
    return p  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not loopback(args.host):
        print("rigd: refusing to listen beyond loopback (the station is offline)", file=sys.stderr)
        return 2
    lib = args.lib or eng.default_lib_path(args.build)
    name = "rig8" if args.map == "latch-8" else "rig"
    image = args.image or args.build / "program" / f"{name}.img.json"
    listing = args.listing or args.build / "program" / f"{name}.lst.json"
    conf = read_kiosk_conf(args.content / "kiosk.conf")
    errors = []
    try:
        held_s = float(conf.get("held_key_release_s", 60))
        if not 1.0 <= held_s <= 3600.0:
            raise ValueError
    except ValueError:
        errors.append(f"kiosk.conf held_key_release_s = {conf.get('held_key_release_s')!r}")
        held_s = 60.0
    order = [s.strip() for s in conf.get("preset_order", "").split(",") if s.strip()]
    preset = args.preset or (order[0] if order else None)
    settings = {"idle_timeout_s": 90, "reduced_motion": False, "review_mode": False,
                "attract_sound": False}  # fmt: skip
    try:
        settings["idle_timeout_s"] = max(30, min(600, int(conf.get("idle_timeout_s", 90))))
    except ValueError:
        errors.append(f"kiosk.conf idle_timeout_s = {conf.get('idle_timeout_s')!r}")
    for k in ("reduced_motion", "attract_sound"):
        settings[k] = conf.get(k, "off").lower() in ("on", "yes", "true", "1")
    pin = None
    if args.staff_pin_file:
        try:
            pin = args.staff_pin_file.read_text().strip() or None
        except OSError:
            pin = None

    rig = Rig(
        RigConfig(
            lib=lib,
            image=image,
            audio=AudioConfig(
                backend=args.audio,
                device=args.device,
                rate=args.rate,
                period=args.period,
                periods=args.periods,
                sub_period=args.sub_period,
                silent_device=args.silent_device,
            ),
            midi=not args.no_midi,
            midi_base_note=args.midi_base_note,
            midi_source=args.midi_source,
            keys=args.keys,
            ceiling_dbfs=args.ceiling_dbfs,
            capture=args.capture,
        )
    )
    # The profile is the library's; a production build refuses the developer switches.
    try:
        rig.load()
    except eng.EngineLoadError:
        pass  # Station.start reports engine_load_failed
    if rig.profile == "production":
        bad = [f"--{k.replace('_', '-')}" for k in PRODUCTION_REFUSES if getattr(args, k)]
        if bad:
            print(f"rigd: the production profile refuses {', '.join(bad)}", file=sys.stderr)
            return 2
    rig.lib = None  # Station.start loads it again, with the rest of start-up

    st = Station(
        StationConfig(
            host=args.host,
            port=args.port,
            listing=listing,
            ui_absent_mute_s=0.0 if args.no_ui_mute else args.ui_absent_mute_s,
            held_key_release_s=held_s,
            keys=args.keys,
            test_hooks=args.test_hooks,
            staff_pin=pin,
            latency_log=args.latency_log,
            config_errors=errors,
            data_dir=args.data,
            content=args.content,
            preset=preset,
            map_name=args.map,
            ceiling_max_dba=args.ceiling_max_dba,
            ceiling_dba=args.ceiling_dba,
            ceiling_cap_dbfs=args.ceiling_dbfs,
            settings=settings,
        ),
        rig,
    )

    async def go() -> int:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        return await st.run(stop)

    try:
        return asyncio.run(go())
    except OSError as exc:
        print(f"rigd: {exc}", file=sys.stderr)
        st.shutdown()
        return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
