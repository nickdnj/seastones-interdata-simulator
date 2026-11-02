"""The panel model: what each drawn lamp and readout shows, from engine data only (VS-14;
PR-04's start; ARCHITECTURE 4.4, 4.5, 7; M4-ARCH A-6 "src" provenance).

Nothing here invents a value. Every field of ``state`` comes from the engine's snapshot or
from the per-period samples the audio thread takes (src/host/rt/rt.c), and SOURCES says which.

* **Lamps (PR-01 is not built in the engine yet).** ADDRESS lamps are the bits of PC and DATA
  lamps the bits of the instruction word at PC (the UI lane's panel reading, content/rig/
  panel.md). Their duty fraction is the share of this frame's period-end samples in which the
  bit was set: at 32-frame periods that is about 25 samples per 1/60 s frame, so a lamp lit for
  half the instructions reads 0.5 give or take about 0.1. ``exact`` is true when the machine is
  halted, in STEP or CRAWL, or ran no period this frame; the values are then the bits of the
  current PC, 0 or 1. When the engine reports PR-01's true per-instruction duty, this changes
  to read it.
* **pc_hist:** the share of the last 250 ms of samples at each address (a sampled heat band).
* **scan_hz:** KEYS row reads per second over the last second, divided by the rows the program
  reads per lap (five rows for 37 keys: rig.s, read-the-keys).
* **watch.voices:** one entry per voice of the channel map (four on the floor's all-D/A map,
  eight on the latch map). A voice holds a note while its gate is high (its gate D/A channel
  above 2.5 V, or its gate-latch line); the note is its pitch channel's voltage at 1 V/oct
  (0 V is C0, MIDI 12; ARCHITECTURE 6.3), so a transposed note reads as the note
  that sounds. Null when the gate is low or the voltage is not on a semitone.
"""

from __future__ import annotations

from collections import deque

from . import engine as eng

# The six detents (ARCHITECTURE 7 v0.2, PRD/UX set; D-PLAN-8). Engine positions: RUN, a raw
# divisor for the four slowed ones (the engine's own enum still has /10../10000, PR-02), SINGLE.
# key_to_sound_ms are ARCHITECTURE 7's ESTIMATE figures; PR-03 replaces them by measurement.
SPEEDS = [
    {"id": "run", "label": "RUN", "ratio": 1.0, "key_to_sound_ms": 16, "divisor": 1},
    {"id": "div30", "label": "1/30", "ratio": 1 / 30, "key_to_sound_ms": 23, "divisor": 30},
    {"id": "div300", "label": "1/300", "ratio": 1 / 300, "key_to_sound_ms": 90, "divisor": 300},
    {"id": "div3000", "label": "1/3000", "ratio": 1 / 3000, "key_to_sound_ms": 800,
     "divisor": 3000},
    {"id": "crawl", "label": "CRAWL", "ratio": 1 / 30000, "key_to_sound_ms": 6000,
     "divisor": 30000},
    {"id": "step", "label": "STEP", "ratio": 0.0, "key_to_sound_ms": None, "divisor": 0},
]  # fmt: skip
SPEED_BY_ID = {s["id"]: s for s in SPEEDS}

ROWS_PER_LAP = 5  # rig.s reads rows 0-4 each lap (37 keys)
HIST_S = 0.25
SCAN_WINDOW_S = 1.0

DEFAULT_MAP = {"voices": 4, "gates": "dac", "pitch": [0, 1, 2, 3], "gate": [4, 5, 6, 7]}

SOURCES = {
    "pc psw r cc dr sr keys_raw keys_seen dac gates halted waiting muted frames cycles":
        "engine snapshot (sx_snapshot_read)",
    "lamps.addr": "bits of PC, share of per-period samples this frame (rt.c); PR-01 pending",
    "lamps.data": "bits of the image word at PC, share of the same samples; PR-01 pending",
    "pc_hist": "share of the last 250 ms of per-period PC samples per address",
    "scan_hz": "KEYS row reads per second (sx_keys_reads_count) / 5 rows per lap",
    "watch.voices": "per voice: pitch D/A volts x 12 (1 V/oct) while its gate is high",
    "speed": "the detent rigd commanded, once the engine reports that speed",
    "faults": "engine fault bits and rigd's supervision (ARCHITECTURE 8.2)",
}  # fmt: skip


def note_of(volts: float) -> int | None:
    """The MIDI note a 1 V/oct pitch voltage plays, if it is on a semitone. 0 V is C0, MIDI 12
    (the VCO's tune origin, 16.352 Hz; the pitch table gives note 60 4.0 V); a 12-bit converter
    is within 1.5 cents of the semitone (ARCHITECTURE 6.3)."""
    x = volts * 12.0
    n = round(x)
    return n + 12 if abs(x - n) < 0.3 and 0 <= n + 12 <= 127 else None


def bits16(v: int) -> list[int]:
    return [(v >> (15 - b)) & 1 for b in range(16)]


class Panel:
    def __init__(self, image: eng.Image | None, rate: int, cmap: dict | None = None,
                 word_bits: int = 12):  # fmt: skip
        self.image = image
        self.rate = rate
        self.cmap = cmap or DEFAULT_MAP
        del word_bits  # the volts already carry the converter's resolution
        self.hist: deque[tuple[int, int]] = deque()  # (frame, pc)
        self.reads: deque[tuple[int, int]] = deque()  # (frame, keys_reads)
        self.frame_samples: list[int] = []

    def word_at(self, pc: int) -> int:
        w = self.image.word(pc) if self.image else None
        return w if w is not None else 0

    def feed(self, samples: list[tuple[int, int, int, int]]) -> None:
        self.frame_samples = [pc for (_f, pc, halted, _r) in samples if not halted]
        for frame, pc, halted, reads in samples:
            if not halted:
                self.hist.append((frame, pc))
            self.reads.append((frame, reads))
        if samples:
            now = samples[-1][0]
            while self.hist and self.hist[0][0] < now - HIST_S * self.rate:
                self.hist.popleft()
            while self.reads and self.reads[0][0] < now - SCAN_WINDOW_S * self.rate:
                self.reads.popleft()

    def lamps(self, pc: int, exact: bool) -> dict:
        samples = self.frame_samples
        if exact or not samples:
            return {"addr": bits16(pc), "data": bits16(self.word_at(pc)), "exact": True}
        n = len(samples)
        addr = [0] * 16
        data = [0] * 16
        for p in samples:
            w = self.word_at(p)
            for b in range(16):
                addr[b] += (p >> (15 - b)) & 1
                data[b] += (w >> (15 - b)) & 1
        return {
            "addr": [round(x / n, 4) for x in addr],
            "data": [round(x / n, 4) for x in data],
            "exact": False,
        }

    def pc_hist(self) -> dict[str, float]:
        if not self.hist:
            return {}
        counts: dict[int, int] = {}
        for _f, pc in self.hist:
            counts[pc] = counts.get(pc, 0) + 1
        total = len(self.hist)
        return {f"{a:04X}": round(c / total, 4) for a, c in sorted(counts.items())}

    def scan_hz(self) -> float:
        if len(self.reads) < 2:
            return 0.0
        (f0, r0), (f1, r1) = self.reads[0], self.reads[-1]
        if f1 <= f0:
            return 0.0
        reads = (r1 - r0) & 0xFFFFFFFF
        return round(reads / ROWS_PER_LAP / ((f1 - f0) / self.rate), 1)

    def voices(self, snap) -> list[int | None]:
        out: list[int | None] = []
        for v in range(self.cmap["voices"]):
            g = self.cmap["gate"][v]
            high = (
                snap.dac_volts[g] > 2.5
                if self.cmap["gates"] == "dac"
                else snap.gates & (0x8000 >> g)
            )
            out.append(note_of(snap.dac_volts[self.cmap["pitch"][v]]) if high else None)
        return out
