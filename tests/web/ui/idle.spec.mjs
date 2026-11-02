// KP-02: idle reset, the 15 s veil, the held-key rule. UI-11, UI-12, with Playwright's clock.
import { test as base, expect } from "@playwright/test";
import { FakeEngine } from "../fake-engine/engine.mjs";
import { open, go, layer } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";

const test = base.extend({
  rig: async ({}, use) => { const e = new FakeEngine(); await e.start(0); await use(e); await e.stop(); },
  app: async ({ page, rig }, use) => {
    await page.clock.install();
    await open(page, rig);
    await use(page);
  },
});

test("warning at 75 s, reset at 90 s: HOME, attract, and the next key sounds (UI-11, PLAY-8)", async ({ app, rig }) => {
  await go(app, "computer");
  await app.locator('#layer-computer .det[data-speed="div300"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("1/300");
  rig.clearRecorded();
  await app.clock.fastForward(74000);
  await expect(app.locator("#veil")).toBeHidden();
  await app.clock.fastForward(1500);
  await expect(app.locator("#veil")).toBeVisible();
  await expect(app.locator("#veil")).toContainText("Still playing?");
  await app.clock.fastForward(15000);
  await expect(app.locator("#veil")).toBeHidden();
  expect(await layer(app)).toBe("attract");
  await expect.poll(() => rig.messages("machine.home").length).toBe(1);
  await expect(app.locator("#hdr-speed")).toHaveText("RUN");
  expect(rig.preset).toBe("stadium-drone");
  // the next key from attract sounds and wakes the station
  const t = await touchSession(app);
  await t.down([app.locator('#layer-attract [data-key="12"]')]);
  await expect.poll(() => rig.touchBits).toBe(1n << 12n);
  expect(await layer(app)).toBe("play");
  await t.up();
});

test("a touch during the warning cancels it and leaves the visitor where they were (UI-11)", async ({ app }) => {
  await go(app, "patch");
  await app.clock.fastForward(76000);
  await expect(app.locator("#veil")).toBeVisible();
  await app.mouse.click(900, 500);
  await expect(app.locator("#veil")).toBeHidden();
  expect(await layer(app)).toBe("patch");
  await app.clock.fastForward(60000);
  expect(await layer(app)).toBe("patch");
});

test("the timer is monotonic: a wall-clock jump during the warning changes nothing (UI-11)", async ({ app }) => {
  await go(app, "play");
  await app.clock.fastForward(78000);
  await expect(app.locator("#veil")).toBeVisible();
  await app.clock.setSystemTime(Date.now() + 3600 * 1000);
  await app.clock.fastForward(1000);
  await expect(app.locator("#veil")).toBeVisible();
  expect(await layer(app)).toBe("play");
});

test("a key held 61 s is released and stops counting; the station then resets at its normal idle time (UI-12, PLAY-8)", async ({ app, rig }) => {
  await go(app, "play");
  const t = await touchSession(app);
  await t.down([app.locator('#layer-play [data-key="12"]')]);
  await expect.poll(() => rig.touchBits).toBe(1n << 12n);
  // under 60 s a held key is someone playing a drone: no warning at the usual 75 s mark
  await app.clock.fastForward(59000);
  await expect(app.locator("#veil")).toBeHidden();
  await app.clock.fastForward(2000);
  await app.clock.fastForward(300);
  await expect.poll(() => rig.touchBits).toBe(0n); // released by the held-key rule
  // from here the key is not activity: warning 75 s and reset 90 s after it stopped counting
  await app.clock.fastForward(72000);
  await expect(app.locator("#veil")).toBeHidden();
  await app.clock.fastForward(3000);
  await expect(app.locator("#veil")).toBeVisible();
  await app.clock.fastForward(15000);
  expect(await layer(app)).toBe("attract");
  await t.up();
});
