"""Fault codes, their staff lines, and the engine bits behind them (ARCHITECTURE 8.2; VS-17).

The visitor's words for each state are content (``content/captions/faults.md``: "The
computer is restarting.", "The sound is reconnecting.", the keyboard-lost line), so a content
editor can change them. The staff line is rigd's: it names the cause in a few words and goes in
``fault.staff_line``. Every code in ARCHITECTURE 8.2 has one (a test checks it).

No fault path makes any sound: there is no fallback sound source anywhere in the build
(KIOSK-4, FLT-12). A fault mutes or stops; it never substitutes.
"""

from __future__ import annotations

from . import engine as eng

CODES = (
    "program_stalled",
    "dsp_fault",
    "audio_device_missing",
    "audio_stalled",
    "midi_absent",
    "image_missing",
    "image_hash_mismatch",
    "config_invalid",
    "engine_load_failed",
    "ui_absent_muted",
    "audio_underruns",  # extension (KIOSK-5, NFR-6; QA-ADV-06): not yet in ARCHITECTURE 8.2
)
EXTENSION_CODES = ("audio_underruns",)

STAFF_LINES = {
    "program_stalled": "STAFF · program stalled (halted, trapped or not reading keys) · "
    "HOME reset in progress",
    "dsp_fault": "STAFF · synth fault (non-finite audio or DC) · muted, HOME reset in progress",
    "audio_device_missing": "STAFF · audio device missing · retrying every 2 s · check the "
    "USB audio interface",
    "audio_stalled": "STAFF · audio thread stalled · reopening the device",
    "midi_absent": "STAFF · MIDI keyboard unplugged · touch keys still play · replug it",
    "image_missing": "STAFF · program image missing · reinstall the image",
    "image_hash_mismatch": "STAFF · program image fails its checksum · reinstall the image",
    "config_invalid": "STAFF · rigd configuration invalid · see the rigd log",
    "engine_load_failed": "STAFF · engine library would not load · see the rigd log",
    "ui_absent_muted": "STAFF · no screen for 10 s (gone or frozen) · muted until the page returns",
    "audio_underruns": "STAFF · audio underruns (late callbacks) · check CPU load and the "
    "audio interface",
}

# Codes the engine reports in sx_snapshot.faults; CPU_STOPPED is a cause of program_stalled.
ENGINE_BITS = (
    (eng.FAULT_PROGRAM_STALLED | eng.FAULT_CPU_STOPPED, "program_stalled"),
    (eng.FAULT_DSP, "dsp_fault"),
    (eng.FAULT_IMAGE_MISSING, "image_missing"),
    (eng.FAULT_IMAGE_HASH, "image_hash_mismatch"),
)

# What each of the four recovery stages (heartbeat.stages, UX 5.8) needs to be free of.
STAGE_BLOCKERS = {
    "computer": {"engine_load_failed", "config_invalid"},
    "program": {"program_stalled", "image_missing", "image_hash_mismatch"},
    "synth": {"dsp_fault"},
    "output": {"audio_device_missing", "audio_stalled"},
}


def from_engine(bits: int) -> set[str]:
    return {code for mask, code in ENGINE_BITS if bits & mask}
