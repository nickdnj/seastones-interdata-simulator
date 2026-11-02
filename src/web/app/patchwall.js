// patchwall.js: the module wall, drawn by us (PM-10, PM-12, PM-18; PATCH-2, PATCH-7, RIGHTS-5).
//
// Our own module plates in the spirit of a 1970s modular: brushed panels, a coloured band
// per module type, silkscreened caps, big round jacks. Generic names only (VOICE, FILTER,
// ECHO); no E-mu, ARP or Buchla marks, panel layouts or logos (DESIGN-SYSTEM 1.1, B-05).
// All vector, no raster image.
//
// What is on the wall is the loaded patch's own graph (the engine format, wallmodel.js): one
// voice card per voice of the channel map, one plate per global module, with the ports its
// type has. The engine sends that layout in every `patch` message; the rail's channel names
// come from content/rig/ (channel-map.md, or channel-map-8.md for the eight-voice map).

import { esc } from "./blocks.js";
import { jacksOf } from "./wallmodel.js";

export const W = 1824;
export const H = 600;

const BAND = { voice: "#E4572E", noise: "#B5BAC1", lfo: "#7B5BB0", slew: "#7B5BB0", mixer: "#4FC3B5", vcf: "#7B5BB0", echo: "#4FC3B5", out: "#F2A83B", rail: "#F2A83B" };
const X0 = 424; // the rail is 0 to 410
const ROW = 150; // plate 140 tall, 10 apart: four rows in 600
// jack centres: 54 px touch targets 8 px apart (UI-25, UX A-06; QA-ADV report §3 item 7)
const PITCH = 62;
export const RAIL_PITCH = 62;
const plateW = (title, n) => Math.max(Math.ceil(title.length * 17) + 40, 80 + (n - 1) * PITCH);

/** The content table naming the rail's lines for a channel map. */
export const railTable = (map) => (map === "latch-8" ? "channel-map-8" : "channel-map");

/**
 * Plates and jacks, in stage px inside the wall, for a layout description (the `patch`
 * message's layout). Plates flow left to right in rows; `overflow` says some did not fit.
 */
export function layout(channelMap, desc) {
  const name = (id, dflt) => (channelMap.find((c) => c.line === id) || {}).name || dflt;
  const plates = [];
  const jacks = [];
  plates.push({ id: "rail", x: 0, y: 0, w: 410, h: H, title: null, band: BAND.rail });
  const all = desc ? jacksOf(desc) : jacksOf({ rail: { gates: false }, voices: { count: 0, ports: [] }, modules: [] });
  for (const j of all.filter((x) => x.plate === "rail")) {
    const k = Number(j.id.split(".")[1]);
    const x = j.kind === "gate" ? 314 : k < 8 ? 46 : 180;
    jacks.push({ ...j, x, y: 132 + (k % 8) * RAIL_PITCH, label: name(j.id, j.kind === "gate" ? `Gate ${k + 1}` : `D/A ${k}`) });
  }
  if (!desc) return { plates, jacks, gates: false, overflow: false };
  const groups = [];
  for (let n = 1; n <= desc.voices.count; n++) groups.push({ id: `v${n}`, title: `VOICE ${n}`, band: BAND.voice });
  for (const m of desc.modules) groups.push({ id: m.id, title: m.title, band: BAND[m.type] || "#B5BAC1" });
  let x = X0, y = 0, overflow = false;
  for (const g of groups) {
    const js = all.filter((j) => j.plate === g.id);
    const w = plateW(g.title, js.length);
    if (x + w > W) { x = X0; y += ROW; }
    if (y + 140 > H) overflow = true;
    plates.push({ id: g.id, x, y, w, h: 140, title: g.title, band: g.band, titleY: 14 });
    js.forEach((j, i) => jacks.push({ ...j, x: x + 40 + i * PITCH, y: y + 76 }));
    x += w + 12;
  }
  return { plates, jacks, gates: desc.rail.gates, overflow };
}

/** Cable colour by what it carries (UX 6.1): pitch amber, gate rose, tone violet, audio teal. */
export function cableColour(from, to, channelMap) {
  for (const id of [from, to]) {
    if (!id) continue;
    if (id.startsWith("gate.") || /\.gate$/.test(id)) return "#F07FA3";
    if (id.startsWith("dac.")) {
      const r = channelMap.find((c) => c.line === id);
      if (r && /^gate/i.test(r.name)) return "#F07FA3";
      return r && /^pitch/i.test(r.name) ? "#F2A83B" : "#9B7FD0";
    }
    if (/^(lfo|vib|soft)\w*\.|^\w+\.(sine|tri|square|sh)$/.test(id)) return "#9B7FD0";
  }
  return "#4FC3B5";
}

function art(p) {
  const cx = p.x + p.w / 2;
  switch (p.art) {
    case "voice":
      return `<path d="M${p.x + 36} ${p.y + 150} l40 -46 v46 l40 -46 v46 l40 -46 v46" fill="none" stroke="#D5D8DC" stroke-width="4" stroke-linejoin="round" opacity=".55"/>` +
        `<text x="${cx}" y="${p.y + 190}" text-anchor="middle" class="silk sm">VCO · ENV · VCA</text>`;
    case "noise": {
      let d = `M${p.x + 16} ${p.y + 130}`;
      const ys = [-14, 10, -22, 18, -6, 20, -18, 8, -10, 16, -20, 6];
      ys.forEach((dy, i) => { d += ` L${p.x + 20 + i * 6.4} ${p.y + 130 + dy}`; });
      return `<path d="${d}" fill="none" stroke="#D5D8DC" stroke-width="3" opacity=".55"/>`;
    }
    case "lfo":
      return `<path d="M${p.x + 30} ${p.y + 130} q22 -40 44 0 t44 0 t44 0 t44 0" fill="none" stroke="#D5D8DC" stroke-width="4" opacity=".55"/>`;
    case "mix":
      return [0, 1, 2, 3].map((i) => `<rect x="${p.x + 38 + i * 64}" y="${p.y + 92}" width="16" height="96" rx="8" fill="#14161a"/><rect x="${p.x + 30 + i * 64}" y="${p.y + 120 + i * 9}" width="32" height="18" rx="4" fill="#D5D8DC" opacity=".8"/>`).join("");
    case "vcf":
      return `<path d="M${p.x + 50} ${p.y + 130} H${p.x + 200} q30 -34 50 6 t70 54" fill="none" stroke="#D5D8DC" stroke-width="4" opacity=".55"/>`;
    case "echo":
      return [0, 1, 2, 3].map((i) => `<rect x="${p.x + 50 + i * 44}" y="${p.y + 100 + i * 10}" width="14" height="${70 - i * 20}" rx="5" fill="#D5D8DC" opacity="${0.7 - i * 0.15}"/>`).join("");
    case "out":
      return `<rect x="${cx - 46}" y="${p.y + 84}" width="54" height="74" rx="8" fill="#3a2e46"/><circle cx="${cx - 19}" cy="${p.y + 108}" r="9" fill="#14101a"/><circle cx="${cx - 19}" cy="${p.y + 136}" r="14" fill="#14101a"/><path d="M${cx + 8} ${p.y + 104} l36 -18 v80 l-36 -18z" fill="#7B5BB0"/>`;
    default:
      return "";
  }
}

const STYLE = `<style>.silk{font-family:Oswald,Arial Narrow,sans-serif;font-weight:700;font-size:24px;letter-spacing:.14em;fill:#D5D8DC}.silk.sm{font-size:22px;letter-spacing:.08em;fill:#B5BAC1;font-weight:600}.silk.jl{font-size:22px;letter-spacing:.01em;fill:#D5D8DC;font-weight:600}.silk.rl{font-size:22px;letter-spacing:.02em;fill:#D5D8DC;font-weight:500}</style>`;

/** The static wall (plates, art, jack rings), drawn under the cables. */
export function wallSvg(lay) {
  let h = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true"><defs>` +
    `<linearGradient id="brush" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#30343A"/><stop offset="1" stop-color="#1d2024"/></linearGradient>` +
    `<radialGradient id="jackring" cx=".4" cy=".35"><stop offset="0" stop-color="#e7eaee"/><stop offset=".7" stop-color="#9da3ab"/><stop offset="1" stop-color="#5d636b"/></radialGradient>` +
    `${STYLE}</defs>`;
  for (const p of lay.plates) {
    h += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="12" fill="url(#brush)" stroke="#0008" stroke-width="2"/>`;
    h += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="10" rx="4" fill="${p.band}"/>`;
    for (const [sx, sy] of [[p.x + 14, p.y + 26], [p.x + p.w - 14, p.y + 26], [p.x + 14, p.y + p.h - 14], [p.x + p.w - 14, p.y + p.h - 14]]) {
      h += `<circle cx="${sx}" cy="${sy}" r="6" fill="#8a9098"/><path d="M${sx - 4} ${sy + 2} l8 -4" stroke="#4a4f56" stroke-width="2"/>`;
    }
    h += art(p);
  }
  for (const j of lay.jacks) {
    h += `<circle cx="${j.x}" cy="${j.y}" r="25" fill="url(#jackring)" stroke="#000a" stroke-width="2"/><circle cx="${j.x}" cy="${j.y}" r="14" fill="#08090b"/>`;
  }
  return h + "</svg>";
}

/**
 * The silkscreen, drawn OVER the cables on a dark backing so every label stays readable
 * wherever a cable runs (DESIGN-SYSTEM B-07). Pointer events pass through.
 */
export function labelsSvg(lay, words) {
  let h = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true" style="pointer-events:none"><defs>${STYLE}</defs>`;
  const back = (x, y, w, hgt) => `<rect x="${x}" y="${y}" width="${w}" height="${hgt}" rx="6" fill="#1d2024" opacity=".82"/>`;
  const approx = (t, px) => Math.ceil(t.length * px);
  for (const p of lay.plates) {
    if (!p.title) continue;
    const w = approx(p.title, 17) + 24;
    const ty = p.titleY ?? 38;
    h += back(p.x + p.w / 2 - w / 2, p.y + ty, w, 34) + `<text x="${p.x + p.w / 2}" y="${p.y + ty + 24}" text-anchor="middle" class="silk">${p.title}</text>`;
  }
  h += `<text x="24" y="52" class="silk">${esc(words.railTitle)}</text><text x="24" y="84" class="silk sm">${esc(words.railSub)}</text>`;
  h += `<text x="21" y="106" class="silk sm">D/A 0-7</text><text x="155" y="106" class="silk sm">D/A 8-15</text>`;
  if (lay.gates) h += `<text x="289" y="106" class="silk sm">GATES</text>`;
  for (const j of lay.jacks) {
    if (j.kind === "source" || j.kind === "gate") {
      const w = approx(j.label, 11.5) + 10;
      h += back(j.x + 27, j.y - 15, w, 30) + `<text x="${j.x + 32}" y="${j.y + 8}" class="silk rl">${esc(j.label)}</text>`;
    } else {
      const w = approx(j.label, 11.5) + 10;
      h += back(j.x - w / 2, j.y + 34, w, 28) + `<text x="${j.x}" y="${j.y + 55}" text-anchor="middle" class="silk jl">${esc(j.label)}</text>`;
    }
  }
  return h + "</svg>";
}
