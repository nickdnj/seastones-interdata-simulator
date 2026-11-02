# tools/demo: the narrated demo video (for Nick)

`tools/demo/make-demo.sh` makes `build/demo/seastones-rig-demo.mp4`, about 5½ minutes:
the rig played on the real page against a real rigd, narrated, with the rig's own audio.
No media is ever committed (`build/` is ignored); only these scripts are.

| File | What |
|---|---|
| `segments.mjs` | The beats: each segment's narration, music-only gap, and on-screen actions (real QWERTY key presses, layers, preset chips, speed detents, STEP, Patch cable pulls). |
| `narrate.mjs` | Renders each narration with macOS `say` (Samantha) and measures it with ffprobe. |
| `drive.mjs` | Playwright on the real page (1280 × 720, `recordVideo`), scheduling each segment's actions to its measured length; writes a timeline. |
| `mix.py` | Aligns rigd's capture (channel 0, float32, 48 kHz) to the video by its first onset against the first key press; ducks it about 11 dB under speech; loudness −16 LUFS, true peak −2 dBTP; fades out; muxes H.264/AAC. |
| `check.py` | Watches and listens to the result: video-clock offset at the switch to Play, loudness, peak, silences over 3 s, and a contact sheet of one frame per segment. |
| `make-demo.sh` | Starts rigd (`--audio null --capture`, real time, nothing audible) and the page server on free ports, runs the above, and stops only what it started. |

Run `python3 tools/demo/check.py build/demo/work build/demo/seastones-rig-demo.mp4` after.

**What you hear:** only our own synthesis, made live by the emulated 7/16. No recording of
Seastones (or anything else) is used: none are on the machine, they are copyrighted, and the
project keeps recordings out of the exhibit and the repo.

**Needs:** macOS (`say`), ffmpeg/ffprobe, Node with `tests/web`'s Playwright, numpy. If ffmpeg
lacks `drawtext` (no freetype), there is no title overlay; the page's own header titles it.
