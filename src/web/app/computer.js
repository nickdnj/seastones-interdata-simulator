// computer.js: layer 2, The Computer (PR-06, PR-07, PR-08; PANEL-1, PANEL-2, PANEL-3, PLAY-7).
//
// The 7/16 panel alive, and the speed knob as the hero. Right column: what the lamps say
// right now (PANEL-3, from content), the loop the program repeats (its blocks, lit by where
// the program counter spends its time: pc_hist at speed, the exact block in CRAWL and
// STEP), and the key-to-sound figure from the engine's calibration record.

import { el, svg } from "./blocks.js";
import { S } from "./strings.js";
import * as content from "./content.js";
import * as rig from "./rig.js";
import * as speed from "./speed.js";
import * as listing from "./listing.js";
import { buildFull, paintLamps, drawKnob } from "./panel.js";
import { Keyboard } from "./keyboard.js";
import { paint } from "./lamps.js";

/** Brightness per loop block: its share of pc_hist (at speed) or 1 for the PC's block. */
export function blockLight(state, loop) {
  const out = loop.map(() => 0);
  if (!state) return out;
  const exact = state.lamps.exact;
  loop.forEach((b, i) => {
    if (exact) out[i] = b.lines.some((l) => l.addr === state.pc || (state.pc > l.addr && state.pc < l.addr + 2 * l.words.length)) ? 1 : 0;
    else out[i] = b.lines.reduce((s, l) => s + (state.pc_hist[l.hex] || 0), 0);
  });
  if (!exact) {
    const max = Math.max(...out, 1e-9);
    for (let i = 0; i < out.length; i++) out[i] = Math.round((out[i] / max) * 100) / 100;
  }
  return out;
}

function ring(parent, loop) {
  const box = el("div", "ring");
  const s = svg("svg", { width: 190, height: 190, viewBox: "0 0 190 190", "aria-hidden": "true" }, box);
  const n = Math.max(1, loop.length);
  const segs = [];
  for (let i = 0; i < n; i++) {
    const a0 = (i / n) * 2 * Math.PI - Math.PI / 2 + 0.06;
    const a1 = ((i + 1) / n) * 2 * Math.PI - Math.PI / 2 - 0.06;
    const r = 78;
    const p = (a) => `${95 + r * Math.cos(a)} ${95 + r * Math.sin(a)}`;
    svg("path", { d: `M${p(a0)} A${r} ${r} 0 0 1 ${p(a1)}`, fill: "none", stroke: "#3a2e46", "stroke-width": 22, "stroke-linecap": "round" }, s);
    const lit = svg("path", { d: `M${p(a0)} A${r} ${r} 0 0 1 ${p(a1)}`, fill: "none", stroke: "#F2A83B", "stroke-width": 22, "stroke-linecap": "round", opacity: 0 }, s);
    segs.push(lit);
  }
  const lap = svg("text", { x: 95, y: 104, "text-anchor": "middle", "font-family": "Roboto Slab, Georgia, serif", "font-weight": 800, "font-size": 30, fill: "#F6EBD0" }, s);
  const ol = el("ol");
  const items = loop.map((b, i) => {
    const li = el("li");
    li.appendChild(el("b", null, String(i + 1)));
    const note = content.item("code", b.id);
    li.append(note ? note.title : b.id);
    ol.appendChild(li);
    return li;
  });
  box.appendChild(ol);
  parent.appendChild(box);
  return { segs, items, lap };
}

export function mount(section, ctx) {
  section.textContent = "";
  const parts = buildFull(section, {
    drawn: S("computer", "panel-strip"),
    help: S("computer", "panel-help"),
    addressName: "ADDRESS",
    addressWhat: S("computer", "address").replace(/^[^·]*·\s*/, ""),
    dataName: "DATA",
    dataWhat: S("computer", "data").replace(/^[^·]*·\s*/, ""),
  });
  speed.bindKnob(parts.knob, ctx.stageScale);

  const row = el("div", "comp-row");
  row.appendChild(el("span", "lbl", S("computer", "speed-label")));
  const dets = speed.detents(row);
  const stepBtn = el("button", "btn amber sm", `${S("computer", "step")} ▶`);
  stepBtn.type = "button";
  stepBtn.id = "step-computer";
  stepBtn.style.cssText = "margin-left:14px;min-width:200px";
  speed.stepButton(stepBtn);
  row.appendChild(stepBtn);
  section.appendChild(row);

  const right = el("div", "comp-right");
  const c1 = el("div", "card");
  c1.appendChild(el("div", "lbl amber", S("computer", "lamps-heading")));
  const say = el("div", "say", "");
  say.id = "lamp-caption";
  c1.appendChild(say);
  right.appendChild(c1);
  const c2 = el("div", "card");
  c2.appendChild(el("div", "lbl amber", S("computer", "loop-heading")));
  const ringBox = el("div");
  ringBox.style.marginTop = "10px";
  c2.appendChild(ringBox);
  right.appendChild(c2);
  section.appendChild(right);

  // Key to sound sits in the bottom row beside the speed controls it depends on.
  const c3 = el("div", "card k2s-card");
  const k2sHead = el("div", "k2s-head");
  k2sHead.appendChild(el("div", "lbl amber", S("computer", "key-to-sound-heading")));
  const fig = el("div", "big-fig", "·");
  fig.id = "k2s-big";
  k2sHead.appendChild(fig);
  c3.appendChild(k2sHead);
  c3.appendChild(el("div", "estimate", S("speed", "estimate")));
  section.appendChild(c3);

  const kbBox = el("div");
  kbBox.className = "comp-kb";
  new Keyboard(kbBox, { width: 1804, height: 96, slim: true });
  section.appendChild(kbBox);

  let r = null;
  let knobFor = null;
  let setKnob = null;
  return {
    paint(state, banks) {
      paintLamps(parts, banks, state);
      const plate = !state ? "·" : state.halted ? S("computer", "halted") : state.speed === "step" || state.waiting ? S("computer", "waiting") : S("computer", "running");
      if (parts.plate.textContent !== plate.toUpperCase()) parts.plate.textContent = plate.toUpperCase();
      dets(state);
      if (rig.live.hello && knobFor !== rig.live.hello) {
        setKnob = drawKnob(parts.knob, rig.speeds().map((s) => s.label), { size: 300, onFace: true });
        knobFor = rig.live.hello;
      }
      if (setKnob && state) setKnob(speed.index(state.speed));
      stepBtn.classList.toggle("off", !state || state.speed !== "step");
      const ro = speed.readoutText(state);
      if (say.textContent !== (ro.lamp || "")) say.textContent = ro.lamp || "";
      if (fig.textContent !== (ro.k2s || "·")) {
        fig.textContent = ro.k2s || "·";
        fig.classList.toggle("words", !/^[\d·]/.test(fig.textContent)); // "waits for STEP" is words, not a figure
      }
      const lst = listing.get();
      if (lst && !r) r = ring(ringBox, lst.loop);
      if (r) {
        const light = blockLight(state, lst.loop);
        r.segs.forEach((sg, i) => { if (sg._o !== light[i]) { sg._o = light[i]; sg.setAttribute("opacity", String(0.15 + 0.85 * light[i])); } });
        r.items.forEach((li, i) => li.classList.toggle("on", light[i] >= 0.5));
        const laps = state ? Math.round(state.scan_hz).toLocaleString("en-US") : "·";
        if (r.lap.textContent !== laps) r.lap.textContent = laps;
      }
    },
  };
}

export { paint };
