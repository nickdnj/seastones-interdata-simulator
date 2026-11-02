#!/usr/bin/env node
// S-8a fps harness (SP-S8A). Serves tests/web/ on 127.0.0.1, opens the render-budget page in
// Chromium at 1920x1080 through Playwright, discards a warm-up, records requestAnimationFrame
// timestamps and per-frame draw time, and prints one JSON report.
//
//   node tests/web/s8-render-budget/measure.mjs [--seconds 10] [--warmup 2] [--headed]
//        [--voices 8] [--cables 20] [--min-fps 50] [--executable /usr/bin/chromium]
//
// p50 fps is 1000 / median frame interval. Dropped frames count missed 60 Hz slots:
// for every interval, round(dt / 16.667) - 1. On the box (S-8b) run it --headed with the kiosk
// Chromium (--executable) so the compositor and GPU are the real ones; headless numbers on a
// Mac are a smoke result, not the NFR-9 measurement.
//
// Playwright resolves from tests/web/node_modules (npm ci in tests/web), or from the directory
// in SX_PLAYWRIGHT_DIR (a node_modules/playwright folder) when no local install exists.

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');

function args() {
  const a = { seconds: 10, warmup: 2, headed: false, voices: 8, cables: 20, minFps: null, executable: null };
  const v = process.argv.slice(2);
  for (let i = 0; i < v.length; i++) {
    const k = v[i];
    if (k === '--headed') a.headed = true;
    else if (k === '--seconds') a.seconds = Number(v[++i]);
    else if (k === '--warmup') a.warmup = Number(v[++i]);
    else if (k === '--voices') a.voices = Number(v[++i]);
    else if (k === '--cables') a.cables = Number(v[++i]);
    else if (k === '--min-fps') a.minFps = Number(v[++i]);
    else if (k === '--executable') a.executable = v[++i];
    else { console.error(`unknown argument ${k}`); process.exit(2); }
  }
  return a;
}

async function loadChromium() {
  try {
    return (await import('@playwright/test')).chromium;
  } catch {
    const dir = process.env.SX_PLAYWRIGHT_DIR;
    if (!dir) throw new Error('Playwright not found: run `npm ci` in tests/web, or set SX_PLAYWRIGHT_DIR');
    return (await import(pathToFileURL(join(dir, 'index.mjs')).href)).chromium;
  }
}

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css' };

function serve() {
  const srv = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^\/+/, '');
    const file = resolve(root, path);
    if (!file.startsWith(root) || file.includes('node_modules')) { res.writeHead(403); res.end(); return; }
    try {
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' });
      res.end(body);
    } catch { res.writeHead(404); res.end(); }
  });
  return new Promise((ok) => srv.listen(0, '127.0.0.1', () => ok(srv)));
}

function pct(sorted, q) {
  if (!sorted.length) return null;
  const pos = (q / 100) * (sorted.length - 1);
  const lo = Math.floor(pos), hi = Math.min(lo + 1, sorted.length - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function summarize(frames, work) {
  const dt = [];
  for (let i = 1; i < frames.length; i++) dt.push(frames[i] - frames[i - 1]);
  const slot = 1000 / 60;
  const dropped = dt.reduce((n, d) => n + Math.max(0, Math.round(d / slot) - 1), 0);
  const sdt = [...dt].sort((x, y) => x - y);
  const sw = [...work].sort((x, y) => x - y);
  const span = frames.length > 1 ? frames[frames.length - 1] - frames[0] : 0;
  const r = (x) => (x == null ? null : Math.round(x * 100) / 100);
  return {
    frames: frames.length,
    span_ms: r(span),
    p50_fps: sdt.length ? r(1000 / pct(sdt, 50)) : null,
    mean_fps: span ? r(((frames.length - 1) * 1000) / span) : null,
    dropped_frames: dropped,
    frame_interval_ms: { p50: r(pct(sdt, 50)), p95: r(pct(sdt, 95)), p99: r(pct(sdt, 99)), max: r(sdt.at(-1)) },
    draw_ms: { p50: r(pct(sw, 50)), p95: r(pct(sw, 95)), max: r(sw.at(-1)) },
  };
}

async function main() {
  const a = args();
  const chromium = await loadChromium();
  const srv = await serve();
  const port = srv.address().port;
  const browser = await chromium.launch({ headless: !a.headed, executablePath: a.executable || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(`http://127.0.0.1:${port}/s8-render-budget/index.html?voices=${a.voices}&cables=${a.cables}`);
    await page.waitForFunction(() => window.__s8 && window.__s8.frames.length > 2);
    await page.waitForTimeout(a.warmup * 1000);
    await page.evaluate(() => { window.__s8.frames.length = 0; window.__s8.work.length = 0; window.__s8.ticks = 0; });
    await page.waitForTimeout(a.seconds * 1000);
    const rec = await page.evaluate(() => ({
      frames: [...window.__s8.frames], work: [...window.__s8.work], ticks: window.__s8.ticks,
      synthetic: window.__s8.synthetic, ua: navigator.userAgent,
    }));
    const s = summarize(rec.frames, rec.work);
    const out = {
      harness: 's8-measure', spike: 'S-8a', synthetic_feed: rec.synthetic, viewport: '1920x1080',
      headless: !a.headed, browser: browser.version(), voices: a.voices, cables: a.cables,
      meters: 16, lamps: 24, seconds: a.seconds, warmup_s: a.warmup, feed_ticks: rec.ticks,
      page_errors: errors, ...s,
    };
    if (a.minFps != null) out.verdict = s.p50_fps != null && s.p50_fps >= a.minFps && !errors.length ? 'pass' : 'fail';
    console.log(JSON.stringify(out, null, 2));
    process.exitCode = errors.length || out.verdict === 'fail' ? 1 : 0;
  } finally {
    await browser.close();
    srv.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error(e); process.exit(1); });
}
