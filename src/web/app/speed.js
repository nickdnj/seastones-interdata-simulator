// speed.js: the speed knob, the six detents, STEP and FULL SPEED (PR-07; PLAY-7, PLAY-11, PANEL-2).
//
// The detents, their names and their ratios come from the engine (hello.capabilities.speeds,
// the calibration record PR-03); the page hard-codes none of them (UI-14). Everything this
// module draws follows the speed the ENGINE reports in `state`, not the one last asked for,
// so the header, the knob and the buttons always tell the truth (UI-13). The page never
// fakes lateness: notes arrive late because the emulator really runs slower.
//
// STEP sends exactly one machine.step per touch and repeats at 3 a second after 600 ms held.

import { el } from "./blocks.js";
import { S, M } from "./strings.js";
import * as protocol from "./protocol.js";
import * as rig from "./rig.js";
import { tap, noteActivity } from "./touch.js";

const STEP_DELAY_MS = 600;
const STEP_RATE_MS = 333;
// A held STEP that is repeating is a visitor at work (NFR-10, QA-ADV-02b), but only for as
// long as the held-key rule allows a held key (PLAY-8): a pinned button cannot keep the
// station awake for ever. app.js sets it from kiosk.conf held_key_release_s.
let stepHoldCapMs = 60000;
export function configureStep({ holdCapMs }) { if (Number.isFinite(holdCapMs)) stepHoldCapMs = holdCapMs; }

export const index = (id) => rig.speeds().findIndex((s) => s.id === id);
export const isSlowed = (state) => !!state && state.speed !== "run";

export function select(i) {
  const sp = rig.speeds()[i];
  if (sp) protocol.speed(sp.id);
}

/** Bind horizontal drag (60 px a detent) and tap-to-advance to a knob element. */
export function bindKnob(knob, stageScale) {
  let start = null;
  knob.addEventListener("pointerdown", (e) => {
    const st = rig.live.state;
    start = { x: e.clientX, i: st ? index(st.speed) : 0, moved: false, last: null };
    try { knob.setPointerCapture(e.pointerId); } catch { /* best effort */ }
    if (e.cancelable) e.preventDefault();
  });
  knob.addEventListener("pointermove", (e) => {
    if (!start) return;
    const dx = (e.clientX - start.x) / (stageScale() || 1);
    if (Math.abs(dx) >= 12) start.moved = true;
    const n = rig.speeds().length;
    const i = Math.max(0, Math.min(n - 1, start.i + Math.round(dx / 60)));
    if (start.moved && i !== start.last) { start.last = i; select(i); }
  });
  const end = () => {
    if (start && !start.moved) {
      const n = rig.speeds().length;
      if (n) select((start.i + 1) % n);
    }
    start = null;
  };
  knob.addEventListener("pointerup", end);
  knob.addEventListener("pointercancel", () => { start = null; });
}

/** A STEP button: one step per touch, then 3 a second after 600 ms held. */
export function stepButton(btn) {
  let delay = null, repeat = null, since = 0;
  const stop = () => { clearTimeout(delay); clearInterval(repeat); delay = repeat = null; };
  const go = () => {
    const st = rig.live.state;
    if (st && st.speed === "step") protocol.step();
  };
  const tick = () => {
    go();
    // "move" activity: it holds off the idle reset, and never wakes the attract screen
    if (performance.now() - since <= stepHoldCapMs) noteActivity("move");
  };
  tap(btn, () => {}, {
    onDown: () => {
      stop();
      go();
      since = performance.now();
      delay = setTimeout(() => { repeat = setInterval(tick, STEP_RATE_MS); }, STEP_DELAY_MS);
    },
    onUp: stop,
  });
  btn.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") go(); });
  return stop;
}

/** The row of detent buttons. Returns paint(state). */
export function detents(parent) {
  const row = el("div", "dets");
  const buttons = [];
  let built = null;
  const build = () => {
    row.textContent = "";
    buttons.length = 0;
    rig.speeds().forEach((sp, i) => {
      const b = el("button", "det", sp.label);
      b.type = "button";
      b.dataset.speed = sp.id;
      b.setAttribute("aria-pressed", "false");
      tap(b, () => select(i));
      row.appendChild(b);
      buttons.push(b);
    });
    built = rig.live.hello;
  };
  parent.appendChild(row);
  return (state) => {
    if (built !== rig.live.hello) build();
    for (const b of buttons) {
      const on = !!state && b.dataset.speed === state.speed;
      if (b._on !== on) { b._on = on; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }
    }
  };
}

/** The two-line readout: what this speed means, and the key-to-sound figure. */
export function readoutText(state) {
  if (!state) return { say: "", k2s: "" };
  const sp = rig.speeds().find((s) => s.id === state.speed);
  const ms = sp ? sp.key_to_sound_ms : null;
  const k2s = ms === null || ms === undefined ? S("play", "waits-for-step") : formatMs(ms);
  return { say: S("speed", state.speed), lamp: M("speed", state.speed), k2s };
}

export function formatMs(ms) {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return `${s < 10 ? s.toFixed(1).replace(/\.0$/, "") : Math.round(s)} s`;
}

export function label(state) {
  const sp = state && rig.speeds().find((s) => s.id === state.speed);
  return sp ? sp.label : "·";
}
