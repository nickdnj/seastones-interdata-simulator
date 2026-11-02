// Long content (UI-38, B-07, CONT-1): every string at the longest its content rule allows,
// plus a long unbreakable word, and no text may be clipped or run outside its card on any
// layer, the About page, the idle veil or a fault card. A content editor can change words
// without a developer (CT-01); this is what lets them reach the limits safely.
import { test, expect } from "@playwright/test";
import { cpSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FakeEngine } from "../fake-engine/engine.mjs";
import { startServe } from "./global-setup.mjs";
import { settled } from "./fixtures.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const LONG_WORD = "Interdata-seven-sixteen-minicomputer";
// The longest each short fixed caption may be. The layout guarantees these; test_web_static
// checks the shipped content against the same numbers (CAPTION_LIMITS there).
// Station 5 also carries the audio caption under its scope, and station 3 four voice rows,
// so their own lines are shorter.
export const LIMITS = { stationMeta: 56, station3Meta: 42, station5Meta: 28, speedText: 80, estimate: 70 }; // characters
const PHRASE = "the computer reads every key and sends the note it finds to the synthesizer again and again ";
/** Ordinary prose of at most `n` characters, cut at a word. */
const chars = (n) => { let t = PHRASE.repeat(Math.ceil(n / PHRASE.length) + 1).slice(0, n + 1); t = t.slice(0, t.lastIndexOf(" ")); return t.charAt(0).toUpperCase() + t.slice(1, -1) + "."; };
// Prose gets the long word; the short fixed captions get ordinary words.
const words = (n, seed = "rig", long = false) =>
  Array.from({ length: n }, (_, i) => (long && i === 3 ? LONG_WORD : `${seed}${i % 7 === 0 ? "s" : ""}`)).join(" ") + ".";

/** Set field `field` of card `key` in a captions-style file. */
function setCard(file, key, field, value) {
  const text = readFileSync(file, "utf8");
  const re = new RegExp(`(## ${key}\\n(?:[a-z]+: .*\\n)*?)${field}: .*\\n`);
  if (!re.test(text)) throw new Error(`${file}: no ${field} in card ${key}`);
  writeFileSync(file, text.replace(re, `$1${field}: ${value}\n`));
}
/** Replace the body (everything after the header block) of a content file. */
function setBody(file, body, header = {}) {
  let [head] = readFileSync(file, "utf8").split(/\n\n/);
  for (const [k, v] of Object.entries(header)) head = head.replace(new RegExp(`^${k}: .*$`, "m"), `${k}: ${v}`);
  writeFileSync(file, `${head}\n\n${body}\n`);
}

function longContent() {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sx-content-long-"));
  cpSync(path.join(ROOT, "content"), dir, { recursive: true });
  const c = (p) => path.join(dir, p);
  // Story: 70 words, the STORY-1 limit, with a long title.
  setBody(c("screens/01-a-computer-on-stage.md"), words(70, "story", true), { title: "A computer on stage, and a synthesizer too" });
  // Code-view notes: 40 words, the CODE-2 limit, on every block.
  for (const f of readdirSync(c("code")).filter((x) => x.endsWith(".md"))) {
    setBody(c(`code/${f}`), words(40, "note", true), { title: "What this part of the program is for" });
  }
  // Lamp captions: 45 words (PANEL-3), and a 20-word readout line, for every speed.
  for (const k of ["run", "div30", "div300", "div3000", "crawl", "step"]) {
    setCard(c("captions/speed.md"), k, "text", chars(LIMITS.speedText));
  }
  setCard(c("captions/speed.md"), "estimate", "text", chars(LIMITS.estimate));
  // Play stations: a long second line each.
  for (let n = 1; n <= 5; n++) setCard(c("captions/play.md"), `station-${n}`, "meta", chars(n === 5 ? LIMITS.station5Meta : n === 3 ? LIMITS.station3Meta : LIMITS.stationMeta));
  // Presets: long titles on the chips.
  for (const p of ["stadium-drone", "two-voice-duet", "bell", "sweep"]) setBody(c(`presets/${p}.md`), words(12, "preset"), { title: "Slow and wide drone" });
  // Fault card and idle veil: long visitor sentences.
  setCard(c("captions/faults.md"), "computer", "meta", words(30, "fault", true));
  setCard(c("captions/idle.md"), "line-2", "text", words(24, "idle", true));
  // About: long credits.
  setCard(c("captions/about.md"), "credits", "text", words(60, "credit", true));
  return dir;
}

async function overflow(page) {
  return page.evaluate(() => {
    const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest("[hidden]"); };
    const sel = ".layer.on .card, .layer.on .btn, .layer.on .chip, .layer.on .det, .layer.on .note, .layer.on .say, .layer.on .readout, " +
      ".layer.on .estimate, .layer.on .cap, .layer.on .text, .tab, #footer, #header, .fcard, .veil p, .about-card, .about-sec p, .patch-help";
    const over = [...document.querySelectorAll(sel)].filter(vis).filter((e) => !e.matches(".listing"))
      .filter((e) => e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)
      .map((e) => `${e.className}#${e.id} ${e.scrollWidth}x${e.scrollHeight} > ${e.clientWidth}x${e.clientHeight}`);
    const outside = [...document.querySelectorAll(".layer.on *, .about-card *, .fcard *")]
      .filter(vis)
      .filter((e) => !(e.closest("svg") && e.tagName !== "svg"))
      .filter((e) => !e.closest(".listing .scroll, .listing .heat"))
      .filter((e) => { const r = e.getBoundingClientRect(); return r.right > 1921 || r.bottom > 1081 || r.left < -1; })
      .map((e) => e.className || e.tagName);
    return { over, outside };
  });
}

test("content at its length limits, and a long word, is never clipped or pushed out of its card (UI-38, B-07)", async ({ page }) => {
  test.setTimeout(120000);
  const serve = await startServe({ content: longContent() });
  const rig = new FakeEngine();
  await rig.start(0);
  try {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(`${serve.url}/?rig=${encodeURIComponent(rig.url)}&hooks=1`);
    await page.waitForFunction(() => window.__seastones && window.__seastones.live.connected && window.__seastones.live.state);
    const bad = [];
    const check = async (where) => {
      await page.waitForTimeout(400);
      const r = await overflow(page);
      for (const x of [...r.over, ...r.outside.map((o) => `outside: ${o}`)]) bad.push(`${where}: ${x}`);
    };
    for (const l of ["play", "computer", "code", "patch", "story"]) {
      await page.evaluate((x) => window.__seastones.go(x), l);
      await settled(page, l);
      await check(`layer ${l}`);
    }
    // every speed's caption and readout
    await page.evaluate(() => window.__seastones.go("play"));
    await settled(page, "play");
    for (const s of ["div30", "div300", "div3000", "crawl", "step"]) {
      await page.locator(`#layer-play .det[data-speed="${s}"]`).tap();
      await check(`play at ${s}`);
    }
    await page.evaluate(() => window.__seastones.go("computer"));
    await settled(page, "computer");
    await check("computer at step");
    await page.locator("#about").tap();
    await check("about");
    await page.locator("#about-close").tap();
    rig.fault("program_stalled");
    await expect(page.locator("#fault")).toBeVisible();
    await check("fault card");
    rig.clearFault("program_stalled");
    expect(bad).toEqual([]);
  } finally {
    await rig.stop();
    serve.proc.kill("SIGTERM");
  }
});
