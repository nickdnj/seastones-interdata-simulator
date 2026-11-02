// staff.js: the staff screen (KP-07, KP-08, KP-09; CT-07 entry; STAFF-1 to STAFF-3, UX 5.11).
//
// Opened only by holding the logo mark for 3 s (no move, one finger), then a PIN on an
// on-screen keypad: a stray touch never opens it, and nothing on the floor needs a keyboard
// or a mouse. rigd checks the PIN (a hash on /data, never in the repo) and locks the screen
// for 30 s after five wrong tries; the page only shows what rigd says.
//
// Health and diagnostics come from the live protocol (heartbeat, hello, state.keys_raw) and
// the content index's problem list. Settings and actions are the PIN-gated `staff.*`
// commands. This is the only module that may send them; protocol.js, the visitor set, has
// none, and no staff command writes memory (CODE-4). The screen closes itself after two
// minutes untouched, so a docent who walks away cannot leave visitors locked out.

import { el } from "./blocks.js";
import { S, M } from "./strings.js";
import * as content from "./content.js";
import * as rig from "./rig.js";
import { tap } from "./touch.js";

export const HOLD_MS = 3000;
const HOLD_MOVE = 12;
const PIN_IDLE_MS = 30000;
const SCREEN_IDLE_MS = 120000;
const CONFIRM_MS = 3000;
const PIN_MAX = 8;

/** Every staff message the page can send (ARCHITECTURE 4.4 plus the proposed extensions). */
export const STAFF_TYPES = [
  "staff.auth", "staff.close", "staff.ceiling", "staff.quiet_hours", "staff.idle_timeout",
  "staff.attract_sound", "staff.reduced_motion", "staff.mute", "staff.test_tone",
  "staff.restart", "staff.review_mode", "staff.save_preset",
];
const send = (t, args = {}) => rig.command({ t, ...args });

let host = null;
let pinBox = null;
let screen = null;
let ctx = null;
let pin = "";
let pinTimer = null;
let idleTimer = null;
let lockTimer = null;
const ui = {};

/** Hold-to-open on the logo mark. Returns the cancel function (for tests). */
export function install(stage, mark, context) {
  host = stage;
  ctx = context;
  buildPin();
  buildScreen();
  let hold = null;
  const cancel = () => { if (hold) { clearTimeout(hold.timer); hold = null; } };
  mark.style.touchAction = "none";
  mark.addEventListener("pointerdown", (e) => {
    if (hold) { cancel(); return; } // a second finger: not the gesture
    hold = { id: e.pointerId, x: e.clientX, y: e.clientY, timer: setTimeout(() => { hold = null; openPin(); }, HOLD_MS) };
    try { mark.setPointerCapture(e.pointerId); } catch { /* best effort */ }
  });
  mark.addEventListener("pointermove", (e) => {
    if (hold && e.pointerId === hold.id && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > HOLD_MOVE * (ctx.stageScale() || 1)) cancel();
  });
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) mark.addEventListener(t, cancel);
  rig.on("staff", (m) => paintStaff(m));
  rig.on("status", (up) => { if (!up) closeAll(); });
  return cancel;
}

export const open = () => !!(screen && !screen.hidden);
export const pinOpen = () => !!(pinBox && !pinBox.hidden);

// ---------------------------------------------------------------- PIN keypad

function buildPin() {
  pinBox = el("div", "staff-pin");
  pinBox.id = "staff-pin";
  pinBox.hidden = true;
  pinBox.setAttribute("role", "dialog");
  const card = el("div", "card staff-pin-card");
  card.appendChild(el("h2", null, S("staff", "pin-title")));
  card.appendChild(el("p", "staff-pin-sub", M("staff", "pin-title")));
  ui.dots = el("div", "staff-dots");
  ui.dots.id = "staff-dots";
  card.appendChild(ui.dots);
  ui.pinMsg = el("div", "staff-pin-msg", "");
  ui.pinMsg.id = "staff-pin-msg";
  ui.pinMsg.setAttribute("aria-live", "polite");
  card.appendChild(ui.pinMsg);
  const pad = el("div", "staff-pad");
  const key = (label, id, fn) => {
    const b = el("button", "btn staff-key", label);
    b.type = "button";
    b.id = id;
    tap(b, () => { armPinTimer(); fn(); });
    pad.appendChild(b);
  };
  for (const d of ["1", "2", "3", "4", "5", "6", "7", "8", "9"]) key(d, `staff-key-${d}`, () => digit(d));
  key(S("staff", "pin-delete"), "staff-key-del", () => { pin = pin.slice(0, -1); paintDots(); });
  key("0", "staff-key-0", () => digit("0"));
  key(S("staff", "pin-ok"), "staff-key-ok", () => submit());
  card.appendChild(pad);
  const cancel = el("button", "btn staff-cancel", S("staff", "cancel"));
  cancel.type = "button";
  cancel.id = "staff-pin-cancel";
  tap(cancel, () => closePin());
  card.appendChild(cancel);
  pinBox.appendChild(card);
  host.appendChild(pinBox);
}

function digit(d) {
  if (pin.length < PIN_MAX) pin += d;
  paintDots();
}

function paintDots() {
  ui.dots.textContent = pin.length ? "●".repeat(pin.length) : "·";
}

function armPinTimer() {
  clearTimeout(pinTimer);
  pinTimer = setTimeout(closePin, PIN_IDLE_MS);
}

function openPin() {
  if (open()) return;
  pin = "";
  paintDots();
  ui.pinMsg.textContent = "";
  pinBox.hidden = false;
  armPinTimer();
}

function closePin() {
  clearTimeout(pinTimer);
  clearInterval(lockTimer);
  pin = "";
  if (pinBox) pinBox.hidden = true;
}

async function submit() {
  if (pin.length < 4) return;
  const tried = pin;
  pin = "";
  paintDots();
  const r = await send("staff.auth", { pin: tried });
  if (r.ok) { closePin(); openScreen(); }
  else if (r.code !== "not_staff") ui.pinMsg.textContent = S("staff", "failed", { code: r.code });
  // a not_staff reply is followed by a staff message saying why (tries left or a lockout)
}

function showLock(seconds) {
  clearInterval(lockTimer);
  let s = seconds;
  const paint = () => { ui.pinMsg.textContent = S("staff", "pin-locked", { s }); };
  paint();
  lockTimer = setInterval(() => { s -= 1; if (s <= 0) { clearInterval(lockTimer); ui.pinMsg.textContent = ""; } else paint(); }, 1000);
}

// ---------------------------------------------------------------- the staff screen

const row = (parent, label, id) => {
  const r = el("div", "staff-row");
  r.appendChild(el("span", "staff-k", label));
  const v = el("span", "staff-v", "·");
  v.id = id;
  r.appendChild(v);
  parent.appendChild(r);
  return v;
};

function stepper(parent, label, id, onStep) {
  const r = el("div", "staff-row");
  r.appendChild(el("span", "staff-k", label));
  const box = el("span", "staff-step");
  const minus = el("button", "btn sm staff-pm", "−");
  minus.type = "button";
  minus.id = `${id}-minus`;
  minus.setAttribute("aria-label", `${label} down`);
  const v = el("b", "staff-num", "·");
  v.id = id;
  const plus = el("button", "btn sm staff-pm", "+");
  plus.type = "button";
  plus.id = `${id}-plus`;
  plus.setAttribute("aria-label", `${label} up`);
  tap(minus, () => onStep(-1));
  tap(plus, () => onStep(1));
  box.append(minus, v, plus);
  r.appendChild(box);
  parent.appendChild(r);
  return v;
}

function toggle(parent, label, id, onSet) {
  const r = el("div", "staff-row");
  r.appendChild(el("span", "staff-k", label));
  const b = el("button", "chip staff-toggle", S("staff", "off"));
  b.type = "button";
  b.id = id;
  b.setAttribute("aria-pressed", "false");
  tap(b, () => onSet(b.getAttribute("aria-pressed") !== "true"));
  r.appendChild(b);
  parent.appendChild(r);
  return b;
}

function setToggle(b, on) {
  b.classList.toggle("on", !!on);
  b.setAttribute("aria-pressed", String(!!on));
  const t = S("staff", on ? "on" : "off");
  if (b.textContent !== t) b.textContent = t;
}

function action(parent, label, id, fn, cls = "btn sm") {
  const b = el("button", cls, label);
  b.type = "button";
  b.id = id;
  tap(b, fn);
  parent.appendChild(b);
  return b;
}

const card = (parent, title) => {
  const c = el("section", "card staff-card");
  c.appendChild(el("h3", "lbl amber", title));
  parent.appendChild(c);
  return c;
};

const clock = (hhmm, deltaMin) => {
  const [h, m] = hhmm.split(":").map(Number);
  const t = (((h * 60 + m + deltaMin) % 1440) + 1440) % 1440;
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
};

function buildScreen() {
  screen = el("div", "staff-screen");
  screen.id = "staff-screen";
  screen.hidden = true;
  screen.setAttribute("role", "dialog");
  screen.setAttribute("aria-labelledby", "staff-title");
  screen.addEventListener("pointerdown", () => armIdle(), { capture: true });
  const head = el("div", "staff-head");
  const h = el("h2", null, S("staff", "title"));
  h.id = "staff-title";
  head.appendChild(h);
  ui.note = el("div", "staff-note", "");
  ui.note.id = "staff-note";
  ui.note.setAttribute("aria-live", "polite");
  head.appendChild(ui.note);
  action(head, S("staff", "close"), "staff-close", () => closeScreen(true), "btn amber sm");
  screen.appendChild(head);

  const cols = el("div", "staff-cols");
  // three columns: health; volume and quiet hours; behaviour and actions
  const left = el("div", "staff-col");
  const mid = el("div", "staff-col");
  const right = el("div", "staff-col");
  cols.append(left, mid, right);
  screen.appendChild(cols);

  const hc = card(left, S("staff", "health"));
  ui.h = {
    emulator: row(hc, S("staff", "health-emulator"), "staff-h-emulator"),
    bridge: row(hc, S("staff", "health-bridge"), "staff-h-bridge"),
    audio: row(hc, S("staff", "health-audio"), "staff-h-audio"),
    keyboard: row(hc, S("staff", "health-keyboard"), "staff-h-keyboard"),
    content: row(hc, S("staff", "health-content"), "staff-h-content"),
    faults: row(hc, S("staff", "health-faults"), "staff-h-faults"),
    image: row(hc, S("staff", "health-image"), "staff-h-image"),
    build: row(hc, S("staff", "health-build"), "staff-h-build"),
    dac: row(hc, S("staff", "health-dac"), "staff-h-dac"),
    latency: row(hc, S("staff", "health-latency"), "staff-h-latency"),
    keys: row(hc, S("staff", "health-keys"), "staff-h-keys"),
    underruns: row(hc, S("staff", "health-underruns"), "staff-h-underruns"),
  };

  const vc = card(mid, S("staff", "volume"));
  ui.ceiling = stepper(vc, S("staff", "ceiling"), "staff-ceiling", (d) => {
    const s = rig.live.staff && rig.live.staff.settings;
    if (s) cmd("staff.ceiling", { dba: Math.max(40, Math.min(s.ceiling_max_dba, s.ceiling_dba + 2 * d)) });
  });
  ui.mute = toggle(vc, S("staff", "mute"), "staff-mute", (on) => cmd("staff.mute", { on }));
  const tone = el("div", "staff-actions");
  action(tone, S("staff", "test-tone"), "staff-test-tone", () => cmd("staff.test_tone"));
  vc.appendChild(tone);

  const qc = card(mid, S("staff", "quiet-hours"));
  const quiet = (patch) => {
    const s = rig.live.staff && rig.live.staff.settings;
    if (s) cmd("staff.quiet_hours", { ...s.quiet_hours, ...patch(s.quiet_hours) });
  };
  ui.qFrom = stepper(qc, S("staff", "quiet-from"), "staff-quiet-from", (d) => quiet((q) => ({ from: clock(q.from, 30 * d) })));
  ui.qTo = stepper(qc, S("staff", "quiet-to"), "staff-quiet-to", (d) => quiet((q) => ({ to: clock(q.to, 30 * d) })));
  ui.qDba = stepper(qc, S("staff", "quiet-ceiling"), "staff-quiet-dba", (d) => quiet((q) => ({ dba: Math.max(40, Math.min(85, q.dba + 2 * d)) })));

  const bc = card(right, S("staff", "behaviour"));
  ui.idle = stepper(bc, S("staff", "idle-timeout"), "staff-idle", (d) => {
    const s = rig.live.settings;
    if (s) cmd("staff.idle_timeout", { s: Math.max(30, Math.min(600, s.idle_timeout_s + 15 * d)) });
  });
  ui.attract = toggle(bc, S("staff", "attract-sound"), "staff-attract", (on) => cmd("staff.attract_sound", { on }));
  ui.motion = toggle(bc, S("staff", "reduced-motion"), "staff-motion", (on) => cmd("staff.reduced_motion", { on }));
  ui.review = toggle(bc, S("staff", "review-mode"), "staff-review", (on) => cmd("staff.review_mode", { on }));
  ui.disasm = toggle(bc, S("staff", "disassembly"), "staff-disasm", (on) => { document.body.classList.toggle("staff", on); setToggle(ui.disasm, on); });

  const ac = card(right, S("staff", "actions"));
  const acts = el("div", "staff-actions");
  action(acts, S("staff", "save-preset"), "staff-save", () => cmd("staff.save_preset"));
  action(acts, S("staff", "restart-computer"), "staff-restart-computer", () => confirmThen("staff-restart-computer", () => cmd("staff.restart", { what: "computer" })));
  action(acts, S("staff", "restart-station"), "staff-restart-station", () => confirmThen("staff-restart-station", () => cmd("staff.restart", { what: "station" })));
  action(acts, S("staff", "about"), "staff-about", () => { closeScreen(true); if (ctx.about) ctx.about(); });
  ac.appendChild(acts);
  host.appendChild(screen);
}

const confirming = new Map();
function confirmThen(id, fn) {
  const b = document.getElementById(id);
  if (confirming.has(id)) {
    clearTimeout(confirming.get(id).timer);
    b.textContent = confirming.get(id).label;
    confirming.delete(id);
    fn();
    return;
  }
  confirming.set(id, { label: b.textContent, timer: setTimeout(() => { b.textContent = confirming.get(id).label; confirming.delete(id); }, CONFIRM_MS) });
  b.textContent = S("staff", "confirm");
}

async function cmd(t, args) {
  const r = await send(t, args);
  if (!r.ok) ui.note.textContent = S("staff", "failed", { code: r.code });
  else ui.note.textContent = "";
  return r;
}

function armIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => closeScreen(true), SCREEN_IDLE_MS);
}

function openScreen() {
  screen.hidden = false;
  ui.note.textContent = "";
  armIdle();
  paint();
}

function closeScreen(tell) {
  clearTimeout(idleTimer);
  if (screen) screen.hidden = true;
  if (tell) send("staff.close");
}

function closeAll() {
  closePin();
  closeScreen(false);
}

function paintStaff(m) {
  if (pinOpen() && !m.authed) {
    if (m.lockout_s > 0) showLock(m.lockout_s);
    else ui.pinMsg.textContent = S("staff", m.tries_left === 1 ? "pin-wrong-1" : "pin-wrong", { n: m.tries_left });
  }
  if (m.saved) ui.note.textContent = S("staff", "saved", { slug: m.saved });
  if (open() && !m.authed) closeScreen(false);
  paint();
}

const hex = (v, n) => v.toString(16).toUpperCase().padStart(n, "0");
const okText = (on) => S("staff", on ? "ok" : "not-ok");
function setText(node, t) { if (node.textContent !== t) node.textContent = t; }
function setOk(node, on) { setText(node, okText(on)); node.classList.toggle("bad", !on); }

/** Repaint from rig.live (called by the render loop while open, and on every staff message). */
export function paint() {
  if (!open()) return;
  const L = rig.live;
  const hb = L.heartbeat;
  setOk(ui.h.emulator, !!(hb && hb.engine_alive));
  setOk(ui.h.bridge, L.connected);
  setOk(ui.h.audio, !!(hb && hb.audio_ok));
  setOk(ui.h.keyboard, !!(hb && hb.midi_present));
  const probs = content.problems().length;
  setText(ui.h.content, probs ? S("staff", "problems", { n: probs }) : S("staff", "ok"));
  ui.h.content.classList.toggle("bad", probs > 0);
  const faults = [...new Set([...((hb && hb.faults) || []), ...L.faults.keys()])];
  setText(ui.h.faults, faults.length ? faults.join(", ") : S("staff", "none"));
  ui.h.faults.classList.toggle("bad", faults.length > 0);
  setText(ui.h.image, L.hello ? L.hello.image_sha256.slice(0, 16) : "·");
  setText(ui.h.build, L.hello ? L.hello.engine_build : "·");
  setText(ui.h.dac, L.hello ? `${L.hello.capabilities.dac.word_bits}-bit, ${L.hello.capabilities.dac.range_v} V` : "·");
  setText(ui.h.latency, hb && hb.lat_p95 !== null ? `${hb.lat_p95} ms` : "·");
  // late audio callbacks since rigd started (KIOSK-5, QA-ADV-06); a storm is audio_underruns
  const storm = faults.includes("audio_underruns");
  setText(ui.h.underruns, hb && Number.isInteger(hb.underruns) ? (storm ? S("staff", "underruns-storm", { n: hb.underruns }) : String(hb.underruns)) : "·");
  ui.h.underruns.classList.toggle("bad", storm);
  setText(ui.h.keys, L.state ? L.state.keys_raw.map((r) => hex(r, 2)).join(" ") : "·");
  const st = L.staff && L.staff.settings;
  setText(ui.ceiling, st ? `${st.ceiling_dba} dBA` : "·");
  if (st) setToggle(ui.mute, st.muted);
  setText(ui.qFrom, st ? st.quiet_hours.from : "·");
  setText(ui.qTo, st ? st.quiet_hours.to : "·");
  setText(ui.qDba, st ? `${st.quiet_hours.dba} dBA` : "·");
  const s = L.settings;
  setText(ui.idle, s ? `${s.idle_timeout_s} s` : "·");
  if (s) { setToggle(ui.attract, s.attract_sound); setToggle(ui.motion, s.reduced_motion); setToggle(ui.review, s.review_mode); }
  setToggle(ui.disasm, document.body.classList.contains("staff"));
}
