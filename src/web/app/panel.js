// panel.js: the 7/16 front panel, drawn by us (PR-05, PR-06; PANEL-1, PANEL-2, DES-2).
//
// A pure function of the latest `state` and the panel model (content/rig/panel.md):
// ADDRESS lamps are the PC, DATA lamps the instruction word at the PC, each lamp's
// brightness its duty cycle (lamps.js). A hex digit sits under each group of four and is
// shown only when the engine says the value is exact (CRAWL, STEP, halted); at speed it is
// a dot, because a digit that changes thousands of times a second would be a lie (UX 5.3).
//
// The layout is inferred and labelled "Panel drawn from Interdata documentation" (R7): the
// bitsavers search found that the 7/16 shipped with a binary or a hex display panel and
// we do not know which Lagin had. No scan or photograph is shown or traced (RIGHTS-6).

import { el, esc } from "./blocks.js";
import { paint } from "./lamps.js";

const HEX = "0123456789ABCDEF";

function lampRow(parent, cls) {
  const lamps = [];
  const hexes = [];
  const row = el("div", "lamprow");
  for (let g = 0; g < 4; g++) {
    const grp = el("div", "lampgrp");
    const ls = el("div", "ls");
    for (let i = 0; i < 4; i++) {
      const l = el("span", "lamp-s" + (cls ? ` ${cls}` : ""));
      l.dataset.bit = String(g * 4 + i);
      ls.appendChild(l);
      lamps.push(l);
    }
    grp.appendChild(ls);
    const h = el("div", "hex", "•");
    grp.appendChild(h);
    hexes.push(h);
    row.appendChild(grp);
  }
  parent.appendChild(row);
  return { lamps, hexes };
}

/** The full panel for The Computer. Returns the parts paint() needs. */
export function buildFull(parent, words) {
  const enc = el("div", "enclosure");
  enc.style.cssText = "position:absolute;left:48px;top:8px;width:1180px;height:596px";
  const face = el("div", "face");
  const strip = el("div", "strip");
  strip.appendChild(el("span", "name", "INTERDATA 7/16"));
  strip.appendChild(el("span", "drawn", words.drawn));
  face.appendChild(strip);
  for (const [x, y] of [[14, 76], [1130, 76], [14, 540], [1130, 540]]) {
    const s = el("span", "screw");
    s.style.left = `${x}px`;
    s.style.top = `${y}px`;
    face.appendChild(s);
  }
  const knobBox = el("div");
  knobBox.style.cssText = "position:absolute;left:30px;top:80px;width:300px";
  const kl = el("div", "legend", "SPEED CONTROL");
  kl.style.cssText = "text-align:center;margin-bottom:4px";
  knobBox.appendChild(kl);
  const knob = el("div", "knob");
  knob.id = "panel-knob";
  knob.style.cssText = "width:300px;height:300px;margin-top:6px";
  knob.setAttribute("role", "slider");
  knob.setAttribute("aria-label", "Speed control");
  knobBox.appendChild(knob);
  face.appendChild(knobBox);
  const help = el("div", null, words.help);
  help.style.cssText = "position:absolute;left:44px;top:440px;width:290px;font-size:24px;line-height:1.25;color:var(--ink-muted)";
  face.appendChild(help);

  const a = el("div");
  a.style.cssText = "position:absolute;left:366px;top:96px";
  const al = el("div", "legend", words.addressName);
  al.appendChild(el("span", null, ` · ${words.addressWhat}`));
  al.style.marginBottom = "12px";
  a.appendChild(al);
  const addr = lampRow(a);
  face.appendChild(a);
  const d = el("div");
  d.style.cssText = "position:absolute;left:366px;top:290px";
  const dl = el("div", "legend", words.dataName);
  dl.appendChild(el("span", null, ` · ${words.dataWhat}`));
  dl.style.marginBottom = "12px";
  d.appendChild(dl);
  const data = lampRow(d);
  face.appendChild(d);
  const st = el("div");
  st.style.cssText = "position:absolute;left:366px;top:488px;display:flex;gap:16px;align-items:center";
  st.appendChild(el("span", "legend", "STATE"));
  const plate = el("span", "stateplate", "·");
  plate.id = "stateplate";
  st.appendChild(plate);
  face.appendChild(st);
  enc.appendChild(face);
  parent.appendChild(enc);
  return { addr, data, plate, knob };
}

/** The mini panel on Play's station 2. */
export function buildMini(parent) {
  const mini = el("div", "mini");
  const face = el("div", "face");
  face.appendChild(el("div", "legend", "ADDRESS"));
  const a = el("div", "lamprow");
  const addr = { lamps: [], hexes: [] };
  for (let i = 0; i < 16; i++) {
    const l = el("span", "lamp-s");
    l.style.marginRight = i % 4 === 3 ? (i === 15 ? "0" : "8px") : "2px";
    a.appendChild(l);
    addr.lamps.push(l);
  }
  face.appendChild(a);
  const dl = el("div", "legend", "DATA");
  dl.style.marginTop = "12px";
  face.appendChild(dl);
  const d = el("div", "lamprow");
  const data = { lamps: [], hexes: [] };
  for (let i = 0; i < 16; i++) {
    const l = el("span", "lamp-s");
    l.style.marginRight = i % 4 === 3 ? (i === 15 ? "0" : "8px") : "2px";
    d.appendChild(l);
    data.lamps.push(l);
  }
  face.appendChild(d);
  const nm = el("div", "legend", "INTERDATA 7/16");
  nm.style.cssText = "font-weight:400;color:var(--ink-muted);margin-top:10px";
  face.appendChild(nm);
  mini.appendChild(face);
  parent.appendChild(mini);
  return { addr, data };
}

/** Paint lamps (and hex digits, when exact) from the lamp banks and the state. */
export function paintLamps(parts, banks, state) {
  for (let i = 0; i < 16; i++) {
    paint(parts.addr.lamps[i], state ? banks.addr.b[i] : 0);
    paint(parts.data.lamps[i], state ? banks.data.b[i] : 0);
  }
  if (!parts.addr.hexes.length) return;
  const exact = !!(state && state.lamps.exact);
  const word = state ? wordFromLamps(state.lamps.data) : 0;
  for (let g = 0; g < 4; g++) {
    const ha = exact ? HEX[(state.pc >> (12 - 4 * g)) & 15] : "•";
    const hd = exact ? HEX[(word >> (12 - 4 * g)) & 15] : "•";
    if (parts.addr.hexes[g].textContent !== ha) parts.addr.hexes[g].textContent = ha;
    if (parts.data.hexes[g].textContent !== hd) parts.data.hexes[g].textContent = hd;
  }
}

/** The 16-bit word an exact lamp row spells (bit 0 is the MSB). */
export function wordFromLamps(fracs) {
  return fracs.reduce((v, f) => (v << 1) | (f >= 0.5 ? 1 : 0), 0);
}

/** The speed knob face: legends round the dial and a pointer at 50 degrees per detent. */
export function drawKnob(host, labels, { size = 300, onFace = true } = {}) {
  const c = size / 2;
  const ang = (i) => -125 + 50 * i;
  let h = `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">`;
  h += `<defs><radialGradient id="kg-${size}" cx=".4" cy=".32"><stop offset="0" stop-color="#f1ede4"/><stop offset=".7" stop-color="#a39c8e"/><stop offset="1" stop-color="#6f695d"/></radialGradient></defs>`;
  if (onFace) {
    const at = [[50, 227], [32, 125], [98, 46], [202, 46], [268, 125], [250, 227]];
    labels.forEach((t, i) => {
      const [x, y] = at[i] || [c, c];
      h += `<text x="${(x * size) / 300}" y="${(y * size) / 300}" text-anchor="middle" font-family="Oswald, Arial Narrow, sans-serif" font-weight="700" font-size="24" letter-spacing="1" fill="#1C1A17">${esc(t)}</text>`;
    });
  } else {
    for (let i = 0; i < labels.length; i++) {
      h += `<line x1="${c}" y1="${size * 0.06}" x2="${c}" y2="${size * 0.13}" stroke="#F2A83B" stroke-width="4" transform="rotate(${ang(i)} ${c} ${c})"/>`;
    }
  }
  const rk = onFace ? size * 0.27 : size * 0.35;
  h += `<circle cx="${c}" cy="${c}" r="${onFace ? size * 0.33 : size * 0.47}" fill="${onFace ? "none" : "#14101a"}" stroke="${onFace ? "none" : "#4a3a58"}" stroke-width="3"/>`;
  h += `<g class="ptr" data-ptr="1"><circle cx="${c}" cy="${c}" r="${rk}" fill="url(#kg-${size})" stroke="#000" stroke-width="2"/>`;
  h += `<circle cx="${c}" cy="${c}" r="${rk * 0.78}" fill="none" stroke="#0003" stroke-width="2"/>`;
  h += `<rect x="${c - size * 0.024}" y="${c - rk * 0.92}" width="${size * 0.048}" height="${rk * 0.56}" rx="4" fill="#B83A24"/></g></svg>`;
  host.innerHTML = h;
  const ptr = host.querySelector("[data-ptr]");
  return (i) => {
    const t = `rotate(${ang(i)}deg)`;
    if (ptr.style.transform !== t) ptr.style.transform = t;
  };
}
