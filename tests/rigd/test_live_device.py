"""The live host on this machine's real audio output (VS-13; `make host-live-smoke`).

Opt-in (SX_LIVE_AUDIO=1): hosted CI has no sound card, and a developer's machine should not
open its output during an ordinary `make ci`. The device is given zeros (--silent-device), so
nothing is heard, while the timing is the real device's and the capture holds what the engine
rendered for it. `make run` is the audible version.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest
from conftest import rms, sounding

pytestmark = pytest.mark.skipif(
    os.environ.get("SX_LIVE_AUDIO") != "1", reason="opt-in: SX_LIVE_AUDIO=1 (make host-live-smoke)"
)


def test_the_real_device_runs_the_engine_and_a_key_sounds(rigd_factory, client_factory):
    r = rigd_factory("--audio", "auto", "--silent-device", "--no-midi", capture=True)
    banner = next(ln for ln in r.text().splitlines() if "profile" in ln)
    assert "Null" not in banner, banner  # the machine's own device (CoreAudio or ALSA)
    c = client_factory(r.url)
    hb = c.until(lambda m: m["t"] == "heartbeat" and m["audio_ok"], 3.0)
    assert hb["stages"]["output"]
    c.pump(0.3)
    f0, t0 = c.last("state")["frames"], time.monotonic()
    time.sleep(1.0)
    c.pump(0.3)
    f1, t1 = c.last("state")["frames"], time.monotonic()
    rate = int(banner.split(" Hz")[0].rsplit(" ", 1)[1])
    assert abs((f1 - f0) / rate / (t1 - t0) - 1.0) < 0.1, "the device's clock drives the engine"
    c.touch(1 << 12)
    st = c.until(lambda m: m["t"] == "state" and sounding(m))
    c.pump(0.6)
    x = r.at_frames(st["frames"] + rate // 10, st["frames"] + rate // 2)
    assert rms(x) > 0.01 and np.max(np.abs(x)) <= 0.2512, "a tone, under the -12 dBFS ceiling"
    print(f"\n{banner}")
