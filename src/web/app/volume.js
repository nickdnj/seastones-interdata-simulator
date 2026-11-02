// volume.js: the visitor's volume and a visible mute (AUDIO-3, NFR-10; UX 4.2a).
//
// A speaker button in the dock, on every layer and in reach (UX 4.3). It shows the level as
// five bars and, while the station is muted for any reason, a crossed speaker and the word
// "Muted". A tap opens a small panel above it: Mute (or Sound on), Quieter, the level and
// Louder. The level is dB below the staff ceiling (rigd's audio.volume, -40 to 0), in five
// steps, so a visitor can only ever turn the station down from where staff set it (STAFF-2).
// The page makes no sound and never assumes: the level and mute it shows are what rigd
// reports in state.volume. HOME and the idle reset put rigd back to 0 dB and unmuted, so the
// next visitor never finds it silenced.

import { el } from "./blocks.js";
import { S } from "./strings.js";
import * as rig from "./rig.js";
import * as protocol from "./protocol.js";
import { tap } from "./touch.js";

const STEPS = 5;
// dB below the staff ceiling for 0 to 5 bars: 6 dB a step, and the quietest is rigd's floor
export const DB_STEPS = [-40, -24, -18, -12, -6, 0];
const PANEL_IDLE_MS = 6000;

const SPEAKER = '<path d="M6 18h8l10-8v28l-10-8H6z" fill="currentColor"/>';
const WAVES = '<path d="M30 17q5 7 0 14M35 12q9 12 0 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>';
const CROSS = '<path d="M30 17l12 14M42 17 30 31" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>';

let btn = null;
let panel = null;
let closeTimer = null;
const ui = {};

const vol = () => (rig.live.state && rig.live.state.volume) || null;
/** Bars lit, 0 to 5: the step nearest rigd's dB. */
const levelOf = () => {
  const v = vol();
  if (!v) return null;
  let best = 0;
  DB_STEPS.forEach((db, i) => { if (Math.abs(db - v.db) < Math.abs(DB_STEPS[best] - v.db)) best = i; });
  return best;
};
const visitorMute = () => !!(vol() && vol().muted);
const anyMute = () => !!((rig.live.heartbeat && rig.live.heartbeat.muted) || (rig.live.state && rig.live.state.muted) || visitorMute());

export function install(stage) {
  const dock = document.getElementById("dock");
  btn = el("button", "vol");
  btn.type = "button";
  btn.id = "volume";
  btn.setAttribute("aria-haspopup", "dialog");
  btn.setAttribute("aria-expanded", "false");
  ui.icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  ui.icon.setAttribute("viewBox", "0 0 48 48");
  ui.icon.setAttribute("aria-hidden", "true");
  btn.appendChild(ui.icon);
  ui.word = el("span", "vol-word", S("frame", "volume"));
  btn.appendChild(ui.word);
  tap(btn, () => (panel.hidden ? open() : close()));
  dock.insertBefore(btn, document.getElementById("fullspeed"));

  panel = el("div", "card vol-panel");
  panel.id = "volume-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", S("frame", "volume"));
  panel.addEventListener("pointerdown", () => armClose(), { capture: true });
  ui.mute = el("button", "btn sm vol-mute", S("frame", "mute"));
  ui.mute.type = "button";
  ui.mute.id = "volume-mute";
  ui.mute.setAttribute("aria-pressed", "false");
  tap(ui.mute, () => protocol.mute(!visitorMute()));
  const down = el("button", "btn sm vol-step", "−");
  down.type = "button";
  down.id = "volume-down";
  down.setAttribute("aria-label", S("frame", "volume-down"));
  tap(down, () => step(-1));
  ui.bars = el("div", "vol-bars");
  ui.bars.id = "volume-bars";
  ui.bars.setAttribute("role", "meter");
  ui.bars.setAttribute("aria-valuemin", "0");
  ui.bars.setAttribute("aria-valuemax", String(STEPS));
  ui.bars.setAttribute("aria-label", S("frame", "volume"));
  ui.segs = [];
  for (let i = 0; i < STEPS; i++) { const sg = el("i"); ui.bars.appendChild(sg); ui.segs.push(sg); }
  const up = el("button", "btn sm vol-step", "+");
  up.type = "button";
  up.id = "volume-up";
  up.setAttribute("aria-label", S("frame", "volume-up"));
  tap(up, () => step(1));
  panel.append(ui.mute, down, ui.bars, up);
  stage.appendChild(panel);
  paint();
}

function step(d) {
  const l = levelOf();
  if (l === null) return;
  const n = Math.max(0, Math.min(STEPS, l + d));
  if (n !== l) protocol.volume(DB_STEPS[n]);
  // a visitor turning it up wants to hear it
  if (d > 0 && visitorMute()) protocol.mute(false);
}

function armClose() {
  clearTimeout(closeTimer);
  closeTimer = setTimeout(close, PANEL_IDLE_MS);
}

export function open() {
  panel.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  armClose();
  paint();
}

export function close() {
  clearTimeout(closeTimer);
  if (panel) panel.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

/** Repaint from rigd's state.volume and mute flags (cheap; called every frame). */
export function paint() {
  if (!btn) return;
  const muted = anyMute();
  const l = levelOf();
  const lit = l === null ? 0 : l;
  const key = `${muted}|${lit}|${visitorMute()}|${l === null}`;
  if (key === ui.key) return;
  ui.key = key;
  ui.icon.innerHTML = SPEAKER + (muted ? CROSS : WAVES);
  btn.classList.toggle("muted", muted);
  ui.word.textContent = S("frame", muted ? "volume-muted" : "volume");
  btn.setAttribute("aria-label", `${S("frame", "volume")}: ${muted ? S("frame", "volume-muted") : `${lit} / ${STEPS}`}`);
  btn.disabled = l === null;
  ui.segs.forEach((sg, i) => sg.classList.toggle("on", i < lit && !muted));
  ui.bars.setAttribute("aria-valuenow", String(lit));
  ui.mute.textContent = S("frame", visitorMute() ? "unmute" : "mute");
  ui.mute.setAttribute("aria-pressed", String(visitorMute()));
  ui.mute.classList.toggle("on", visitorMute());
  if (l === null) close();
}
