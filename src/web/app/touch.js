// touch.js: pointer normalisation and gesture suppression (KP-03; INPUT-4, UX 4.4).
//
// Ported in spirit from the Model 4 kiosk's touch.js, changed for an instrument: many
// pointers at once are normal here (each owns one key, one cable or one control), so there
// is no "first pointer only" rule. What it keeps: no browser gesture ever fires (pinch,
// swipe-back, long-press menu, text selection, drag-scroll), and a control fires on
// pointerup inside the control it started on, after a move of less than 12 px.
//
// The page makes no sound: there is no click here, or anywhere (UX 7.2).

const MOVE_LIMIT = 12; // stage px (UX 6.1 uses the same figure for "tap a plug")
const activity = new Set();
let scaleFn = () => 1;

export function setScale(fn) { scaleFn = fn; }
export function onActivity(fn) { activity.add(fn); }
export function noteActivity(kind = "touch") { for (const fn of activity) fn(kind); }

const prevent = (e) => { if (e.cancelable) e.preventDefault(); };

/**
 * Kiosk keys (KIOSK-1, UX 4.4): a keyboard left on the station, or a stray USB device, must
 * not reach the browser: no reload, zoom, find, print, save, history, devtools, fullscreen
 * toggle, select-all or new window. Chromium's kiosk flags close most of these; the page
 * closes them again so nothing depends on one layer. Plain letters, digits, Space, Enter and
 * Tab pass (the dev QWERTY keyboard and an assistive build's activation keys, A-28).
 */
export function kioskKeyBlocked(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return true;
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(e.key)) return true;
  return ["Backspace", "Escape", "ContextMenu", "BrowserBack", "BrowserForward", "BrowserRefresh", "BrowserHome",
    "BrowserSearch", "BrowserFavorites", "Find", "Help", "Print", "ZoomIn", "ZoomOut", "PageUp", "PageDown", "Home", "End"].includes(e.key);
}

/** Suppress every browser gesture on the page (the CSS half is touch-action: none). */
export function install(root = document) {
  // A file dropped on the page would navigate to it; copy, cut and paste have nothing to do.
  for (const type of ["contextmenu", "dragstart", "selectstart", "gesturestart", "gesturechange", "gestureend", "dblclick", "wheel",
    "dragover", "drop", "copy", "cut", "paste", "auxclick"]) {
    root.addEventListener(type, prevent, { passive: false, capture: true });
  }
  root.addEventListener("keydown", (e) => { if (kioskKeyBlocked(e)) prevent(e); }, { capture: true });
  // the middle button's autoscroll
  root.addEventListener("mousedown", (e) => { if (e.button === 1) prevent(e); }, { capture: true });
  root.addEventListener("touchstart", (e) => { if (e.touches.length > 1) prevent(e); }, { passive: false, capture: true });
  root.addEventListener("touchmove", prevent, { passive: false, capture: true });
  root.addEventListener("pointerdown", () => noteActivity("touch"), { capture: true });
  // A finger that keeps moving (a cable drag, the knob) is someone mid-action, not someone
  // who walked away: the idle reset must not fire under it (NFR-10, PLAY-8; QA-ADV-02). A
  // still finger is not activity, so an object resting on the glass cannot hold the station.
  let lastMove = 0;
  root.addEventListener("pointermove", (e) => {
    if (!e.buttons && e.pointerType !== "touch") return; // a hovering mouse is nobody
    const t = performance.now();
    if (t - lastMove < 250) return;
    lastMove = t;
    noteActivity("move");
  }, { capture: true, passive: true });
  root.addEventListener("keydown", () => noteActivity("key"), { capture: true });
}

/**
 * A tap control. `handler(event)` runs on pointerup inside `el` after less than 12 px of
 * movement. Keyboard activation (Enter, Space) works too, for an assistive build (A-28).
 * Returns an unbind function. `opts.onDown(event)` runs at pointerdown (STEP repeat).
 */
export function tap(el, handler, opts = {}) {
  const downs = new Map();
  const down = (e) => {
    if (e.button !== undefined && e.button > 0) return;
    downs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    el.classList.add("pressed");
    try { el.setPointerCapture(e.pointerId); } catch { /* best effort */ }
    if (opts.onDown) opts.onDown(e);
    prevent(e);
  };
  const up = (e) => {
    const d = downs.get(e.pointerId);
    downs.delete(e.pointerId);
    if (!downs.size) el.classList.remove("pressed");
    if (!d) return;
    if (opts.onUp) opts.onUp(e);
    const s = scaleFn() || 1;
    const moved = Math.hypot(e.clientX - d.x, e.clientY - d.y) / s;
    const r = el.getBoundingClientRect();
    const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (moved < MOVE_LIMIT && inside) handler(e);
    prevent(e);
  };
  const cancel = (e) => {
    downs.delete(e.pointerId);
    if (!downs.size) el.classList.remove("pressed");
    if (opts.onUp) opts.onUp(e);
  };
  const key = (e) => {
    if (e.key === "Enter" || e.key === " ") { prevent(e); handler(e); }
  };
  el.addEventListener("pointerdown", down);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", cancel);
  el.addEventListener("lostpointercapture", cancel);
  el.addEventListener("keydown", key);
  if (!el.hasAttribute("tabindex") && el.tagName !== "BUTTON") el.setAttribute("tabindex", "0");
  el.dataset.tap = "1";
  return () => {
    el.removeEventListener("pointerdown", down);
    el.removeEventListener("pointerup", up);
    el.removeEventListener("pointercancel", cancel);
    el.removeEventListener("lostpointercapture", cancel);
    el.removeEventListener("keydown", key);
  };
}
