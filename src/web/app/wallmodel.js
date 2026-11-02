// wallmodel.js: the patch wall as it follows from an engine patch (PM-10, PM-12, PM-13;
// ARCHITECTURE 11.3, ADR-007). Pure: no DOM, so the fake engine (Node) and the page share it.
//
// The engine's patch format (seastones.patch/1, src/toolchain/sxpatch/patch.py) is the one
// source of truth. A patch has a voice template (modules made once per voice), a `voices`
// block (each voice's pitch, gate and output, with {i} arithmetic over the voice number),
// global modules, and global cables, which may name `<template id>*.<port>` for that port on
// every voice. The wall shows that graph as a visitor can patch it:
//
//   voice card n (1-based)   jacks v<n>.pitch, v<n>.gate, v<n>.out, and v<n>.<tid>-<port>
//                            for every template port a wildcard cable reaches
//   a global module          jacks <id>.<port>, one per port of its type
//   the D/A rail             dac.0 to dac.15; gate.0 to gate.7 only on a gate-latch map
//
// Engine port for each wall jack (what rigd's patch.connect translates to):
//   v<n>.pitch -> the template's $pitch for voice n-1    v<n>.gate -> $gate
//   v<n>.out   -> $out                                    v<n>.<tid>-<port> -> <tid><n-1>.<port>
//   <id>.<port>, dac.<k>, gate.<k> -> themselves

/** Whole-number arithmetic over i with + - * / % and brackets (/ rounds down), as sxpatch. */
export function evalIndex(expr, i) {
  const toks = String(expr).replace(/\s+/g, "").match(/i|\d+|[-+*/%()]/g) || [];
  if (toks.join("") !== String(expr).replace(/\s+/g, "")) throw new Error(`bad expression {${expr}}`);
  let k = 0;
  const floorDiv = (a, b) => Math.floor(a / b);
  const mod = (a, b) => ((a % b) + b) % b;
  const atom = () => {
    const t = toks[k++];
    if (t === "(") { const v = sum(); if (toks[k++] !== ")") throw new Error(`bad expression {${expr}}`); return v; }
    if (t === "-") return -atom();
    if (t === "i") return i;
    if (/^\d+$/.test(t || "")) return Number(t);
    throw new Error(`bad expression {${expr}}`);
  };
  const prod = () => {
    let v = atom();
    while (["*", "/", "%"].includes(toks[k])) {
      const op = toks[k++], r = atom();
      v = op === "*" ? v * r : op === "/" ? floorDiv(v, r) : mod(v, r);
    }
    return v;
  };
  const sum = () => {
    let v = prod();
    while (["+", "-"].includes(toks[k])) { const op = toks[k++], r = prod(); v = op === "+" ? v + r : v - r; }
    return v;
  };
  const v = sum();
  if (k !== toks.length) throw new Error(`bad expression {${expr}}`);
  return v;
}

/** Fill every {...} in a jack name for voice i. */
export const fill = (s, i) => String(s).replace(/\{([^{}]*)\}/g, (_, e) => String(evalIndex(e, i)));

const WILD = /^([a-z][a-z0-9_]*)\*\.([a-z0-9_]+)$/;
const SHORT = { square: "SQR", sh: "S&H", cutoff: "CUT", resonance: "RES" };
const portLabel = (p) => (/^in(\d)$/.test(p) ? p.slice(2) : SHORT[p] || p.toUpperCase());
const NAMED = { send: "ECHO SEND", busl: "LEFT", busr: "RIGHT", out: "OUTPUT", vib: "VIBRATO", soft: "SLEW" };
const TYPE_TITLE = { lfo: "LFO", mixer: "MIXER", echo: "ECHO", slew: "SLEW", noise: "NOISE", vcf: "FILTER", vco: "VCO", env: "ENVELOPE", vca: "VCA", out: "OUTPUT" };

/**
 * The wall's layout description from an engine patch and the module registry
 * ({type: {inputs: [{name}], outputs: [{name}]}}): what the engine's `patch` message carries
 * as `layout`, so the page draws the wall without the registry.
 */
export function layoutOf(patch, registry) {
  const voices = patch.voices || { count: 0 };
  const count = Math.max(0, Math.min(8, voices.count || 0));
  const ports = [];
  const seenPort = new Set();
  for (const [a, b] of patch.cables || []) {
    for (const end of [a, b]) {
      const m = WILD.exec(end);
      if (m && !seenPort.has(`${m[1]}-${m[2]}`)) { seenPort.add(`${m[1]}-${m[2]}`); ports.push({ id: `${m[1]}-${m[2]}`, label: portLabel(m[2]), out: end === a }); }
    }
  }
  // two template ports with the same name (osc-mod, sub-mod) keep their module in the label
  for (const p of ports) if (ports.filter((q) => q.label === p.label).length > 1) p.label = `${p.id.split("-")[0].toUpperCase()} ${p.label}`;
  const mods = [...(patch.modules || [])];
  if (!mods.some((m) => m.id === "out")) mods.push({ id: "out", type: "out" });
  const byType = {};
  for (const m of mods) byType[m.type] = (byType[m.type] || 0) + 1;
  const nth = {};
  const modules = mods.map((m) => {
    const reg = registry[m.type] || { inputs: [], outputs: [] };
    nth[m.type] = (nth[m.type] || 0) + 1;
    const base = NAMED[m.id] || TYPE_TITLE[m.type] || m.type.toUpperCase();
    const title = !NAMED[m.id] && byType[m.type] > 1 ? `${base} ${nth[m.type]}` : base;
    return { id: m.id, type: m.type, title, ins: reg.inputs.map((p) => p.name), outs: reg.outputs.map((p) => p.name) };
  });
  const gates = typeof voices.gate === "string" && voices.gate.startsWith("gate.");
  return { map: patch.map || "", rail: { gates }, voices: { count, ports }, modules };
}

/** Every jack of a layout: {id, label, kind: source|gate|in|out, plate}. */
export function jacksOf(layout) {
  const out = [];
  for (let k = 0; k < 16; k++) out.push({ id: `dac.${k}`, kind: "source", plate: "rail" });
  if (layout.rail.gates) for (let k = 0; k < 8; k++) out.push({ id: `gate.${k}`, kind: "gate", plate: "rail" });
  for (let n = 1; n <= layout.voices.count; n++) {
    out.push({ id: `v${n}.pitch`, label: "PITCH", kind: "in", plate: `v${n}` });
    out.push({ id: `v${n}.gate`, label: "GATE", kind: "in", plate: `v${n}` });
    for (const p of layout.voices.ports) out.push({ id: `v${n}.${p.id}`, label: p.label, kind: p.out ? "out" : "in", plate: `v${n}` });
    out.push({ id: `v${n}.out`, label: "OUT", kind: "out", plate: `v${n}` });
  }
  for (const m of layout.modules) {
    for (const p of m.ins) out.push({ id: `${m.id}.${p}`, label: portLabel(p), kind: "in", plate: m.id });
    for (const p of m.outs) out.push({ id: `${m.id}.${p}`, label: portLabel(p), kind: "out", plate: m.id });
  }
  return out;
}

/** The wall's cables for an engine patch, in wall jack ids. */
export function cablesOf(patch, layout) {
  const out = [];
  const v = patch.voices || {};
  for (let i = 0; i < layout.voices.count; i++) {
    const n = i + 1;
    if (v.pitch) out.push({ from: fill(v.pitch, i), to: `v${n}.pitch` });
    if (v.gate) out.push({ from: fill(v.gate, i), to: `v${n}.gate` });
    if (v.out) out.push({ from: `v${n}.out`, to: fill(v.out, i) });
  }
  const end = (e, n) => { const m = WILD.exec(e); return m ? `v${n}.${m[1]}-${m[2]}` : e; };
  for (const [a, b] of patch.cables || []) {
    if (WILD.test(a) || WILD.test(b)) for (let n = 1; n <= layout.voices.count; n++) out.push({ from: end(a, n), to: end(b, n) });
    else out.push({ from: a, to: b });
  }
  return out;
}

/**
 * Does any voice reach the speaker (PATCH-4)? A voice sounds only when a computer line
 * reaches its gate; its sound reaches the speaker when a path of cables and modules leads
 * from its output to the output module's inputs.
 */
export function reachesOut(cables, layout) {
  const adj = new Map();
  const link = (a, b) => {
    if (!adj.has(a)) adj.set(a, new Set());
    if (!adj.has(b)) adj.set(b, new Set());
    adj.get(a).add(b);
    adj.get(b).add(a);
  };
  for (const c of cables) link(c.from, c.to);
  // inside a module every input reaches every output; the output module's inputs are the end
  for (const m of layout.modules) {
    if (m.type === "out") continue;
    for (const i of m.ins) for (const o of m.outs) link(`${m.id}.${i}`, `${m.id}.${o}`);
  }
  const sinks = new Set((layout.modules.find((m) => m.type === "out") || { ins: [] }).ins.map((p) => `out.${p}`));
  const fed = (jack) => {
    const seen = new Set([jack]);
    const q = [jack];
    while (q.length) {
      const n = q.shift();
      if (/^(dac|gate)\.\d+$/.test(n)) return true;
      for (const c of cables) {
        const o = c.from === n ? c.to : c.to === n ? c.from : null;
        if (o && !seen.has(o)) { seen.add(o); q.push(o); }
      }
    }
    return false;
  };
  for (let n = 1; n <= layout.voices.count; n++) {
    if (!fed(`v${n}.gate`)) continue;
    const seen = new Set([`v${n}.out`]);
    const q = [`v${n}.out`];
    while (q.length) {
      const j = q.shift();
      if (sinks.has(j)) return true;
      for (const k of adj.get(j) || []) if (!seen.has(k)) { seen.add(k); q.push(k); }
    }
  }
  return false;
}
