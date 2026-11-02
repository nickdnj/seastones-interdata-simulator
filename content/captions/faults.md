title: Fault and starting states
status: ready
note: UX 5.8 and 8.8, ARCHITECTURE 8.2. Visitor lines are calm and blame nobody. Each staff line names the cause and the runbook page; it is small and visible to visitors, so it stays short and non-alarming.

## kicker
text: Resting for a moment

## computer
text: The computer is restarting.
meta: Give it a moment. Keys are paused, and nothing will sound until it is back.

## sound
text: The sound is reconnecting.
meta: The computer is fine. The speakers lost their connection, and it is finding them again.

## starting
text: Waking up.
meta: The computer is starting. This takes about a minute.

## stage-computer
text: The computer

## stage-program
text: Its program

## stage-synth
text: The synthesizer

## stage-output
text: The sound output

## keyboard-lost
text: The keyboard has gone quiet. The touch keys on screen still work.

## staff-disconnected
text: STAFF · bridge connection lost · reconnecting · runbook p.1, "No sound"

## staff-starting
text: STAFF · waiting for rigd · runbook p.1, "Starting"

## staff-program_stalled
text: STAFF · program stalled, reloading the image · runbook p.2

## staff-dsp_fault
text: STAFF · synthesizer fault, resetting · runbook p.2

## staff-audio_device_missing
text: STAFF · audio device lost · retrying every 2 s · runbook p.1, "No sound"

## staff-audio_stalled
text: STAFF · audio thread stalled, reopening the device · runbook p.1

## staff-midi_absent
text: STAFF · USB-MIDI keyboard lost · replug and it recovers by itself

## staff-image_missing
text: STAFF · program image missing · runbook p.3

## staff-image_hash_mismatch
text: STAFF · program image does not match its hash · runbook p.3

## staff-config_invalid
text: STAFF · configuration file invalid · runbook p.3

## staff-engine_load_failed
text: STAFF · engine library would not load · runbook p.3

## staff-ui_absent_muted
text: STAFF · muted while no screen was connected · clears on reconnect

## staff-content
text: STAFF · the content index could not be read · runbook p.4

## staff-protocol_mismatch
text: STAFF · rigd speaks protocol v{v}, this page v1 · install matching versions · runbook p.3

## staff-audio_underruns
text: STAFF · audio underruns: late callbacks, a storm · check CPU load · runbook p.1, "Crackles"
