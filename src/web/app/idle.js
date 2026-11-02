// idle.js: idle reset, the "Still playing?" veil, the held-key rule (KP-02; PLAY-8, UX 5.9, 6.5).
//
// Defaults from kiosk.conf: idle_timeout_s = 90, idle_warning_s = 15, held_key_release_s =
// 60. After timeout - warning seconds with no touch and no key, a silent veil counts down;
// any touch or key cancels it and leaves the visitor exactly where they were. At the
// timeout the station resets: HOME (notes released, default patch, RUN), layers closed,
// attract. A key held longer than held_key_release_s is not activity: a backpack on the
// keyboard cannot keep the station from resetting (rigd and keyboard.js release the key).
//
// Time is the monotonic clock (performance.now), so a wall-clock jump changes nothing
// (UI-11). Physical key activity is read from `keys_raw`, used here only as a signal and
// never drawn.

import { el, svg } from "./blocks.js";
import { S } from "./strings.js";

let cfg = { timeoutMs: 90000, warningMs: 15000, heldMs: 60000 };
let last = 0;
let warned = false;
let onReset = () => {};
let isAttract = () => false;
let touchHeld = () => false;
let isPaused = () => false;
let veil = null;
let ringArc = null;
let countText = null;
const heldSince = new Map(); // keys_raw bit -> ms
let prevRaw = 0n;
let timer = null;

export function configure(c) { cfg = { ...cfg, ...c }; }

export function install({ reset, attract, held, paused }) {
  onReset = reset;
  isAttract = attract;
  if (held) touchHeld = held;
  if (paused) isPaused = paused;
  veil = document.getElementById("veil");
  veil.textContent = "";
  const ring = svg("svg", { width: 300, height: 300, viewBox: "0 0 300 300", "aria-hidden": "true" }, veil);
  svg("circle", { cx: 150, cy: 150, r: 120, fill: "none", stroke: "#3a2e46", "stroke-width": 18 }, ring);
  ringArc = svg("circle", { cx: 150, cy: 150, r: 120, fill: "none", stroke: "#F2A83B", "stroke-width": 18, "stroke-linecap": "round",
    transform: "rotate(-90 150 150)", "stroke-dasharray": `${2 * Math.PI * 120}`, "stroke-dashoffset": "0" }, ring);
  countText = svg("text", { x: 150, y: 176, "text-anchor": "middle", class: "count" }, ring);
  const words = el("div");
  words.appendChild(el("h2", null, S("idle", "title")));
  words.appendChild(el("p", null, S("idle", "line-1")));
  words.appendChild(el("p", null, S("idle", "line-2")));
  veil.appendChild(words);
  last = performance.now();
  clearInterval(timer);
  timer = setInterval(check, 250);
}

/** Any touch, on-screen key or QWERTY key. */
export function activity() {
  last = performance.now();
  if (warned) hide();
}

/** Physical keys: a new key down is activity; a key held past the limit is not. */
export function sawKeys(keysRaw) {
  let bits = 0n;
  keysRaw.forEach((row, r) => { bits |= BigInt(row) << BigInt(r * 8); });
  const t = performance.now();
  for (let b = 0; b < 64; b++) {
    const m = 1n << BigInt(b);
    if (bits & m) { if (!heldSince.has(b)) heldSince.set(b, t); } else heldSince.delete(b);
  }
  const fresh = bits & ~prevRaw;
  prevRaw = bits;
  if (fresh) activity();
  else if (bits) {
    // a key still held and under the limit keeps the station awake
    for (const since of heldSince.values()) if (t - since <= cfg.heldMs) { last = Math.max(last, t); if (warned) hide(); break; }
  }
}

function hide() {
  warned = false;
  veil.hidden = true;
}

function check() {
  // attract has nothing to reset; a docent on the staff screen is not a visitor walking away
  if (isAttract() || isPaused()) { last = performance.now(); if (warned) hide(); return; }
  // an on-screen key held down (and not yet past the held-key limit) is someone playing
  if (touchHeld()) last = performance.now();
  const idle = performance.now() - last;
  if (idle >= cfg.timeoutMs) {
    hide();
    last = performance.now();
    onReset();
    return;
  }
  if (idle >= cfg.timeoutMs - cfg.warningMs) {
    if (!warned) { warned = true; veil.hidden = false; }
    const left = Math.max(0, cfg.timeoutMs - idle);
    const frac = left / cfg.warningMs;
    ringArc.setAttribute("stroke-dashoffset", String((1 - frac) * 2 * Math.PI * 120));
    const n = String(Math.ceil(left / 1000));
    if (countText.textContent !== n) countText.textContent = n;
  }
}

export const warning = () => warned;
export const timeoutMs = () => cfg.timeoutMs;
