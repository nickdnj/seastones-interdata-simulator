// play.js: layer 1, Play (PR-13, PM-15, PR-12; PLAY-1, PLAY-3, PLAY-4, PLAY-6, PLAY-7, AUDIO-6).
//
// The five stations, left to right, are the chain a key press travels: the key matrix the
// program read, the panel lamps, the voice map, the sixteen D/A wires and the gates, the
// scope. Each is drawn from the engine's state alone, so when the computer is slowed they
// light up late, in data-flow order, and that is the lesson (UX 5.2, 7.1).

import { el } from "./blocks.js";
import { S, M } from "./strings.js";
import { fit, refitOnFonts } from "./fit.js";
import * as content from "./content.js";
import * as rig from "./rig.js";
import * as protocol from "./protocol.js";
import * as speed from "./speed.js";
import * as meters from "./meters.js";
import { buildMini, paintLamps, drawKnob } from "./panel.js";
import { Keyboard } from "./keyboard.js";
import { tap } from "./touch.js";

const CHEVRON = '<svg width="28" height="40" viewBox="0 0 28 40" aria-hidden="true"><path d="M5 6l16 14L5 34" fill="none" stroke="#F2A83B" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/></svg>';
const SPEAKER = '<svg width="56" height="44" viewBox="0 0 56 44" aria-hidden="true"><rect x="4" y="4" width="30" height="36" rx="5" fill="#3a2e46"/><circle cx="19" cy="16" r="5" fill="#120d18"/><circle cx="19" cy="29" r="8" fill="#120d18"/><path d="M34 12l16-8v36l-16-8z" fill="#7B5BB0"/></svg>';

/**
 * Presets in kiosk.conf preset_order, then any others; the first is the default patch. Only
 * those written for the engine's voice count: a four-voice patch cannot load on the
 * eight-voice map (rigd refuses it), so it is never offered there.
 */
export function presets() {
  const v = rig.live.hello ? rig.live.hello.capabilities.voices : null;
  const all = content.items("presets").filter((p) => !v || !p.voices || Number(p.voices) === v);
  const order = content.confList("preset_order");
  const ranked = order.map((s) => all.find((p) => p.slug === s)).filter(Boolean);
  return [...ranked, ...all.filter((p) => !order.includes(p.slug))];
}
export const defaultPreset = () => (presets()[0] || {}).slug || null;

/** Load a preset through the engine; the chip lights when the engine says it is loaded. */
export const loadPreset = (slug) => protocol.load(slug);

/** PUT IT BACK: the default patch and full speed, in one tap (UX 5.2). */
export async function putItBack(toast) {
  const slug = defaultPreset();
  if (slug) protocol.load(slug);
  else protocol.home(); // no preset for this map: the engine's own default patch
  protocol.speed("run");
  if (toast) toast(S("play", "put-back-toast"));
}

/** The chip strip (also used by Patch). Returns paint(). */
export function chips(parent) {
  const row = el("div", "chips");
  let list = [];
  let key = null;
  // The strip follows the engine's voice count and review mode (CT-07 shows the draft
  // presets): it is rebuilt when either changes, never per frame.
  const build = () => {
    // only the chips: Play keeps its PUT IT BACK button at the end of this row
    for (const c of list) c.remove();
    list = [];
    const after = row.firstChild;
    for (const p of presets()) {
      const c = el("button", "chip", p.title);
      c.type = "button";
      c.dataset.preset = p.slug;
      c.setAttribute("aria-pressed", "false");
      tap(c, () => loadPreset(p.slug));
      row.insertBefore(c, after); // before anything else in the row, in preset order
      list.push(c);
    }
    // review mode's longer strip: smaller words, the same 72 px touch height
    row.classList.toggle("many", list.length > 6);
  };
  parent.appendChild(row);
  // Rebuilt the moment review mode or the engine's voice count changes, whether or not this
  // strip's layer is showing: building it only in paint left a hidden layer's strip stale
  // until its first frame (the flaky review-mode test).
  const refresh = () => {
    const k = `${content.reviewMode()}|${rig.live.hello ? rig.live.hello.capabilities.voices : "?"}`;
    if (k !== key) { key = k; build(); }
  };
  content.onReviewChange(refresh);
  rig.on("hello", refresh);
  rig.on("status", refresh);
  const paint = () => {
    refresh();
    const cur = rig.live.patch ? rig.live.patch.preset : null;
    for (const c of list) {
      const on = c.dataset.preset === cur;
      if (c._on !== on) { c._on = on; c.classList.toggle("on", on); c.setAttribute("aria-pressed", String(on)); }
    }
  };
  paint();
  return { row, paint };
}

/** The one-line audio caption (UX 7.2): what is sounding, and what changed. */
export function audioCaption(state) {
  if (!state) return "";
  const patch = rig.live.patch;
  if (state.speed === "step" || state.halted) return S("play", "caption-stepping");
  if (patch && !patch.reaches_out) return S("play", "caption-nothing-out");
  if (state.speed !== "run") return S("play", "caption-slowed");
  const sounding = state.watch.voices.filter((v) => v !== null).length;
  if (!sounding) return S("play", "caption-silent");
  const p = patch && patch.preset && content.item("presets", patch.preset);
  return S("play", "caption-sounding", { preset: p ? p.title : "·", voices: `${sounding} ${S("play", "voice-label").toLowerCase()}${sounding > 1 ? "s" : ""}` });
}

export function mount(section, ctx) {
  section.textContent = "";
  const chain = el("div", "chain");
  const station = (n, width, doorway) => {
    const card = el(doorway ? "button" : "div", "card station");
    if (doorway) {
      card.type = "button";
      tap(card, () => ctx.go(doorway));
    }
    card.id = `station-${n}`;
    card.style.width = `${width}px`;
    card.appendChild(el("div", "lbl amber", S("play", `station-${n}`)));
    const body = el("div", "body");
    card.appendChild(body);
    const cap = el("div", "cap", M("play", `station-${n}`));
    card.appendChild(cap);
    chain.appendChild(card);
    // a caption at its limit steps down to the 22 px floor rather than overflow the station;
    // the observer fires when the layer is first shown and the card gets its size
    const refit = () => fit(card, (px) => { cap.style.fontSize = `${px}px`; }, 25, 22);
    fits.push(refitOnFonts(refit));
    if (typeof ResizeObserver === "function") new ResizeObserver(refit).observe(card);
    return body;
  };
  const fits = [];
  const chev = () => chain.insertAdjacentHTML("beforeend", `<span class="chev">${CHEVRON}</span>`);

  const v = {};
  v.matrix = meters.matrix(station(1, 300, null));
  chev();
  v.mini = buildMini(station(2, 340, "computer"));
  chev();
  v.voices = meters.voices(station(3, 300, "code"), { free: S("play", "voice-free"), voice: S("play", "voice-label") });
  chev();
  v.dac = meters.dacMeters(station(4, 440, "patch"), content.rigTable("channel-map"), {
    pitch: S("play", "group-pitch"), gate: S("play", "group-gate"), tone: S("play", "group-tone"),
  });
  chev();
  const s5 = station(5, 330, "patch");
  const sbox = el("div");
  sbox.style.width = "100%";
  v.scope = meters.scope(sbox);
  const under = el("div");
  under.style.cssText = "display:flex;align-items:center;gap:10px;margin-top:10px";
  under.insertAdjacentHTML("beforeend", SPEAKER);
  v.caption = el("span", null, "");
  v.caption.id = "audio-caption";
  v.caption.style.cssText = "font-size:22px;line-height:1.2;color:var(--muted)";
  under.appendChild(v.caption);
  sbox.appendChild(under);
  s5.appendChild(sbox);
  section.appendChild(chain);

  const left = el("div", "controls-left");
  left.appendChild(el("div", "lbl", S("play", "sounds")));
  v.chips = chips(left);
  const pib = el("button", "btn amber sm", S("play", "put-it-back"));
  pib.type = "button";
  pib.id = "putback";
  pib.style.marginLeft = "6px";
  tap(pib, () => putItBack(ctx.toast));
  v.chips.row.appendChild(pib);
  section.appendChild(left);

  const card = el("div", "card speed-card");
  const knob = el("div", "knob");
  knob.id = "play-knob";
  knob.style.cssText = "width:150px;height:150px";
  knob.setAttribute("role", "slider");
  knob.setAttribute("aria-label", "Speed control");
  card.appendChild(knob);
  const right = el("div");
  right.style.flex = "1";
  right.appendChild(el("div", "lbl amber", S("play", "slow-title")));
  v.dets = speed.detents(right);
  const ro = el("div", "readout");
  v.say = el("span", null, "");
  v.say.id = "speed-say";
  const k2s = el("span", "k2s", ` ${S("play", "key-to-sound")} `);
  v.k2s = el("b", null, "");
  v.k2s.id = "k2s";
  k2s.appendChild(v.k2s);
  ro.append(v.say, k2s);
  right.appendChild(ro);
  card.appendChild(right);
  v.fitReadout = refitOnFonts(() => fit(card, (px) => { ro.style.fontSize = `${px}px`; }, 25, 22));
  section.appendChild(card);
  speed.bindKnob(knob, ctx.stageScale);
  v.knobFace = null;
  v.knob = knob;

  const notice = el("div", "kb-notice", S("faults", "keyboard-lost"));
  // under the speed card, clear of the chips' second row and above the keys (QA-ADV-04)
  notice.style.cssText = "top:592px;left:1080px;right:48px;height:34px;font-size:22px";
  notice.hidden = true;
  notice.id = "kb-notice-play";
  section.appendChild(notice);
  v.notice = notice;
  const kbBox = el("div");
  kbBox.style.cssText = "position:absolute;left:48px;top:630px";
  new Keyboard(kbBox, { width: 1804, height: 180 });
  section.appendChild(kbBox);

  return {
    paint(state, banks) {
      v.matrix(state);
      paintLamps(v.mini, banks, state);
      v.voices(state);
      // the voice rows are built from the engine's voice count, after mount: refit the
      // station captions when that count changes (station 3 grows with it)
      const nVoices = state ? state.watch.voices.length : 0;
      if (nVoices !== v.nVoices) { v.nVoices = nVoices; for (const f of fits) f(); }
      v.dac(state);
      v.scope(rig.live.scope);
      v.chips.paint();
      v.dets(state);
      if (rig.live.hello && v.knobFace !== rig.live.hello) {
        v.setKnob = drawKnob(v.knob, rig.speeds().map((s) => s.label), { size: 150, onFace: false });
        v.knobFace = rig.live.hello;
      }
      if (v.setKnob && state) v.setKnob(speed.index(state.speed));
      const r = speed.readoutText(state);
      let words = false;
      if (v.say.textContent !== r.say) { v.say.textContent = r.say; words = true; }
      if (v.k2s.textContent !== r.k2s) { v.k2s.textContent = r.k2s; words = true; }
      if (words) v.fitReadout();
      const cap = audioCaption(state);
      if (v.caption.textContent !== cap) { v.caption.textContent = cap; for (const f of fits) f(); }
      const hb = rig.live.heartbeat;
      // The unplug notice (INPUT-3, UX 5.8): only while rigd's midi_absent fault is up, which
      // it raises when a keyboard is unplugged. A station that never had a keyboard (the
      // touch-only mirror, UX 9) has midi_present false and no fault, and says nothing.
      const unplugged = rig.live.faults.has("midi_absent") || !!(hb && hb.faults.includes("midi_absent"));
      v.notice.hidden = !unplugged;
    },
  };
}
