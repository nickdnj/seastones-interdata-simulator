// Review captures for Nick and DES-1 (UI-39 groundwork): every screen and its main states at
// 1920 x 1080, against the fake engine running the real program. Writes PNGs to
// docs/qa/results/ui/ (JPEG, quality 82: the grain makes PNGs 2 MB each) only when SX_UI_SHOTS=1, so an ordinary `make web-test` never rewrites
// committed files.
//
//   SX_UI_SHOTS=1 npx playwright test ui/screenshots.spec.mjs
import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FakeEngine } from "../fake-engine/engine.mjs";
import { open, go } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const OUT = path.join(ROOT, "docs/qa/results/ui");

test.skip(!process.env.SX_UI_SHOTS, "set SX_UI_SHOTS=1 to write the review captures");
test.describe.configure({ mode: "serial" });

let rig, page, n = 0;
const shot = async (name) => {
  n += 1;
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(OUT, `${String(n).padStart(2, "0")}-${name}.jpg`), type: "jpeg", quality: 82 });
};

test.beforeAll(async ({ browser }) => {
  mkdirSync(OUT, { recursive: true });
  rig = new FakeEngine();
  await rig.start(0);
  page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, hasTouch: true });
});
test.afterAll(async () => { await page.close(); await rig.stop(); });

test("captures", async () => {
  test.setTimeout(180000);
  // cold start: rigd up, the synthesizer and the output still coming up
  rig.setStages({ computer: true, program: true, synth: false, output: false });
  await open(page, rig);
  await shot("attract-starting");
  rig.setStages({ synth: true, output: true });
  await expect(page.locator("#attract-pill")).toContainText(/play the keys/i);
  await page.waitForTimeout(1200);
  await shot("attract");

  const t = await touchSession(page);
  await go(page, "play");
  await t.down([page.locator('#layer-play [data-key="12"]')]);
  await shot("play-key-held");
  await t.up();
  await page.locator('#layer-play .det[data-speed="div300"]').tap();
  await page.keyboard.down("d");
  await page.waitForTimeout(300);
  await shot("play-slowed-full-speed-showing");
  await page.keyboard.up("d");
  await page.locator("#fullspeed").tap();

  await go(page, "computer");
  await page.waitForTimeout(600);
  await shot("computer-run");
  await page.locator('#layer-computer .det[data-speed="crawl"]').tap();
  await page.waitForTimeout(1500);
  await shot("computer-crawl");
  await page.locator('#layer-computer .det[data-speed="step"]').tap();
  for (let i = 0; i < 9; i++) await page.locator("#step-computer").tap();
  await shot("computer-step");

  await go(page, "code");
  for (let i = 0; i < 4; i++) await page.locator("#step-code").tap();
  await shot("code-step");
  await page.evaluate(() => window.__seastones.setStaff(true));
  await shot("code-step-staff-disassembly");
  await page.evaluate(() => window.__seastones.setStaff(false));
  await page.locator('#layer-code .det[data-speed="run"]').tap();
  await page.waitForTimeout(800);
  await shot("code-run");

  await go(page, "patch");
  await shot("patch-default");
  await page.locator('#layer-patch .chip[data-preset="sweep"]').tap();
  await shot("patch-sweep-preset");
  await page.locator("#putback-patch").tap();
  // every cable out (the patch spec does it through the UI; here the engine does it at once)
  for (const c of [...rig.cables]) rig.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.disconnect", id: 1, from: c.from, to: c.to }));
  await page.waitForFunction(() => window.__seastones.live.patch.cables.length === 0);
  await page.waitForTimeout(200);
  await page.keyboard.down("a");
  await expect(page.locator("#silence-hint")).toBeVisible();
  await shot("patch-nothing-reaches-the-speaker");
  await page.keyboard.up("a");
  await page.locator("#putback-patch").tap();
  await page.locator("#wall .jackhit[data-jack='lfo.tri']").tap();
  await shot("patch-tap-to-join-selected");
  await page.locator("#wall .jackhit[data-jack='lfo.tri']").tap();

  await go(page, "story");
  await page.locator("#layer-story .dot").nth(0).tap();
  await shot("story-1-disclosure");
  for (const i of [1, 2, 3, 4, 5]) {
    await page.locator("#layer-story .dot").nth(i).tap();
    await shot(`story-${i + 1}`);
  }
  await page.evaluate(() => window.__seastones.setReview(true));
  await page.locator("#layer-story .dot").nth(6).tap();
  await shot("story-review-draft-not-shippable");
  await page.evaluate(() => window.__seastones.setReview(false));

  await go(page, "play");
  await page.locator("#about").tap();
  await shot("about-this-recreation");
  await page.locator("#about-close").tap();

  // the staff screen: hold the logo 3 s, then the PIN on the keypad
  const mark = await page.locator("#header .mark").boundingBox();
  const st = await touchSession(page);
  await st.down([{ x: mark.x + mark.width / 2, y: mark.y + mark.height / 2 }]);
  await page.waitForTimeout(3300);
  await st.up();
  for (const d of "43") await page.locator(`#staff-key-${d}`).tap();
  await shot("staff-pin");
  for (const d of "21") await page.locator(`#staff-key-${d}`).tap();
  await page.locator("#staff-key-ok").tap();
  await expect(page.locator("#staff-screen")).toBeVisible();
  await shot("staff-screen");
  await page.locator("#staff-review").tap();
  await page.locator("#staff-close").tap();
  await go(page, "story");
  await page.locator("#layer-story .dot").nth(6).tap();
  await shot("review-mode-banner");
  rig.settings.review_mode = false;
  rig.broadcast(rig.settingsMsg());

  await go(page, "play");
  rig.unplugKeyboard();
  await shot("play-keyboard-lost-notice");
  rig.replugKeyboard();
  rig.fault("program_stalled", "unknown opcode at 00F0");
  await shot("fault-computer-restarting");
  rig.clearFault("program_stalled");
  await go(page, "play");
  rig.fault("audio_device_missing");
  rig.setStages({ output: false });
  await shot("fault-sound-reconnecting");
  rig.setStages({ output: true });
  rig.clearFault("audio_device_missing");
  await go(page, "computer");
  rig.kill();
  await expect(page.locator("#fault")).toBeVisible();
  await shot("fault-rigd-gone-no-stale-lamps");
  rig.revive();
  await expect(page.locator("#fault")).toBeHidden({ timeout: 10000 });

  // a rigd from another protocol version, and the eight-voice channel map
  const v2 = new FakeEngine({ protocolVersion: 2 });
  await v2.start(0);
  await page.goto(`${process.env.SX_WEB_URL}/?rig=${encodeURIComponent(v2.url)}&hooks=1`);
  await expect(page.locator("#fault-staff")).toContainText("protocol v2");
  await shot("fault-protocol-mismatch");
  await v2.stop();
  const r8 = new FakeEngine({ voices: 8 });
  await r8.start(0);
  await open(page, r8);
  await go(page, "patch");
  await shot("patch-eight-voice-map");
  await r8.stop();
});

test("idle warning capture", async ({ browser }) => {
  const p = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.clock.install();
  await open(p, rig);
  await go(p, "play");
  await p.clock.fastForward(80000);
  await expect(p.locator("#veil")).toBeVisible();
  await p.waitForTimeout(400);
  await p.screenshot({ path: path.join(OUT, `${String(++n).padStart(2, "0")}-idle-still-playing.jpg`), type: "jpeg", quality: 82 });
  await p.close();
});
