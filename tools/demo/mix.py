#!/usr/bin/env python3
"""mix.py: put the demo together (tools/demo/README.md).

    python3 tools/demo/mix.py <workdir> <capture.f32> <out.mp4>

* The rig's own audio is rigd's capture (channel 0, float32, 48 kHz, real time). Its first
  onset is aligned to the first key press in the video timeline (plus about 20 ms, the rig's
  key-to-sound time), so what you hear lines up with what you see.
* The narration segments go in at their segment starts. The rig is ducked about 11 dB under
  speech (a smoothed speech envelope, so it breathes rather than pumps), then the mix is
  loudness-normalised (-16 LUFS, true peak -2 dBTP) and muxed with the video as H.264/AAC.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

RATE = 48000
KEY_TO_SOUND = 0.02
DUCK_DB = -11.0
RIG_RMS_DB = -24.0  # rig level before ducking, measured over the sounding parts
NAR_RMS_DB = -20.0


def read_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def db(x: float) -> float:
    return 10 ** (x / 20)


def smooth_env(x: np.ndarray, attack_s: float, release_s: float) -> np.ndarray:
    """A peak follower on |x|, block-wise (10 ms) so it is quick in numpy."""
    blk = RATE // 100
    n = len(x) // blk + 1
    padded = np.zeros(n * blk)
    padded[: len(x)] = np.abs(x)
    peaks = padded.reshape(n, blk).max(axis=1)
    a = np.exp(-0.01 / attack_s)
    r = np.exp(-0.01 / release_s)
    env = np.zeros(n)
    e = 0.0
    for i, p in enumerate(peaks):
        e = a * e + (1 - a) * p if p > e else r * e + (1 - r) * p
        env[i] = e
    return np.repeat(env, blk)[: len(x)]


def main() -> int:
    work, cap, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    tl = json.loads((work / "timeline.json").read_text())
    video_len = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(work / "video.webm"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        or tl["end"]
    )
    n = int(video_len * RATE)

    # ---- the rig, aligned by its first onset
    rig = np.fromfile(cap, dtype=np.float32).astype(np.float64)
    rig = rig - np.median(rig[:RATE]) if len(rig) > RATE else rig
    above = np.flatnonzero(np.abs(rig) > 0.003)
    if not len(above):
        print("error: the capture is silent")
        return 1
    onset = above[0] / RATE
    first_key = min(k[0] for k in tl["keys"] if k[1] == "down")
    shift = first_key + KEY_TO_SOUND - onset  # capture time + shift = video time
    print(
        f"capture {len(rig) / RATE:.1f} s, onset at {onset:.3f} s; first key at {first_key:.3f} s; shift {shift:+.3f} s"
    )
    track = np.zeros(n)
    s = int(round(shift * RATE))
    src0, dst0 = (0, s) if s >= 0 else (-s, 0)
    m = min(len(rig) - src0, n - dst0)
    if m > 0:
        track[dst0 : dst0 + m] = rig[src0 : src0 + m]
    sounding = np.abs(track) > 0.003
    rms = np.sqrt(np.mean(track[sounding] ** 2)) if sounding.any() else 1.0
    track *= db(RIG_RMS_DB) / rms
    print(
        f"rig: peak {20 * np.log10(np.max(np.abs(rig)) + 1e-12):.1f} dBFS raw, sounding {sounding.mean() * 100:.0f}% of the video"
    )

    # ---- the narration, at each segment's start
    nar = np.zeros(n)
    for seg in tl["segments"]:
        x = read_audio(Path(seg["narration"]))
        a = int(seg["start"] * RATE)
        b = min(n, a + len(x))
        nar[a:b] += x[: b - a]
    voiced = np.abs(nar) > 0.002
    nrms = np.sqrt(np.mean(nar[voiced] ** 2)) if voiced.any() else 1.0
    nar *= db(NAR_RMS_DB) / nrms

    # ---- duck the rig under speech
    env = smooth_env(nar, attack_s=0.04, release_s=0.6)
    speaking = np.clip(env / (db(NAR_RMS_DB) * 0.5), 0, 1)
    gain = 1.0 - (1.0 - db(DUCK_DB)) * speaking
    mix = nar + track * gain
    peak = np.max(np.abs(mix))
    if peak > 0.9:
        mix *= 0.9 / peak
    wav = work / "mix.f32"
    mix.astype(np.float32).tofile(wav)

    # ---- mux: H.264 + AAC, loudness-normalised, a title over the lead-in
    title = "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='The 1974 Seastones Rig  ·  a demo':fontcolor=white:fontsize=34:x=(w-text_w)/2:y=h-90:box=1:boxcolor=black@0.55:boxborderw=14:enable='lt(t,6)'"
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-i",
        str(work / "video.webm"),
        "-f",
        "f32le",
        "-ar",
        str(RATE),
        "-ac",
        "1",
        "-i",
        str(wav),
        "-vf",
        title,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-af",
        f"loudnorm=I=-16:TP=-2:LRA=11,afade=t=out:st={max(0.0, video_len - 2.5):.2f}:d=2.5",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]
    filters = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    if (
        " drawtext " not in filters
    ):  # an ffmpeg built without freetype: the page's own header titles it
        print("no drawtext in this ffmpeg: no title overlay")
        i = cmd.index("-vf")
        del cmd[i : i + 2]
    subprocess.run(cmd, check=True)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
