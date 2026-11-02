// meters.js: the live views of the chain (VS-15, PR-13; PLAY-3, NFR-2).
//
// Key matrix as the program last read it (`keys_seen`), the voice map (`watch.voices`),
// the D/A meters (`dac`, stepped exactly as the converter steps them, never smoothed),
// the gate lamps (`gates`). Each is a pure function of the latest state: with the engine
// halted, pressing keys changes none of them (PLAY-3), because `keys_raw` (the only field
// that moves) is never drawn here.

import { el } from "./blocks.js";
import { paint } from "./lamps.js";
import { noteName } from "./keyboard.js";

/** 5 rows x 8 lamps: keys 0-36 and three unused positions, drawn dim. */
export function matrix(parent) {
  const grid = el("div", "matrix");
  grid.dataset.view = "matrix";
  const lamps = [];
  for (let k = 0; k < 40; k++) {
    const l = el("span", "lamp-s" + (k > 36 ? " dim" : ""));
    l.style.width = l.style.height = "27px";
    grid.appendChild(l);
    lamps.push(l);
  }
  parent.appendChild(grid);
  return (state) => {
    for (let k = 0; k < 40; k++) {
      const on = state && k < 37 ? (state.keys_seen[k >> 3] >> (7 - (k & 7))) & 1 : 0;
      paint(lamps[k], on);
    }
  };
}

/** One slot per program voice: the note it holds, or "free". */
export function voices(parent, words) {
  const box = el("div", "voices");
  box.dataset.view = "voices";
  parent.appendChild(box);
  let slots = [];
  let built = -1;
  const build = (n) => {
    box.textContent = "";
    slots = [];
    for (let v = 0; v < n; v++) {
      const row = el("div", "voice" + (n === 1 ? " big" : ""));
      row.appendChild(el("span", "lbl", `V${v + 1}`));
      const nn = el("span", "nn free", words.free);
      const bar = el("span", "bar");
      const fill = el("span");
      bar.appendChild(fill);
      row.append(nn, bar);
      box.appendChild(row);
      slots.push({ row, nn, fill, note: undefined });
    }
    built = n;
  };
  return (state) => {
    const list = state ? state.watch.voices : [];
    const n = Math.max(1, list.length);
    if (n !== built) build(n);
    slots.forEach((s, v) => {
      const note = state ? list[v] ?? null : null;
      if (s.note === note) return;
      s.note = note;
      s.nn.textContent = note === null ? words.free : noteName(note);
      s.nn.classList.toggle("free", note === null);
      s.fill.style.width = note === null ? "0%" : "100%";
    });
  };
}

/** Sixteen D/A meters grouped by the channel map, then eight gate lamps. */
export function dacMeters(parent, channelMap, words) {
  const wrap = el("div");
  wrap.dataset.view = "meters";
  const row = el("div", "meters");
  const bars = [];
  const kind = (i) => {
    const r = channelMap.find((c) => c.line === `dac.${i}`);
    return r && /^pitch/i.test(r.name) ? "pitch" : "tone";
  };
  let last = null;
  for (let i = 0; i < 16; i++) {
    const k = kind(i);
    if (last && k !== last) row.appendChild(el("div", "meter-gap"));
    last = k;
    const m = el("div", `meter ${k}`);
    m.title = (channelMap.find((c) => c.line === `dac.${i}`) || {}).name || `D/A ${i}`;
    const fill = el("span");
    m.appendChild(fill);
    row.appendChild(m);
    bars.push(fill);
  }
  wrap.appendChild(row);
  const gates = el("div");
  gates.style.cssText = "display:flex;gap:10px;margin-top:12px;align-items:center";
  const gl = [];
  for (let g = 0; g < 8; g++) {
    const l = el("span", "lamp-s rose");
    l.style.width = l.style.height = "22px";
    gates.appendChild(l);
    gl.push(l);
  }
  wrap.appendChild(gates);
  const legend = el("div", "meter-legend");
  const lp = el("span", null, words.pitch);
  lp.style.color = "var(--amber)";
  const lt = el("span", null, words.tone);
  lt.style.color = "var(--teal)";
  const lg = el("span", null, words.gate);
  lg.style.color = "var(--rose)";
  legend.append(lp, lt, lg);
  wrap.appendChild(legend);
  parent.appendChild(wrap);
  return (state) => {
    for (let i = 0; i < 16; i++) {
      const h = state ? `${((state.dac[i] / 65536) * 100).toFixed(2)}%` : "0%";
      if (bars[i]._h !== h) { bars[i]._h = h; bars[i].style.height = h; }
    }
    for (let g = 0; g < 8; g++) paint(gl[g], state ? (state.gates >> (15 - g)) & 1 : 0);
  };
}

/** The scope: the engine's own decimated output (AUDIO-6). Small area, 30 Hz at most. */
export function scope(parent) {
  const cv = el("canvas", "scope");
  cv.dataset.view = "scope";
  cv.width = 560;
  cv.height = 240;
  parent.appendChild(cv);
  const cx = cv.getContext("2d");
  let lastSeq = null;
  return (sc) => {
    const seq = sc ? sc.seq : -1;
    if (seq === lastSeq) return;
    lastSeq = seq;
    cx.fillStyle = "#08140f";
    cx.fillRect(0, 0, 560, 240);
    cx.strokeStyle = "#123a2a";
    cx.lineWidth = 1;
    for (let y = 0; y <= 240; y += 60) { cx.beginPath(); cx.moveTo(0, y); cx.lineTo(560, y); cx.stroke(); }
    cx.strokeStyle = sc ? "#7CFFC4" : "#2a4a3a";
    cx.lineWidth = 3;
    cx.shadowColor = "#7CFFC4";
    cx.shadowBlur = sc ? 10 : 0;
    cx.beginPath();
    if (sc) {
      const p = sc.points;
      for (let x = 0; x < 560; x++) {
        const v = p[Math.floor((x / 560) * p.length)];
        const y = 120 - v * 110;
        if (x) cx.lineTo(x, y); else cx.moveTo(x, y);
      }
    } else { cx.moveTo(0, 120); cx.lineTo(560, 120); }
    cx.stroke();
    cx.shadowBlur = 0;
  };
}
