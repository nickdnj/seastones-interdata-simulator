#!/usr/bin/env node
// drive.mjs: play the demo on the real page against a real rigd, recording video.
//   node tools/demo/drive.mjs <workdir> <page url> <rigd ws url>
// Reads <workdir>/durations.json (narrate.mjs); writes <workdir>/video.webm and
// <workdir>/timeline.json (each segment's start and the first key press, in seconds from
// the moment recording began).
import { readFileSync, writeFileSync, renameSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SEGMENTS } from "./segments.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const { chromium } = await import(path.join(ROOT, "tests/web/node_modules/@playwright/test/index.mjs"));

const [work, pageUrl, rigUrl] = process.argv.slice(2);
if (!rigUrl) { console.error("usage: drive.mjs <workdir> <page url> <rigd ws url>"); process.exit(2); }
const durations = JSON.parse(readFileSync(path.join(work, "durations.json"), "utf8"));
const W = 1280, H = 720;
const LEAD_IN = 1.5; // seconds of picture before the first narration
const PAD = 0.5; // between segments

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: work, size: { width: W, height: H } } });
const t0 = performance.now(); // recording starts with the context
const now = () => (performance.now() - t0) / 1000;
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(`${pageUrl}/?rig=${encodeURIComponent(rigUrl)}&hooks=1&dev=1`);
await page.waitForFunction(() => window.__seastones && window.__seastones.live.connected && window.__seastones.live.state && window.__seastones.live.patch, null, { timeout: 30000 });
await page.waitForFunction(() => !document.fonts || document.fonts.status === "loaded");

const timeline = { segments: [], marks: {}, keys: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));
while (now() < LEAD_IN) await sleep(20);

let segStart = 0;
const ctx = {
  wait: (ms) => sleep(ms),
  left: (ms) => ms - (performance.now() - segStart),
  waitUntil: async (ms) => { await sleep(ms - (performance.now() - segStart)); },
  down: async (k) => { timeline.keys.push([now(), "down", k]); await page.keyboard.down(k); },
  up: async (k) => { timeline.keys.push([now(), "up", k]); await page.keyboard.up(k); },
  go: async (l) => {
    await page.evaluate((x) => window.__seastones.go(x), l);
    await page.waitForFunction((x) => window.__seastones.settled ? window.__seastones.settled(x) : true, l, { timeout: 10000 }).catch(() => {});
  },
  chip: async (slug, scope = ".layer.on") => { await page.locator(`${scope} .chip[data-preset="${slug}"]`).first().click(); },
  tap: async (sel) => { await page.locator(sel).first().click(); },
  speed: async (id) => { await page.locator(`.layer.on .det[data-speed="${id}"]`).first().click(); },
  review: async (on) => { await page.evaluate((v) => window.__seastones.setReview(v), on); },
  pull: async (jack) => {
    await page.locator(`#wall .jackhit[data-jack="${jack}"]`).click();
    await page.locator("#remove-bubble").click({ timeout: 3000 }).catch(() => {});
    await sleep(300);
  },
  mark: (name) => { timeline.marks[name] = now(); },
};

for (const s of SEGMENTS) {
  const d = durations[s.id];
  const ms = (d.seconds + d.gap) * 1000;
  segStart = performance.now();
  const start = now();
  timeline.segments.push({ id: s.id, start, narration: d.file, seconds: d.seconds, slot: d.seconds + d.gap });
  try {
    await s.act(ctx, ms);
  } catch (e) {
    errors.push(`${s.id}: ${e.message}`);
  }
  const over = (performance.now() - segStart) - ms;
  if (over > 300) console.log(`warning: ${s.id} ran ${Math.round(over)} ms over its slot`);
  await sleep(ms + PAD * 1000 - (performance.now() - segStart));
  console.log(`${s.id.padEnd(10)} at ${start.toFixed(2)} s`);
}
for (const k of ["z", "x", "c", "b", "n", "a", "s", "d", "g", "h", "k"]) await page.keyboard.up(k);
await sleep(1500);
timeline.end = now();
timeline.errors = errors;
const video = page.video();
await context.close();
await browser.close();
renameSync(await video.path(), path.join(work, "video.webm"));
writeFileSync(path.join(work, "timeline.json"), JSON.stringify(timeline, null, 2));
console.log(`done: ${timeline.end.toFixed(1)} s, ${errors.length} page error(s)`);
for (const e of errors) console.log(`  ${e}`);
