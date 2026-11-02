#!/usr/bin/env python3
"""check.py: look at and listen to the finished demo before anyone else does.

    python3 tools/demo/check.py <workdir> <out.mp4>

* Sync: the frame where the picture jumps to the Play screen, against the time drive.mjs
  switched to it, gives the video clock's offset from the timeline (should be small).
* Loudness (ebur128), peak (volumedetect), silences over 3 s (silencedetect).
* A contact sheet of one frame per segment, in <workdir>/sheet.png, to eyeball.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np


def ff(*args: str) -> str:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", *args], capture_output=True, text=True
    ).stderr


def frames_gray(mp4: Path, t0: float, t1: float, fps: int = 20) -> np.ndarray:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{t0}",
            "-to",
            f"{t1}",
            "-i",
            str(mp4),
            "-vf",
            f"fps={fps},scale=160:90,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 90, 160).astype(np.float64)


def main() -> int:
    work, mp4 = Path(sys.argv[1]), Path(sys.argv[2])
    tl = json.loads((work / "timeline.json").read_text())
    seg = {s["id"]: s for s in tl["segments"]}
    dur = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(mp4),
            ],
            capture_output=True,
            text=True,
        ).stdout
    )
    print(f"duration {dur:.1f} s ({int(dur // 60)}:{int(dur % 60):02d})")

    # sync: the attract -> Play switch
    switch = seg["honest"]["start"] + seg["honest"]["slot"] - 1.5
    f = frames_gray(mp4, switch - 2, switch + 2)
    jump = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    seen = switch - 2 + (int(np.argmax(jump)) + 1) / 20
    print(
        f"Play screen switched at {switch:.2f} s (timeline), seen at {seen:.2f} s (video): offset {seen - switch:+.2f} s"
    )

    # level, peak, silence
    e = ff("-i", str(mp4), "-af", "ebur128=peak=true", "-f", "null", "-")
    i_lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", e)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", e)
    print(
        f"integrated {i_lufs[-1] if i_lufs else '?'} LUFS, true peak {tp[-1] if tp else '?'} dBFS"
    )
    v = ff("-i", str(mp4), "-af", "volumedetect", "-f", "null", "-")
    print("volumedetect:", " ".join(re.findall(r"(mean_volume: \S+ dB|max_volume: \S+ dB)", v)))
    s = ff("-i", str(mp4), "-af", "silencedetect=noise=-45dB:d=3", "-f", "null", "-")
    sil = re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)", s)
    print(
        f"silences over 3 s: {len(sil)}"
        + "".join(f"\n  {float(a):.1f}-{float(b):.1f} s" for a, b in sil)
    )

    # contact sheet: one frame two-thirds into each segment
    pics = []
    for x in tl["segments"]:
        t = x["start"] + x["slot"] * 0.66
        p = work / f"sheet-{x['id']}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                f"{t}",
                "-i",
                str(mp4),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:-1",
                str(p),
            ],
            check=True,
        )
        pics.append(p)
    inputs = []
    for p in pics:
        inputs += ["-i", str(p)]
    n = len(pics)
    layout = "|".join(f"{(i % 4) * 480}_{(i // 4) * 270}" for i in range(n))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            f"xstack=inputs={n}:layout={layout}:fill=black",
            str(work / "sheet.png"),
        ],
        check=True,
    )
    print(f"contact sheet: {work / 'sheet.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
