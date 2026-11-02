// S-8a render-budget page (SP-S8A). Canvas 2D for animated parts, SVG for static art
// (ARCHITECTURE 4.7). The workload is the S-8 worst case: 20 cables with droop, 16 meters,
// 24 panel lamps, 16 gate lamps and a scope, at 1920x1080, fed at 60 Hz by a SYNTHETIC
// generator. Frame timestamps and per-frame draw time go to window.__s8 for measure.mjs.

import { createSyntheticFeed } from '../fixtures/synthetic-feed.js';

const params = new URLSearchParams(location.search);
const VOICES = Number(params.get('voices') || 8);
const CABLES = Number(params.get('cables') || 20);
const feed = createSyntheticFeed({ voices: VOICES, seed: 1974 });

const W = 1920, H = 1080;
const svg = document.getElementById('art');
const cv = document.getElementById('live');
const ctx = cv.getContext('2d', { alpha: true });

// ------------------------------------------------------------------ layout
const lamps = Array.from({ length: 24 }, (_, i) => ({ x: 120 + i * 62, y: 110 }));
const meters = Array.from({ length: 16 }, (_, i) => ({ x: 120 + i * 58, y: 260, w: 34, h: 300 }));
const gates = Array.from({ length: 16 }, (_, i) => ({ x: 137 + i * 58, y: 590 }));
const scope = { x: 1100, y: 240, w: 720, h: 340 };
const jacksOut = Array.from({ length: 16 }, (_, i) => ({ x: 140 + i * 104, y: 700 }));
const jacksIn = Array.from({ length: 16 }, (_, i) => ({ x: 140 + i * 104, y: 960 }));
const cableColours = ['#d94f30', '#e8b33a', '#3c8dbc', '#5fae5f', '#c9c3b6', '#9a5fb3', '#e07fa0', '#2b2b2b'];
const cables = Array.from({ length: CABLES }, (_, i) => ({
  a: jacksOut[i % 16],
  b: jacksIn[(i * 7 + 3) % 16],
  colour: cableColours[i % cableColours.length],
  sway: (i * 0.37) % 1,
}));

// ------------------------------------------------------------------ static art (SVG, once)
function el(name, attrs, parent = svg) {
  const e = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  parent.appendChild(e);
  return e;
}
el('rect', { x: 0, y: 0, width: W, height: H, fill: '#1d1914' });
el('rect', { x: 60, y: 50, width: 1800, height: 140, rx: 10, fill: '#3a2f25', stroke: '#6b5844', 'stroke-width': 3 });
el('rect', { x: 60, y: 220, width: 1000, height: 420, rx: 10, fill: '#2a241d', stroke: '#6b5844', 'stroke-width': 3 });
el('rect', { x: scope.x - 10, y: scope.y - 20, width: scope.w + 20, height: scope.h + 40, rx: 10, fill: '#0c140f',
  stroke: '#6b5844', 'stroke-width': 3 });
el('rect', { x: 60, y: 660, width: 1800, height: 380, rx: 10, fill: '#262019', stroke: '#6b5844', 'stroke-width': 3 });
for (const l of lamps) el('circle', { cx: l.x, cy: l.y, r: 20, fill: '#111', stroke: '#8c7a62', 'stroke-width': 3 });
for (const m of meters) el('rect', { x: m.x - 3, y: m.y - 3, width: m.w + 6, height: m.h + 6, fill: '#0d0b09',
  stroke: '#8c7a62', 'stroke-width': 2 });
for (let g = 0; g <= 10; g++) {
  el('line', { x1: scope.x, x2: scope.x + scope.w, y1: scope.y + (g * scope.h) / 10, y2: scope.y + (g * scope.h) / 10,
    stroke: '#1f3a28', 'stroke-width': 1 });
}
for (const j of [...jacksOut, ...jacksIn]) {
  el('circle', { cx: j.x, cy: j.y, r: 18, fill: '#151210', stroke: '#b8a688', 'stroke-width': 4 });
  el('circle', { cx: j.x, cy: j.y, r: 7, fill: '#000' });
}
jacksOut.forEach((j, i) => {
  const t = el('text', { x: j.x, y: j.y - 30, fill: '#d8ccb4', 'font-size': 22, 'text-anchor': 'middle',
    'font-family': 'system-ui' });
  t.textContent = `D/A ${i}`;
});

// ------------------------------------------------------------------ live layer (Canvas 2D)
const peak = new Float32Array(16);

function drawLamps(s) {
  for (let i = 0; i < 24; i++) {
    const on = s.lamps[i];
    ctx.beginPath();
    ctx.arc(lamps[i].x, lamps[i].y, 15, 0, Math.PI * 2);
    ctx.fillStyle = on ? '#ff5a1f' : '#2a1208';
    ctx.shadowColor = on ? '#ff5a1f' : 'transparent';
    ctx.shadowBlur = on ? 18 : 0;
    ctx.fill();
  }
  ctx.shadowBlur = 0;
}

function drawMeters(s) {
  for (let c = 0; c < 16; c++) {
    const m = meters[c];
    const v = s.dac[c] / 65535;
    peak[c] = Math.max(v, peak[c] * 0.985);
    const h = v * m.h;
    const grad = ctx.createLinearGradient(0, m.y + m.h, 0, m.y);
    grad.addColorStop(0, '#2f8f46');
    grad.addColorStop(0.75, '#e8b33a');
    grad.addColorStop(1, '#d94f30');
    ctx.fillStyle = grad;
    ctx.fillRect(m.x, m.y + m.h - h, m.w, h);
    ctx.fillStyle = '#f2ead8';
    ctx.fillRect(m.x, m.y + m.h - peak[c] * m.h - 2, m.w, 3);
    ctx.beginPath();
    ctx.arc(gates[c].x, gates[c].y, 10, 0, Math.PI * 2);
    ctx.fillStyle = s.gates[c] ? '#7cff6b' : '#123010';
    ctx.fill();
  }
}

function drawScope(s) {
  ctx.save();
  ctx.beginPath();
  ctx.rect(scope.x, scope.y, scope.w, scope.h);
  ctx.clip();
  ctx.strokeStyle = '#7cff6b';
  ctx.lineWidth = 2.5;
  ctx.shadowColor = '#7cff6b';
  ctx.shadowBlur = 8;
  ctx.beginPath();
  const n = s.scope.length;
  for (let i = 0; i < n; i++) {
    const x = scope.x + (i / (n - 1)) * scope.w;
    const y = scope.y + scope.h / 2 - s.scope[i] * scope.h * 0.45;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawCables(tMs) {
  ctx.lineCap = 'round';
  for (const c of cables) {
    const dx = c.b.x - c.a.x, dy = c.b.y - c.a.y;
    const len = Math.hypot(dx, dy);
    const droop = 60 + len * 0.18 + Math.sin(tMs / 900 + c.sway * 6.28) * 6;
    const mx = (c.a.x + c.b.x) / 2, my = Math.max(c.a.y, c.b.y) + droop;
    const pass = (colour, width, off) => {
      ctx.strokeStyle = colour;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(c.a.x + off, c.a.y + off);
      ctx.quadraticCurveTo(mx + off, my + off, c.b.x + off, c.b.y + off);
      ctx.stroke();
    };
    pass('rgba(0,0,0,0.45)', 14, 5); // shadow
    pass(c.colour, 11, 0);            // body
    pass('rgba(255,255,255,0.25)', 3, -2); // highlight
    for (const p of [c.a, c.b]) {     // plugs
      ctx.fillStyle = '#c9c3b6';
      ctx.beginPath();
      ctx.arc(p.x, p.y, 13, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

// ------------------------------------------------------------------ loop + instrumentation
const rec = { frames: [], work: [], ticks: 0, synthetic: true, voices: VOICES, cables: CABLES };
window.__s8 = rec;
setInterval(() => { feed.step(); rec.ticks++; }, 1000 / feed.rateHz);

function frame(ts) {
  const t0 = performance.now();
  ctx.clearRect(0, 0, W, H);
  const s = feed.state;
  drawLamps(s);
  drawMeters(s);
  drawScope(s);
  drawCables(ts);
  rec.frames.push(ts);
  rec.work.push(performance.now() - t0);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
