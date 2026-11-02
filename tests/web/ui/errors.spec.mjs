// KP-05: fault and starting states. UI-33 (keyboard lost), UI-34 (each fault, no stale
// values, recovery), KIOSK-4 (no sound, no fake lamp).
import { test, expect, go, open, brightness } from "./fixtures.mjs";
import { FakeEngine } from "../fake-engine/engine.mjs";

const COMPUTER = ["program_stalled", "dsp_fault", "image_missing", "image_hash_mismatch", "config_invalid", "engine_load_failed"];
const SOUND = ["audio_device_missing", "audio_stalled"];
const STAFF = {
  program_stalled: "program stalled", dsp_fault: "synthesizer fault", image_missing: "program image missing",
  image_hash_mismatch: "does not match its hash", config_invalid: "configuration file invalid",
  engine_load_failed: "engine library would not load", audio_device_missing: "audio device lost", audio_stalled: "audio thread stalled",
};

test("each fault code shows its visitor line and its staff line, and clears itself (UI-34, ARCHITECTURE 8.2)", async ({ app, rig }) => {
  await go(app, "play");
  for (const code of [...COMPUTER, ...SOUND]) {
    rig.fault(code);
    const card = app.locator("#fault");
    await expect(card).toBeVisible();
    await expect(app.locator("#fault-headline")).toHaveText(SOUND.includes(code) ? "The sound is reconnecting." : "The computer is restarting.");
    await expect(app.locator("#fault-staff")).toContainText(STAFF[code]);
    await expect(app.locator("#fault-staff")).toContainText("STAFF");
    await expect(app.locator('.tab[data-layer="code"]')).toHaveCSS("opacity", "0.45");
    await expect(app.locator("#home")).toBeEnabled();
    rig.clearFault(code);
    await expect(card).toBeHidden();
    // recovery starts the station over at attract (UX 5.8)
    await expect(app.locator("#layer-attract")).toBeVisible();
    await go(app, "play");
  }
});

test("the keyboard-lost notice is one calm line, not a fault card, and clears on replug (UI-33, INPUT-3)", async ({ app, rig }) => {
  await go(app, "play");
  rig.unplugKeyboard();
  await expect(app.locator("#kb-notice-play")).toBeVisible();
  await expect(app.locator("#kb-notice-play")).toHaveText("The keyboard has gone quiet. The touch keys on screen still work.");
  await expect(app.locator("#fault")).toBeHidden();
  rig.replugKeyboard();
  await expect(app.locator("#kb-notice-play")).toBeHidden();
});

test("no keyboard ever attached: no 'gone quiet' line, and the station plays by touch (QA-ADV-04, UX 9)", async ({ app, rig }) => {
  await go(app, "play");
  rig.setHealth({ midi_present: false }); // a touch-only station: nothing was unplugged
  await expect.poll(() => app.evaluate(() => window.__seastones.live.heartbeat.midi_present)).toBe(false);
  await app.waitForTimeout(300);
  await expect(app.locator("#kb-notice-play")).toBeHidden();
  await expect(app.locator("#fault")).toBeHidden();
  // the line, when it does show, sits clear of the keys and the chips
  rig.unplugKeyboard();
  await expect(app.locator("#kb-notice-play")).toBeVisible();
  const r = await app.evaluate(() => {
    const b = (s) => document.querySelector(s).getBoundingClientRect();
    const n = b("#kb-notice-play"), kb = b("#layer-play .kb");
    const hit = [...document.querySelectorAll("#layer-play .chip, #putback, #layer-play .speed-card")].some((e) => {
      const r = e.getBoundingClientRect();
      return Math.min(r.right, n.right) > Math.max(r.left, n.left) && Math.min(r.bottom, n.bottom) > Math.max(r.top, n.top);
    });
    return { gap: kb.top - n.bottom, hit };
  });
  expect(r.hit).toBe(false);
  expect(r.gap).toBeGreaterThanOrEqual(2);
});

test("rigd killed: the error state is up within 3 s, shows no stale lamp, and clears on restart (UI-34, KIOSK-4, KP-05)", async ({ app, rig }) => {
  await go(app, "computer");
  await app.waitForTimeout(300);
  const t0 = Date.now();
  rig.kill();
  await expect(app.locator("#fault")).toBeVisible({ timeout: 3000 });
  expect(Date.now() - t0).toBeLessThan(3000);
  await expect(app.locator("#fault-headline")).toHaveText("The computer is restarting.");
  await expect(app.locator("#fault-staff")).toContainText("bridge connection lost");
  // nothing on the panel stays lit: the page forgot the last state rather than freeze it
  await app.waitForTimeout(200);
  for (let i = 0; i < 16; i++) expect(await brightness(app.locator("#layer-computer .lamprow").first().locator(".lamp-s").nth(i))).toBe(0);
  await expect(app.locator("#hdr-speed")).toHaveText("·");
  rig.revive();
  await expect(app.locator("#fault")).toBeHidden({ timeout: 10000 });
  await expect(app.locator("#layer-attract")).toBeVisible();
});

test("a heartbeat that stops (rigd hung) is a dead link after the 3 s deadline (KIOSK-2)", async ({ app, rig }) => {
  await go(app, "play");
  // rigd hangs: it stops sending anything and stops answering new connections, but the
  // page's socket stays open, so only the heartbeat deadline can notice
  clearInterval(rig.timer);
  rig.accepting = false;
  const t0 = Date.now();
  await expect(app.locator("#fault")).toBeVisible({ timeout: 6000 });
  expect(Date.now() - t0).toBeGreaterThanOrEqual(2000);
  rig.accepting = true;
  rig.timer = setInterval(() => rig.tick(), 1000 / 60);
  await expect(app.locator("#fault")).toBeHidden({ timeout: 10000 });
});

test("cold start: the attract screen says WAKING UP and lights stones as stages come up (UX 5.1)", async ({ page }) => {
  const rig = new FakeEngine();
  rig.setStages({ computer: true, program: false, synth: false, output: false });
  await rig.start(0);
  try {
    await open(page, rig);
    await expect(page.locator("#attract-pill")).toContainText(/waking up/i);
    await expect(page.locator("#fault")).toBeHidden();
    rig.setStages({ program: true, synth: true, output: true });
    await expect(page.locator("#attract-pill")).toContainText(/play the keys/i);
  } finally {
    await rig.stop();
  }
});

test("no fault path makes a sound or draws an invented value (KIOSK-4)", async ({ app, rig }) => {
  await go(app, "play");
  rig.fault("dsp_fault");
  await expect(app.locator("#fault")).toBeVisible();
  // the fixture fails the test on any sound API; the page has none to call
  expect(await app.evaluate(() => window.__soundCalls.length)).toBe(0);
  rig.clearFault("dsp_fault");
});
