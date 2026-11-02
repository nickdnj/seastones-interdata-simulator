// errors.js: the fault and starting states (KP-05; KIOSK-4, KIOSK-5, INPUT-3, UX 5.8).
//
// Honest, quiet, self-recovering. A calm card over the dimmed stage: one plain visitor
// sentence, four stage markers that tick only as each part REALLY comes back (from the
// heartbeat's `stages`), and one small staff line naming the cause and the runbook page.
// The dock's layer tabs are disabled, HOME stays live, the footer stays. The page never
// makes a sound and never shows a stale or invented value: when the link to rigd is down
// every live view is blank, because rig.js has dropped the state (UI-34).
//
// The keyboard-lost notice is not a fault: one line above the touch keys (INPUT-3).

import { el } from "./blocks.js";
import { S, M } from "./strings.js";
import * as rig from "./rig.js";

const SOUND = new Set(["audio_device_missing", "audio_stalled"]);
// staff-only: the keyboard line, the no-screen mute, and an underrun storm (the staff screen
// and its staff line show it; the sound carries on, so a visitor card would be untrue)
const NOTICE_ONLY = new Set(["midi_absent", "ui_absent_muted", "audio_underruns"]);
const STAGES = ["computer", "program", "synth", "output"];

/** What the screen should say now, or null when all is well. Pure; tested directly. */
export function classify({ connected, everConnected, heartbeat, faults, mismatch = null }) {
  // rigd answers in another protocol version: it will not fix itself, so staff must see why
  if (connected && mismatch !== null) return { variant: "computer", staff: "staff-protocol_mismatch", stages: null, vars: { v: mismatch } };
  if (!connected) {
    return everConnected
      ? { variant: "computer", staff: "staff-disconnected", stages: null }
      : { variant: "starting", staff: "staff-starting", stages: null };
  }
  const codes = new Set([...(faults || []), ...((heartbeat && heartbeat.faults) || [])]);
  for (const c of NOTICE_ONLY) codes.delete(c);
  if (heartbeat && !heartbeat.audio_ok) codes.add("audio_device_missing");
  if (!codes.size) {
    const st = heartbeat && heartbeat.stages;
    if (st && !STAGES.every((k) => st[k])) return { variant: "starting", staff: "staff-starting", stages: st };
    return null;
  }
  const code = [...codes].sort((a, b) => (SOUND.has(a) ? 1 : 0) - (SOUND.has(b) ? 1 : 0))[0];
  return { variant: SOUND.has(code) && codes.size === 1 ? "sound" : SOUND.has(code) ? "sound" : "computer", staff: `staff-${code}`, code, stages: heartbeat && heartbeat.stages };
}

let host = null;
let shown = null;
let parts = null;

export function install() {
  host = document.getElementById("fault");
  host.textContent = "";
  const card = el("div", "card fcard");
  const kick = el("div", "kick", S("faults", "kicker"));
  const h = el("h2");
  h.id = "fault-headline";
  const sentence = el("p", "sentence");
  sentence.id = "fault-sentence";
  const stages = el("div", "stages");
  const marks = {};
  for (const k of STAGES) {
    const m = el("div", "stage-m");
    m.dataset.stage = k;
    m.appendChild(el("i"));
    m.append(S("faults", `stage-${k}`));
    stages.appendChild(m);
    marks[k] = m;
  }
  const staff = el("div", "staffline");
  staff.id = "fault-staff";
  card.append(kick, h, sentence, stages, staff);
  host.appendChild(card);
  parts = { h, sentence, marks, staff };
}

/** Show or clear the card. Returns true while a fault or start-up card is up. */
export function update(st) {
  const s = classify(st);
  // Starting is not a card: the attract screen says WAKING UP and lights its stones as each
  // stage comes up (UX 5.1). A fault later on is a card over whatever was showing (UX 5.8).
  if (!s || s.variant === "starting") {
    if (shown) { host.hidden = true; shown = null; }
    return s ? "starting" : false;
  }
  const key = `${s.variant}|${s.staff}|${s.vars ? JSON.stringify(s.vars) : ""}`;
  if (shown !== key) {
    parts.h.textContent = S("faults", s.variant);
    parts.sentence.textContent = M("faults", s.variant);
    const line = s.code && rig.live.faults.get(s.code);
    parts.staff.textContent = S("faults", s.staff, s.vars) + (line && line.staff_line ? ` · ${line.staff_line}` : "");
    host.hidden = false;
    host.dataset.variant = s.variant;
    shown = key;
  }
  for (const k of STAGES) parts.marks[k].classList.toggle("done", !!(s.stages && s.stages[k]));
  return true;
}

export const showing = () => shown !== null;
