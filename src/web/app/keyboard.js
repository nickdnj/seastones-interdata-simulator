// keyboard.js: the on-screen keyboard and the touch key source (VS-15, KP-03; INPUT-2, INPUT-4, INPUT-5).
//
// 37 keys, C3 to C6, key k = note 48 + k, the same key numbers as the physical keyboard
// and the KEYS device (ARCHITECTURE 5.1). Touch keys never make a sound: they set bits in
// the touch bitmap, the 7/16 program reads the bitmap, and only the program sounds a note.
//
// The bitmap is sent whole (a level, not edges) at every change and at 4 Hz, so a lost
// message cannot stick a note. Each pointer owns one key; up, cancel, leaving the key,
// losing capture, a blur or a hidden page all release it.
//
// Held-key rule (PLAY-8, UX 6.5): a key held longer than held_key_release_s is dropped
// from the bitmap and ignored until that pointer lets go. rigd applies the same rule to
// the MIDI keyboard.
//
// QWERTY (INPUT-5) is a development mapping, on only with kiosk.conf dev_qwerty = on or
// ?dev=1 on a loopback page. It ORs into the same touch bitmap.

import { el } from "./blocks.js";
import * as protocol from "./protocol.js";
import { noteActivity } from "./touch.js";

export const KEYS = 37;
export const BASE_NOTE = 48;
const WHITE = [0, 2, 4, 5, 7, 9, 11];
const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const noteName = (n) => NAMES[n % 12] + (Math.floor(n / 12) - 1);

const QWERTY = { z: 48, x: 50, c: 52, v: 53, b: 55, n: 57, m: 59, a: 60, w: 61, s: 62, e: 63, d: 64, f: 65, t: 66, g: 67, y: 68, h: 69, u: 70, j: 71, k: 72, o: 73, l: 74, p: 75, ";": 76 };

const pointers = new Map(); // pointerId -> {key, since, ignored}
const qwertyDown = new Map(); // key char -> {key, since, ignored}
const keyboards = new Set();
let lastSent = null;
let refresh = null;
let heldLimitMs = 60000;
let qwertyOn = false;
let now = () => performance.now();

export function configure({ heldKeyMs, qwerty, clock }) {
  if (Number.isFinite(heldKeyMs)) heldLimitMs = heldKeyMs;
  qwertyOn = !!qwerty;
  if (clock) now = clock;
}

/** The touch bitmap now: every pointer and QWERTY key that is down and not past 60 s. */
export function bits() {
  let b = 0n;
  const t = now();
  for (const src of [pointers, qwertyDown]) {
    for (const p of src.values()) {
      if (!p.ignored && t - p.since > heldLimitMs) p.ignored = true;
      if (!p.ignored) b |= 1n << BigInt(p.key);
    }
  }
  return b;
}

/** True while any key is down and not yet released by the held-key rule. */
export function anyHeld() { return bits() !== 0n; }

function changed() {
  const b = bits();
  for (const kb of keyboards) kb.paint(b);
  if (b !== lastSent) {
    lastSent = b;
    protocol.keysTouch(b);
  }
}

/** Send the level now and every 250 ms (INPUT-4). Also re-applies the held-key rule. */
export function start() {
  clearInterval(refresh);
  refresh = setInterval(() => {
    const b = bits();
    if (b !== lastSent) changed();
    else protocol.keysTouch(b);
  }, 250);
  window.addEventListener("blur", releaseAll);
  document.addEventListener("visibilitychange", () => { if (document.hidden) releaseAll(); });
  window.addEventListener("keydown", (e) => {
    if (!qwertyOn || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    const n = QWERTY[e.key.toLowerCase()];
    if (n === undefined) return;
    qwertyDown.set(e.key.toLowerCase(), { key: n - BASE_NOTE, since: now(), ignored: false });
    noteActivity("key");
    changed();
  });
  window.addEventListener("keyup", (e) => {
    if (qwertyDown.delete(e.key.toLowerCase())) changed();
  });
}

export function releaseAll() {
  pointers.clear();
  qwertyDown.clear();
  changed();
}

/** Build a keyboard into `parent`. `width` and `height` in stage px. */
export class Keyboard {
  constructor(parent, { width = 1804, height = 190, slim = false } = {}) {
    const whites = [];
    for (let k = 0; k < KEYS; k++) if (WHITE.includes(k % 12)) whites.push(k);
    const gap = 3;
    const ww = (width - gap * (whites.length - 1)) / whites.length;
    const bw = Math.max(54, Math.round(ww * 0.66));
    this.root = el("div", "kb" + (slim ? " slim" : ""));
    this.root.style.width = `${width}px`;
    this.root.style.height = `${height}px`;
    this.root.setAttribute("role", "group");
    this.root.setAttribute("aria-label", "Keyboard");
    this.caps = new Array(KEYS);
    whites.forEach((k, i) => {
      const cap = el("div", "wk");
      cap.style.left = `${Math.round(i * (ww + gap))}px`;
      cap.style.width = `${Math.round(ww)}px`;
      const note = BASE_NOTE + k;
      if (note % 12 === 0) cap.appendChild(el("span", "nm", noteName(note)));
      this.add(cap, k);
    });
    for (let k = 0; k < KEYS; k++) {
      if (WHITE.includes(k % 12)) continue;
      const leftWhite = whites.indexOf(k - 1);
      const cap = el("div", "bk");
      cap.style.left = `${Math.round((leftWhite + 1) * (ww + gap) - gap / 2 - bw / 2)}px`;
      cap.style.width = `${bw}px`;
      cap.style.height = `${Math.max(54, Math.round(height * 0.62))}px`; // touch floor (A-05)
      this.add(cap, k);
    }
    parent.appendChild(this.root);
    keyboards.add(this);
  }

  add(cap, k) {
    cap.dataset.key = String(k);
    cap.setAttribute("role", "button");
    cap.setAttribute("aria-label", noteName(BASE_NOTE + k));
    const release = (e) => {
      const p = pointers.get(e.pointerId);
      if (p && p.key === k) { pointers.delete(e.pointerId); changed(); }
    };
    cap.addEventListener("pointerdown", (e) => {
      if (e.cancelable) e.preventDefault();
      e.stopPropagation(); // a key is not a tap on whatever is behind it
      noteActivity("key");
      pointers.set(e.pointerId, { key: k, since: now(), ignored: false });
      try { cap.releasePointerCapture(e.pointerId); } catch { /* implicit touch capture */ }
      changed();
    });
    for (const t of ["pointerup", "pointercancel", "pointerleave", "lostpointercapture"]) cap.addEventListener(t, release);
    this.root.appendChild(cap);
    this.caps[k] = cap;
  }

  /** The key cap's own feedback: lit while this page holds it down. */
  paint(b) {
    for (let k = 0; k < KEYS; k++) {
      const on = ((b >> BigInt(k)) & 1n) === 1n;
      if (this.caps[k]._on !== on) {
        this.caps[k]._on = on;
        this.caps[k].classList.toggle("on", on);
      }
    }
  }
}
