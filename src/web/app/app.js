// app.js: wiring, the layer model, HOME and the render loop (PM-00, KP-01; PLAY-1, PLAY-9).
//
// Layers 0 to 5: attract, play, computer, code, patch, story. Layer 6 has no code path in
// v1 (SEA-3, KP-01). The engine always runs, so the attract scan loop is real and the first
// key sounds from any state. HOME, from anywhere: Play, default patch, RUN, every note
// released, drags cancelled, any veil closed (UX 6.5). The page makes no sound.
//
// Rendering is a pure function of the latest engine state: the `state` handler feeds the
// lamp banks, and one requestAnimationFrame loop paints the visible layer from rig.live.

import * as content from "./content.js";
import { CONTENT_DOWN } from "./strings.js";
import * as rig from "./rig.js";
import * as protocol from "./protocol.js";
import * as shell from "./shell.js";
import * as touch from "./touch.js";
import * as keyboard from "./keyboard.js";
import * as listing from "./listing.js";
import * as speed from "./speed.js";
import * as idle from "./idle.js";
import * as errors from "./errors.js";
import { LampBank } from "./lamps.js";
import { el } from "./blocks.js";
import * as attract from "./attract.js";
import * as play from "./play.js";
import * as computer from "./computer.js";
import * as code from "./code.js";
import * as patch from "./patch.js";
import * as story from "./story.js";
import * as about from "./about.js";
import * as staff from "./staff.js";
import * as volume from "./volume.js";
import { S } from "./strings.js";

const stage = document.getElementById("stage");
let scale = 1;
const banks = { addr: new LampBank(16), data: new LampBank(16) };
const views = {};
let layer = "attract";
let prevRawBits = 0n;
let wasFaulted = false;
const said = { speed: null, preset: null, fault: null };

function fit() {
  scale = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = `translate(-50%, -50%) scale(${scale})`;
}

function contours() {
  const g = document.getElementById("contours");
  const cols = ["#F2A83B", "#F07FA3", "#7B5BB0"];
  let h = "";
  for (let i = 0; i < 14; i++) {
    const y = 520 + i * 34;
    const a = 18 + (i % 4) * 6;
    h += `<path d="M-40 ${y} q120 -${a} 240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0" stroke="${cols[i % 3]}" opacity="${(0.05 + i * 0.012).toFixed(3)}"/>`;
  }
  g.innerHTML = h;
}

const isLoopback = () => ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
const params = new URLSearchParams(location.search);

let framesSinceGo = 0;
const paintedSince = () => framesSinceGo >= 2;

export function go(name) {
  about.hide();
  volume.close();
  if (name === layer) return;
  framesSinceGo = 0;
  layer = name;
  stage.classList.toggle("attract", name === "attract");
  for (const s of document.querySelectorAll(".layer")) s.classList.toggle("on", s.dataset.layer === name);
  shell.setLayer(name);
  if (name === "story") views.story.show(views.story.current());
}

export function home() {
  about.hide();
  volume.close();
  keyboard.releaseAll();
  views.patch.reset();
  protocol.home();
  idle.activity();
  go("play");
}

function idleReset() {
  about.hide();
  volume.close();
  keyboard.releaseAll();
  views.patch.reset();
  views.story.reset();
  protocol.home();
  go("attract");
}

function wake() {
  if (layer === "attract" && wasFaulted === false) go("play");
}

function contentDown() {
  const box = el("div", "content-down");
  const card = el("div", "card fcard");
  card.style.cssText = "width:1240px;padding:46px 56px 34px";
  const h = el("h2", null, CONTENT_DOWN.headline);
  h.style.cssText = "font-family:var(--f-display);font-weight:800;font-size:64px;margin:0 0 16px";
  card.append(h, el("p", "sentence", CONTENT_DOWN.body), el("div", "staffline", `${CONTENT_DOWN.staff} · ${content.failureReason()}`));
  card.querySelector(".sentence").style.cssText = "font-size:34px";
  box.appendChild(card);
  stage.appendChild(box);
  stage.classList.add("no-content");
  setTimeout(() => location.reload(), 30000);
}

function paint() {
  const st = rig.live.state;
  const faulted = errors.update({
    connected: rig.live.connected,
    everConnected: rig.live.everConnected,
    heartbeat: rig.live.heartbeat,
    faults: [...rig.live.faults.keys()],
    mismatch: rig.live.mismatch,
  });
  // Recovery: when every stage is really back the station starts over at attract (UX 5.8);
  // while it is starting it waits there.
  if ((wasFaulted === true && faulted !== true) || faulted === "starting") { if (layer !== "attract") go("attract"); }
  wasFaulted = faulted;
  shell.setDockEnabled(faulted !== true);
  shell.setSpeed(speed.label(st), speed.isSlowed(st));
  shell.setScan(st ? Math.round(st.scan_hz).toLocaleString("en-US") : "·");
  // live regions (A-29): what changed, in the words already on screen
  if (st && st.speed !== said.speed) { said.speed = st.speed; shell.announce(`${speed.label(st)}. ${speed.readoutText(st).say}`); }
  const pr = rig.live.patch && rig.live.patch.preset;
  if (pr && pr !== said.preset) { said.preset = pr; const p = content.item("presets", pr); if (p) shell.announce(p.title); }
  const fh = faulted === true ? document.getElementById("fault-headline").textContent : null;
  if (fh !== said.fault) { said.fault = fh; if (fh) shell.announce(fh, true); }
  const ready = rig.live.connected && faulted === false;
  if (layer === "attract") views.attract.paint(st, banks, ready, rig.live.heartbeat && rig.live.heartbeat.stages);
  else if (views[layer] && views[layer].paint) views[layer].paint(st, banks);
  staff.paint();
  volume.paint();
  framesSinceGo += 1;
  requestAnimationFrame(paint);
}

async function boot() {
  fit();
  addEventListener("resize", fit);
  contours();
  touch.install(document);
  touch.setScale(() => scale);
  if (!(await content.load())) { contentDown(); return; }
  if (content.confFlag("reduced_motion", false)) document.body.classList.add("reduced");
  listing.load();

  const ctx = { go, stageScale: () => scale, toast: shell.toast };
  const frame = shell.build({
    onLayer: (n) => go(n),
    onHome: home,
    onFullSpeed: () => protocol.speed("run"),
    onAbout: () => about.show(),
  });
  about.install(stage);
  volume.install(stage);
  staff.install(stage, frame.mark, { stageScale: () => scale, about: () => about.show() });
  const banner = el("div", "review-banner", S("staff", "review-banner"));
  banner.id = "review-banner";
  banner.hidden = true;
  stage.appendChild(banner);
  views.attract = attract.mount(document.getElementById("layer-attract"), { onWake: wake });
  views.play = play.mount(document.getElementById("layer-play"), ctx);
  views.computer = computer.mount(document.getElementById("layer-computer"), ctx);
  views.code = code.mount(document.getElementById("layer-code"), ctx);
  views.patch = patch.mount(document.getElementById("layer-patch"), ctx);
  views.story = story.mount(document.getElementById("layer-story"));
  errors.install();

  const heldMs = content.confNumber("held_key_release_s", 60) * 1000;
  speed.configureStep({ holdCapMs: heldMs });
  keyboard.configure({ heldKeyMs: heldMs, qwerty: content.confFlag("dev_qwerty", false) || (params.get("dev") === "1" && isLoopback()) });
  idle.configure({
    timeoutMs: content.confNumber("idle_timeout_s", 90) * 1000,
    warningMs: content.confNumber("idle_warning_s", 15) * 1000,
    heldMs,
  });
  idle.install({ reset: idleReset, attract: () => layer === "attract", held: keyboard.anyHeld, paused: () => staff.open() || staff.pinOpen() });

  // Staff settings the page follows (KP-08, CT-07): sent by rigd at connect and on change.
  const confReduced = content.confFlag("reduced_motion", false);
  rig.on("settings", (s) => {
    document.body.classList.toggle("reduced", confReduced || s.reduced_motion);
    idle.configure({ timeoutMs: s.idle_timeout_s * 1000 });
    if (content.reviewMode() !== s.review_mode) { content.setReviewMode(s.review_mode); views.story.show(null); }
    banner.hidden = !s.review_mode;
  });
  touch.onActivity((kind) => { idle.activity(); if (kind !== "move") wake(); });

  rig.on("state", (st) => {
    banks.addr.update(st.lamps.addr, st.lamps.exact, st.frames);
    banks.data.update(st.lamps.data, st.lamps.exact, st.frames);
    idle.sawKeys(st.keys_raw);
    let bits = 0n;
    st.keys_raw.forEach((row, r) => { bits |= BigInt(row) << BigInt(r * 8); });
    if (bits & ~prevRawBits) wake(); // a physical key wakes the attract screen (it already sounds)
    prevRawBits = bits;
  });
  rig.on("status", (up) => { if (!up) { banks.addr.clear(); banks.data.clear(); } });

  // The rig URL comes from kiosk.conf; a loopback page may override it for tests (?rig=).
  const override = params.get("rig");
  const url = override && isLoopback() && /^ws:\/\/(127\.0\.0\.1|localhost):\d+\/?$/.test(override) ? override : content.conf("rig_url", "ws://127.0.0.1:7690");
  rig.connect(url, { deadline: content.confNumber("heartbeat_deadline_s", 3) * 1000 });
  keyboard.start();
  setInterval(() => { fetch("/heartbeat", { method: "POST" }).catch(() => {}); }, 10000);

  // Test hooks, loopback only and only when asked for (VS-27 decides the production profile).
  if (params.get("hooks") === "1" && isLoopback()) {
    window.__seastones = {
      go, home, live: rig.live, banks, layer: () => layer,
      setReview: (on) => { content.setReviewMode(on); views.story.show(null); },
      setStaff: (on) => document.body.classList.toggle("staff", on),
      // a layer is settled when it is shown, its slide-in has finished, the data it is built
      // from has arrived, and it has painted since: tests read layout only then
      settled: (name) => {
        const sec = document.querySelector(`.layer[data-layer="${name}"]`);
        if (!sec || !sec.classList.contains("on") || layer !== name) return false;
        if (document.fonts && document.fonts.status !== "loaded") return false;
        if (sec.getAnimations({ subtree: true }).some((a) => a.playState === "running" && a.animationName === "layer-in")) return false;
        if ((name === "code" || name === "computer") && !listing.get()) return false;
        if (name === "computer" && !sec.querySelector(".ring li")) return false;
        if (name === "patch" && !(rig.live.patch && sec.querySelector("#wall .jackhit"))) return false;
        return paintedSince(name);
      },
      // short timings for tests of the idle rules (loopback test hooks only)
      timings: ({ timeoutMs, warningMs, stepCapMs }) => {
        if (timeoutMs) idle.configure({ timeoutMs, warningMs });
        if (stepCapMs) speed.configureStep({ holdCapMs: stepCapMs });
      },
    };
  }
  document.querySelector(`.layer[data-layer="attract"]`).classList.add("on");
  shell.setLayer("attract");
  requestAnimationFrame(paint);
}

boot();
