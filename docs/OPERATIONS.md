# Running the station: for the docent

> DRAFT (kiosk lane, 2026-11-03). Not yet tried by a docent: the OPS-6 handoff test (HUM-09)
> decides whether these words work. The station hardware is not chosen yet, so the buttons
> named here are the plan, not the box.

## Start it

Switch it on at the wall. That is all. The station starts by itself and is ready to play in
about a minute (at most a minute and a half). You do not need a keyboard, a mouse or a password.
When the screen shows the rig and a key on the music keyboard makes a sound, it is working.

## Stop it

Press the computer's power button **once** and let go. The sound fades out, the screen goes
dark, and the computer switches itself off within a minute. Then you may switch off at the wall.

Do not hold the power button down unless the computer has not switched off after two minutes.
A power cut does no harm either: the station is built to be switched off at the wall.

It restarts itself every night at about 3:30 a.m. You will not notice.

## The staff screen

Hold your finger on the small logo for three seconds, then type the staff PIN. Visitors cannot
open it by accident. On the staff screen you can:

- see whether each part is working (green) or not (the line names the part);
- set the loudest the station may ever play, and play a 3-second **test tone** to hear it;
- set quieter hours, and how long the station waits before starting over for the next person;
- turn the sound **off** (mute) and on again;
- **restart the computer** (the emulated one: clears a stuck program, takes 2 seconds), or
  **restart the whole station** (takes about 10 seconds);
- save the current patch as a preset.

Press **Close** when you are done. Settings you change are kept when the station restarts.

## When it is silent

Work down this list and stop when it plays again.

1. **Is it muted?** Open the staff screen. If it says muted, turn the sound back on.
2. **Play the test tone** on the staff screen. If you hear it, the speakers are fine: go to 4.
3. **No test tone either:** check the volume knob on the amplifier and that the speaker and
   amplifier are plugged in and switched on. The staff screen's Audio line says if the computer
   cannot find its sound box; check that box's cable.
4. **The tone plays but the keys do not:** the staff screen's Keyboard line says if the music
   keyboard is missing; check its cable. The on-screen keys should still play.
5. **Press HOME** on the screen, or **Restart the computer** on the staff screen.
6. **Restart the whole station** on the staff screen. Wait a minute.
7. **Switch it off at the wall, count to ten, switch it on.** Wait two minutes.
8. Still silent: put the "resting" sign out and write down what the staff screen says. That is
   what the person who looks after the computer needs.

The station never plays a recording, so when something is wrong it is quiet, and the screen
says so. That is on purpose.

---

## For whoever installs or looks after the computer

Not for the docent. Commands are run from a copy of the repository on the station.

| Task | Command |
|---|---|
| Build for this machine | `make host-production notices` |
| See what installing would change (changes nothing) | `scripts/install-station.sh` |
| Install, or reinstall after an update (safe to repeat) | `sudo scripts/install-station.sh --apply` |
| Set or change the staff PIN (never kept in the repo) | `sudo python3 /opt/seastones/scripts/staff-pin.py /data/staff-pin` |
| Stop / start everything (Linux) | `sudo systemctl stop seastones-station.target` / `start` |
| Remove it (keeps settings, logs and the PIN) | `sudo scripts/uninstall-station.sh --apply` |
| Check the release gates | `make release-check` (record in `build/release/`) |

On a Mac the paths are `/opt/seastones` and `/Users/Shared/Seastones/data`; the parts run as
launch agents in the kiosk user's login, so turn on automatic login for that user, and
"Start up automatically after a power failure" in the Energy settings.

What runs: `rigd` (the emulated computer and the synthesizer; restarted within a second if it
stops, and killed and restarted if its heartbeat stops for 5 s), the page server, and the
browser in kiosk mode (reopened 3 s after it closes; closed and reopened if the page stops
beating for 60 s). On Linux a hardware watchdog restarts a computer that hangs completely.
Each boot's time from switch-on to playable is written to `<data>/log/boot.jsonl`. Logs are in
`<data>/log/` (five files of 2 MB each, then the oldest is dropped); on Linux, `journalctl -u
seastones-rigd` too. Set by hand once, it cannot be scripted: the computer's BIOS setting
"restore on AC power loss = on", and check the monitor comes back on by itself after a power cut.
