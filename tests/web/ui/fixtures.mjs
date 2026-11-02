// Shared fixtures: a fresh fake engine per test, the page connected to it, and two traps that
// fail any test in which the page makes a sound (UI-32) or a request off the machine (KIOSK-6).
import { test as base, expect } from "@playwright/test";
import { FakeEngine } from "../fake-engine/engine.mjs";

const SOUND_TRAP = () => {
  window.__soundCalls = [];
  const trap = (name) => function () { window.__soundCalls.push(name); throw new Error(`the page tried to make a sound: ${name}`); };
  window.AudioContext = trap("AudioContext");
  window.webkitAudioContext = trap("webkitAudioContext");
  window.OfflineAudioContext = trap("OfflineAudioContext");
  window.Audio = trap("Audio");
  HTMLMediaElement.prototype.play = trap("HTMLMediaElement.play");
  if (window.speechSynthesis) window.speechSynthesis.speak = trap("speechSynthesis.speak");
};

export const test = base.extend({
  rig: async ({}, use) => {
    const e = new FakeEngine();
    await e.start(0);
    await use(e);
    await e.stop();
  },
  app: async ({ page, rig }, use) => {
    const offMachine = [];
    await page.addInitScript(SOUND_TRAP);
    await page.route("**/*", (route) => {
      const u = new URL(route.request().url());
      if (["127.0.0.1", "localhost"].includes(u.hostname)) return route.continue();
      offMachine.push(u.href);
      return route.abort();
    });
    await open(page, rig);
    await use(page);
    expect(offMachine, "requests off the machine").toEqual([]);
    expect(await page.evaluate(() => window.__soundCalls)).toEqual([]);
  },
});

export async function open(page, rig, extra = "") {
  await page.goto(`${process.env.SX_WEB_URL}/?rig=${encodeURIComponent(rig.url)}&hooks=1&dev=1${extra}`);
  await page.waitForFunction(() => window.__seastones && window.__seastones.live.connected && window.__seastones.live.state && window.__seastones.live.patch);
  await page.waitForFunction(() => !document.fonts || document.fonts.status === "loaded");
}

/**
 * Show a layer and wait until it has settled: shown, its slide-in finished, the data it is
 * built from arrived (listing, loop ring, patch wall), fonts loaded, and two frames painted.
 * Tests read layout only after this; a single read straight after a layer switch was the
 * source of the load-dependent flakes in `make ci`.
 */
export async function go(page, layer) {
  await page.evaluate((l) => window.__seastones.go(l), layer);
  await settled(page, layer);
}
export const settled = (page, layer) => page.waitForFunction((l) => window.__seastones.settled(l), layer, { timeout: 15000 });
export const layer = (page) => page.evaluate(() => window.__seastones.layer());
export const live = (page) => page.evaluate(() => {
  const l = window.__seastones.live;
  return { connected: l.connected, state: l.state, patch: l.patch, heartbeat: l.heartbeat };
});

/** Wait until the page has seen `n` more state messages (the engine has moved on). */
export async function frames(page, n = 3) {
  const s0 = await page.evaluate(() => window.__seastones.live.state && window.__seastones.live.state.seq);
  await page.waitForFunction(([s, k]) => window.__seastones.live.state && window.__seastones.live.state.seq >= s + k, [s0 || 0, n]);
}

/** The --b brightness of a lamp element. */
export const brightness = (loc) => loc.evaluate((el) => Number(getComputedStyle(el).getPropertyValue("--b") || 0));

export { expect };
