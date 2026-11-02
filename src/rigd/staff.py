"""The staff session and settings (KP-07, KP-08, KP-09, CT-07, STAFF-1, STAFF-2; ENG-06).

Protocol: the UI lane's proposal, adopted into src/rigd/schema/protocol-v1.json. ``staff.auth``
with the PIN opens a session on that connection only; every other ``staff.*`` needs one
(``nack not_staff``). Five wrong PINs lock the staff screen for 30 s. The PIN is never in the
repo: rigd reads it from ``--staff-pin-file``, which holds either the digits or
``sha256:<hex>`` of them; with no file, no session can open.

Settings persist in ``<data>/staff.conf`` (JSON, written atomically) and survive restarts.

The ceiling is set in dBA (STAFF-2). The engine's limiter works in dBFS, so rigd maps
``dBFS = -1 - (ceiling_max_dba - ceiling_dba)``: the hardware maximum, ``ceiling_max_dba``, is
what the sealed amplifier gives at the engine's hard maximum of -1 dBFS, measured at
installation with a sound-level meter (NFR-5). Until that measurement, the defaults
(78 dBA maximum, 67 dBA ceiling) keep the output at -12 dBFS. Quiet hours lower it further
while the local time is inside them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from pathlib import Path

from . import schema

HARD_MAX_DBFS = -1.0
TRIES = 5
LOCKOUT_S = 30.0


def pin_matches(pin: str, spec: str | None) -> bool:
    if not spec:
        return False
    if spec.startswith("sha256:"):
        return hmac.compare_digest(hashlib.sha256(pin.encode()).hexdigest(), spec[7:].lower())
    return hmac.compare_digest(pin.encode(), spec.encode())


class Staff:
    def __init__(self, data_dir: Path | None, pin_spec: str | None, settings: dict,
                 ceiling_max_dba: int = 78, ceiling_dba: int = 67):  # fmt: skip
        self.path = Path(data_dir) / "staff.conf" if data_dir else None
        self.pin_spec = pin_spec
        self.tries = TRIES
        self.lock_until = 0.0
        self.cfg = {
            "ceiling_dba": min(ceiling_dba, ceiling_max_dba),
            "ceiling_max_dba": ceiling_max_dba,
            "quiet_hours": {"from": "00:00", "to": "00:00", "dba": min(60, ceiling_dba)},
            "muted": False,
        }
        self.settings = dict(settings)
        self.load()

    # ------------------------------------------------------------ persistence

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return  # a damaged file: the defaults stand (the staff screen can set them again)
        if not isinstance(saved, dict):
            return

        # Each saved value must be one the staff screen itself could have sent (the protocol's
        # own bounds); anything else keeps its default. A hand-edited or damaged file must not
        # stop rigd from starting, nor set what the protocol refuses (QA-ADV-03).
        def ok(msg: dict) -> bool:
            return not schema.validate("client", {"v": 1, "id": 1, **msg})

        cfg = saved.get("cfg") if isinstance(saved.get("cfg"), dict) else {}
        c = cfg.get("ceiling_dba")
        if ok({"t": "staff.ceiling", "dba": c}):
            self.cfg["ceiling_dba"] = c
        q = cfg.get("quiet_hours")
        if isinstance(q, dict) and ok(
            {"t": "staff.quiet_hours", **{k: q.get(k) for k in ("from", "to", "dba")}}
        ):
            self.cfg["quiet_hours"] = {k: q[k] for k in ("from", "to", "dba")}
        if isinstance(cfg.get("muted"), bool):
            self.cfg["muted"] = cfg["muted"]
        self.cfg["ceiling_dba"] = min(int(self.cfg["ceiling_dba"]), self.cfg["ceiling_max_dba"])
        settings = saved.get("settings") if isinstance(saved.get("settings"), dict) else {}
        for k, v in settings.items():
            if k not in self.settings or type(v) is not type(self.settings[k]):
                continue
            if k == "idle_timeout_s" and not ok({"t": "staff.idle_timeout", "s": v}):
                continue
            self.settings[k] = v

    def save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"cfg": self.cfg, "settings": self.settings}, indent=1))
            tmp.replace(self.path)
        except OSError:
            pass  # /data read-only or full: settings hold for this run (ENG-09's spirit)

    # ------------------------------------------------------------ the session

    def lockout_s(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        return int(min(LOCKOUT_S, max(0.0, -(-(self.lock_until - now) // 1))))

    def auth(self, pin: str) -> bool:
        now = time.monotonic()
        if now < self.lock_until or not self.pin_spec:
            return False
        if pin_matches(pin, self.pin_spec):
            self.tries = TRIES
            return True
        self.tries -= 1
        if self.tries <= 0:
            self.lock_until = now + LOCKOUT_S
            self.tries = TRIES
        return False

    def message(self, authed: bool, saved: str | None = None, with_saved: bool = False) -> dict:
        m = {"v": 1, "t": "staff", "authed": authed, "tries_left": self.tries,
             "lockout_s": self.lockout_s()}  # fmt: skip
        if authed:
            m["settings"] = {**self.cfg, "quiet_hours": dict(self.cfg["quiet_hours"])}
        if with_saved:
            m["saved"] = saved
        return m

    def settings_message(self) -> dict:
        return {"v": 1, "t": "settings", **self.settings}

    # ------------------------------------------------------------ the ceiling

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        q = self.cfg["quiet_hours"]
        if q["from"] == q["to"]:
            return False
        hm = (now or datetime.now()).strftime("%H:%M")
        return q["from"] <= hm < q["to"] if q["from"] < q["to"] else hm >= q["from"] or hm < q["to"]

    def ceiling_dbfs(self, now: datetime | None = None) -> float:
        dba = self.cfg["ceiling_dba"]
        if self.in_quiet_hours(now):
            dba = min(dba, self.cfg["quiet_hours"]["dba"])
        return HARD_MAX_DBFS - (self.cfg["ceiling_max_dba"] - dba)
