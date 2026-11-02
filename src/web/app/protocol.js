// protocol.js: every message the page can send to rigd, and nothing else (CODE-4).
//
// This is the whole client side of protocol v1 for the visitor UI. There is deliberately
// no deposit, no switch-register write, no memory write, no passage and no staff command
// here: a visitor cannot change the program (CODE-4), and layer 6 has no code path in v1
// (KP-01, SEA-3). The code-view UI test enumerates this file and the messages
// actually sent.

import { post, command } from "./rig.js";

const hex64 = (bits) => BigInt.asUintN(64, bits).toString(16).toUpperCase().padStart(16, "0");

/** The on-screen keyboard's whole state, as a level (INPUT-4). */
export const keysTouch = (bits) => post({ t: "keys.touch", bits: hex64(bits) });
export const speed = (position) => command({ t: "machine.speed", position });
export const step = () => command({ t: "machine.step" });
export const home = () => command({ t: "machine.home" });
export const connect = (from, to) => command({ t: "patch.connect", from, to });
export const disconnect = (from, to) => command({ t: "patch.disconnect", from, to });
export const load = (slug) => command({ t: "patch.load", slug });
// The visitor's own volume, below the staff ceiling, and a visible mute (AUDIO-3). The
// message names are the host lane's: audio.volume (dB below the staff ceiling) and audio.mute.
export const volume = (db) => command({ t: "audio.volume", db });
export const mute = (on) => command({ t: "audio.mute", on });

export const MESSAGE_TYPES = [
  "keys.touch", "machine.speed", "machine.step", "machine.home",
  "patch.connect", "patch.disconnect", "patch.load", "audio.volume", "audio.mute",
];
