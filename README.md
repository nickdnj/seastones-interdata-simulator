```
                         ⚡
              ╭──────────────────────╮
              │  THE 1974 SEASTONES  │
              │         RIG          │
              ╰──────────────────────╯
        a minicomputer, a keyboard, a pile of oscillators,
              and a stadium full of people
```

# The 1974 Seastones Rig

**A playable recreation of the computer-and-synthesizer rig that Ned Lagin took on tour with the
Grateful Dead in 1974.** An emulated Interdata minicomputer drives a virtual modular synthesizer
through a simulated 16-channel D/A converter. You press a key. A real program, running on a real
(emulated) 16-bit CPU, decides what voltage comes out. Nothing here plays itself.

> Built for a computer museum exhibit, and open to everyone. **Come play.**

**Not affiliated with or endorsed by Ned Lagin, the Grateful Dead or E-mu Systems.** This is our
own recreation, built from what is public. We do not have Ned's code, his wiring, or his channel
map. All of that is our design, and the machine's timing is an estimate.

---

## 🌹 Set I: the story

In 1974 a minicomputer stood on stage with the Grateful Dead. Ned Lagin played it like an
instrument: a keyboard fed the computer, and the computer set the voltages that drove a
synthesizer. Computers had made music in laboratories before. This one went on tour. On August 6,
1974, the rig was set up at Roosevelt Stadium in Jersey City, New Jersey: a computer, a keyboard
and a synthesizer, ready for a stadium. The music is *Seastones*.

The public record says the machine was an Interdata 7/16. Some memories say a Model 70 or 74.
We say so on the screen, because that is still open.

## 🌀 Set II: try it yourself

You need a Mac or a Linux box, a C compiler, `make`, `patch`, and Python 3.12 or newer. Sound comes out of
your default audio device. A USB MIDI keyboard works. So does your computer keyboard.

```bash
git clone https://github.com/nickdnj/seastones-interdata-simulator.git
cd seastones-interdata-simulator
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make run
```

`make run` builds the engine and the program (a few seconds), then prints two addresses:

| Open | What you get |
|---|---|
| `http://127.0.0.1:8080/` | the station page: the story, the front panel, the patch wall, the code |
| `http://127.0.0.1:8080/?dev=1` | the same, with your computer keys as a keyboard |

Press Ctrl-C to stop. If port 8080 is busy, set `SX_PORT_HTTP=8090` (and `SX_PORT_WS` for the sound
server). Keep the volume low the first time.

## 🌌 Space: how it works

```
 keys ──► emulated Interdata 16-bit CPU ──► device X'20' ──► 16 D/A channels
              (open-simh, our program)                           │
                                                                 ▼
          speakers ◄── mixer ◄── oscillators · filters · amps · envelopes
```

- **The CPU is real.** The Interdata 16-bit core is [open-simh](https://github.com/open-simh/simh),
  compiled into our engine, and checked in lockstep against stock `id16` so we know it behaves like
  the machine it claims to be.
- **The program is ours.** Written in Interdata assembly with our own assembler (`src/toolchain/sxasm`),
  it scans the keyboard, runs the voices, and writes sample values to the D/A converter.
- **The synth is a model.** Band-limited oscillators, filters, amplifiers and envelopes, patched by a
  graph you can see and rewire on the patch wall. It is a software model, not analog hardware: no
  drift, no analog noise.
- **The page shows its work.** Lamps, a speed control that slows the machine to a crawl, and a code
  view that steps through the program as it plays.
- **Real-time rules.** No allocation, locks, syscalls or logging on the audio path, and a lint that
  enforces it (`make rt-lint`).

Read the decisions in [`docs/adr/`](docs/adr) and the overview in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 🎼 The taping policy

This repo holds code and our own original material. It does **not** hold, and a guard script stops
anyone from committing:

- any recording, excerpt, spectrogram or transcription of *Seastones* or any Grateful Dead music;
- Interdata or Perkin-Elmer software, paper tapes or manual scans;
- audio of any kind, including our own renders.

`make private-check` scans every file, by name and by magic bytes, so a renamed recording does not
slip through; `make private-check-history` does the same for the whole history. Please run it
before you send anything.

## 🎸 Encore: help build it

Pull requests are welcome: the engine (C17), the toolchain and server (Python 3.12), the page
(plain JavaScript), the content text, and the tests.

```bash
make ci        # lint, rights check, notices check, all tests, lockstep, sanitizers
```

See [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md). The most useful help right now is hearing from
people who worked on, saw, or know about the original rig. If that is you, open an issue.

## Licence and credits

Our code is MIT-licensed ([`LICENSE`](LICENSE)). Vendored code and typefaces keep their own licences:
see [`THIRD-PARTY-NOTICES`](THIRD-PARTY-NOTICES). Built on open-simh by Robert M. Supnik and
contributors. Interdata, E-mu, ARP, Buchla, Fender Rhodes and Grateful Dead are names or trademarks of
their respective owners.

*Seastones* is Ned Lagin's work. Go listen to it.
