"""systemd's notify protocol, without a dependency (VS-17; ARCHITECTURE 4.5, 10).

``sd_notify(WATCHDOG=1)`` is sent only while the engine's frame counter advances and the
asyncio loop is responsive, so ``WatchdogSec=5`` in ``deploy/systemd/seastones-rigd.service``
restarts a hung rigd. ``NOTIFY_SOCKET`` unset (a developer's shell) makes every call a no-op;
the Mac's supervisor stub (``scripts/supervise-stub.py``) speaks the same datagrams.
"""

from __future__ import annotations

import os
import socket


class Notifier:
    def __init__(self, path: str | None = None):
        path = path if path is not None else os.environ.get("NOTIFY_SOCKET", "")
        self.addr = None
        self.sock = None
        if path:
            self.addr = "\0" + path[1:] if path.startswith("@") else path
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    @property
    def enabled(self) -> bool:
        return self.sock is not None

    def send(self, text: str) -> None:
        if self.sock is None:
            return
        try:
            self.sock.sendto(text.encode(), self.addr)
        except OSError:
            pass  # the supervisor is gone; it will notice by itself

    def ready(self, status: str = "") -> None:
        self.send("READY=1" + (f"\nSTATUS={status}" if status else ""))

    def watchdog(self) -> None:
        self.send("WATCHDOG=1")

    def status(self, text: str) -> None:
        self.send(f"STATUS={text}")
