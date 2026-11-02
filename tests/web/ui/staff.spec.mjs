// KP-07, KP-08, KP-09 and CT-07's entry: the staff screen against the fake engine's staff
// protocol. Everything is done by touch (taps and one long press): the floor has no
// keyboard or mouse (UX 5.11, KP-07 AC 4).
import { test as base } from "@playwright/test";
import { test, expect, go, open } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";
import { FakeEngine } from "../fake-engine/engine.mjs";

// With Playwright's clock installed before the page loads (as idle.spec does).
const clockTest = base.extend({
  rig: async ({}, use) => { const e = new FakeEngine(); await e.start(0); await use(e); await e.stop(); },
  app: async ({ page, rig }, use) => { await page.clock.install(); await open(page, rig); await use(page); },
});
async function openStaffClock(page, rig) {
  if ((await page.evaluate(() => window.__seastones.layer())) === "attract") await go(page, "play");
  const t = await touchSession(page);
  const box = await page.locator("#header .mark").boundingBox();
  await t.down([{ x: box.x + box.width / 2, y: box.y + box.height / 2 }]);
  await page.clock.fastForward(3200);
  await t.up();
  await expect(page.locator("#staff-pin")).toBeVisible();
  await enterPin(page, rig.staffPin);
  await expect(page.locator("#staff-screen")).toBeVisible();
}

async function hold(page, ms) {
  if ((await page.evaluate(() => window.__seastones.layer())) === "attract") await go(page, "play");
  const t = await touchSession(page);
  const box = await page.locator("#header .mark").boundingBox();
  await t.down([{ x: box.x + box.width / 2, y: box.y + box.height / 2 }]);
  await page.waitForTimeout(ms);
  await t.up();
}
async function enterPin(page, pin) {
  for (const d of pin) await page.locator(`#staff-key-${d}`).tap();
  await page.locator("#staff-key-ok").tap();
}
async function openStaff(page, rig) {
  await hold(page, 3300);
  await expect(page.locator("#staff-pin")).toBeVisible();
  await enterPin(page, rig.staffPin);
  await expect(page.locator("#staff-screen")).toBeVisible();
}

test("a tap or a short hold on the logo never opens it; a 3 s hold opens the PIN pad (KP-07 AC 1)", async ({ app }) => {
  await go(app, "play");
  await app.locator("#header .mark").tap();
  await hold(app, 1500);
  await expect(app.locator("#staff-pin")).toBeHidden();
  // two fingers at once are not the gesture either
  const t = await touchSession(app);
  const box = await app.locator("#header .mark").boundingBox();
  await t.down([{ x: box.x + 20, y: box.y + 20 }, { x: box.x + 50, y: box.y + 30 }]);
  await app.waitForTimeout(3300);
  await t.up();
  await expect(app.locator("#staff-pin")).toBeHidden();
  await hold(app, 3300);
  await expect(app.locator("#staff-pin")).toBeVisible();
  await app.locator("#staff-pin-cancel").tap();
  await expect(app.locator("#staff-pin")).toBeHidden();
});

test("a wrong PIN is refused with not_staff and the tries left; five wrong tries lock it (KP-07 AC 1, AC 3)", async ({ app, rig }) => {
  await hold(app, 3300);
  await enterPin(app, "0000");
  await expect(app.locator("#staff-pin-msg")).toContainText("4 tries left");
  await expect(app.locator("#staff-screen")).toBeHidden();
  for (let i = 0; i < 4; i++) await enterPin(app, "0000");
  await expect(app.locator("#staff-pin-msg")).toContainText(/Wait \d+ seconds/);
  await enterPin(app, rig.staffPin);
  await expect(app.locator("#staff-screen")).toBeHidden();
  const auths = rig.messages("staff.auth");
  expect(auths.length).toBe(6);
});

test("the staff screen shows health and diagnostics from the live protocol (KP-07)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await expect(app.locator("#staff-h-emulator")).toHaveText("ok");
  await expect(app.locator("#staff-h-bridge")).toHaveText("ok");
  await expect(app.locator("#staff-h-image")).toHaveText(rig.imageDoc.sha256.slice(0, 16));
  await expect(app.locator("#staff-h-dac")).toContainText("12-bit");
  await expect(app.locator("#staff-h-faults")).toHaveText("none");
  rig.setHealth({ midi_present: false });
  await expect(app.locator("#staff-h-keyboard")).toHaveText("not ok");
  rig.fault("dsp_fault");
  await expect(app.locator("#staff-h-faults")).toContainText("dsp_fault");
  rig.clearFault("dsp_fault");
  rig.midiKeys(1n << 12n);
  await expect(app.locator("#staff-h-keys")).toContainText("08");
});

test("volume, mute and quiet hours go to rigd and come back from it (KP-08, STAFF-2)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await expect(app.locator("#staff-ceiling")).toHaveText("72 dBA");
  for (let i = 0; i < 6; i++) await app.locator("#staff-ceiling-plus").tap();
  await expect(app.locator("#staff-ceiling")).toHaveText("78 dBA"); // the hardware maximum
  await app.locator("#staff-ceiling-minus").tap();
  await expect(app.locator("#staff-ceiling")).toHaveText("76 dBA");
  await app.locator("#staff-mute").tap();
  await expect(app.locator("#staff-mute")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => app.evaluate(() => window.__seastones.live.heartbeat.muted)).toBe(true);
  await app.locator("#staff-quiet-from-plus").tap();
  await expect(app.locator("#staff-quiet-from")).toHaveText("12:30");
  await app.locator("#staff-test-tone").tap();
  await expect.poll(() => rig.staffLog.map(([t]) => t)).toContain("staff.test_tone");
  // the page itself made no sound (the fixture's trap would fail the test)
});

test("idle timeout and reduced motion apply to the page at once (KP-08)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await expect(app.locator("#staff-idle")).toHaveText("90 s");
  await app.locator("#staff-idle-plus").tap();
  await expect(app.locator("#staff-idle")).toHaveText("105 s");
  await expect(app.locator("body")).not.toHaveClass(/reduced/);
  await app.locator("#staff-motion").tap();
  await expect(app.locator("body")).toHaveClass(/reduced/);
  await app.locator("#staff-motion").tap();
  await expect(app.locator("body")).not.toHaveClass(/reduced/);
});

test("review mode from the staff screen: drafts show with a banner on every layer, and leave with it (CT-07, KP-09)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await app.locator("#staff-review").tap();
  await expect(app.locator("#staff-review")).toHaveAttribute("aria-pressed", "true");
  await app.locator("#staff-close").tap();
  await expect(app.locator("#staff-screen")).toBeHidden();
  for (const l of ["play", "computer", "code", "patch", "story"]) {
    await go(app, l);
    await expect(app.locator("#review-banner")).toBeVisible();
  }
  // it sits in the header's empty centre: over neither the brand, the status line nor a layer
  const box = (s) => app.locator(s).first().boundingBox();
  const hit = (a, b) => Math.min(a.x + a.width, b.x + b.width) > Math.max(a.x, b.x) && Math.min(a.y + a.height, b.y + b.height) > Math.max(a.y, b.y);
  const banner = await box("#review-banner");
  await go(app, "play");
  for (const sp of ["run", "div3000", "crawl"]) {
    await app.locator(`#layer-play .det[data-speed="${sp}"]`).tap(); // the status line is widest slowed
    await expect(app.locator("#hdr-speed")).not.toHaveText("RUN", { timeout: 2000 }).catch(() => {});
    for (const s of [".brand", ".status", "#main"]) expect(hit(banner, await box(s)), `${s} at ${sp}`).toBe(false);
  }
  await app.locator('#layer-play .det[data-speed="run"]').tap();
  expect(await app.locator("#review-banner").evaluate((e) => e.scrollWidth <= e.clientWidth + 1)).toBe(true);
  // the drafts are there, stamped
  await go(app, "story");
  let stamped = 0;
  for (let i = 0; i < 12 && !stamped; i++) {
    stamped = await app.locator(".draft-stamp").count();
    if (!stamped) await app.locator("#story-next, .pager button:last-child").first().tap();
  }
  expect(stamped).toBeGreaterThan(0);
  // review mode belongs to the station: a reconnect keeps it, until staff turn it off
  rig.kill();
  rig.revive();
  await expect.poll(() => app.evaluate(() => window.__seastones.live.connected), { timeout: 15000 }).toBe(true);
  await expect(app.locator("#review-banner")).toBeVisible();
  // recovery starts the station over at attract; hold the logo only once that has happened
  await expect(app.locator("#fault")).toBeHidden({ timeout: 10000 });
  await expect.poll(() => app.evaluate(() => window.__seastones.layer())).toBe("attract");
  await openStaff(app, rig);
  await app.locator("#staff-review").tap();
  await expect(app.locator("#review-banner")).toBeHidden();
});

test("save preset, restart the computer, and close; nothing works after close (KP-09)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await app.locator("#staff-save").tap();
  await expect(app.locator("#staff-note")).toContainText(/Saved as staff-\d+/);
  // a restart needs a second tap within 3 s
  await app.locator("#staff-restart-computer").tap();
  await expect(app.locator("#staff-restart-computer")).toHaveText("Tap again to confirm");
  expect(rig.staffLog.some(([t]) => t === "staff.restart")).toBe(false);
  await app.locator("#staff-restart-computer").tap();
  await expect.poll(() => rig.staffLog.some(([t, a]) => t === "staff.restart" && a.what === "computer")).toBe(true);
  await app.locator("#staff-close").tap();
  await expect.poll(() => rig.messages("staff.close").length).toBe(1);
  const r = await app.evaluate(() => new Promise((res) => {
    const ws = new WebSocket(new URLSearchParams(location.search).get("rig"));
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.t === "nack") { res(m.code); ws.close(); } };
    ws.onopen = () => ws.send(JSON.stringify({ v: 1, t: "staff.mute", id: 9, on: true }));
  }));
  expect(r).toBe("not_staff");
});

test("restart the whole station: the page shows the restart card and comes back on its own (KP-09, KP-05)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await app.locator("#staff-restart-station").tap();
  await app.locator("#staff-restart-station").tap();
  await expect(app.locator("#staff-screen")).toBeHidden();
  await expect(app.locator("#fault")).toBeVisible();
  await expect(app.locator("#fault-headline")).toHaveText("The computer is restarting.");
  await expect(app.locator("#fault")).toBeHidden({ timeout: 15000 });
  await expect.poll(() => app.evaluate(() => window.__seastones.layer())).toBe("attract");
});

clockTest("the staff screen closes itself, and the session with it, after two minutes untouched", async ({ app, rig }) => {
  await openStaffClock(app, rig);
  await app.clock.fastForward(110000);
  await expect(app.locator("#staff-screen")).toBeVisible();
  await app.clock.fastForward(11000);
  await expect(app.locator("#staff-screen")).toBeHidden();
  await expect.poll(() => rig.messages("staff.close").length).toBe(1);
});

test("the About page opens from the staff screen too, closing it (KP-07, CT-09)", async ({ app, rig }) => {
  await openStaff(app, rig);
  await app.locator("#staff-about").tap();
  await expect(app.locator("#staff-screen")).toBeHidden();
  await expect(app.locator("#about-page")).toBeVisible();
  await expect.poll(() => rig.messages("staff.close").length).toBe(1);
});

clockTest("idle never resets the station under an open staff screen", async ({ app, rig }) => {
  await go(app, "computer");
  await openStaffClock(app, rig);
  await app.clock.fastForward(100000);
  await expect(app.locator("#veil")).toBeHidden();
  await expect(app.locator("#staff-screen")).toBeVisible();
  expect(await app.evaluate(() => window.__seastones.layer())).toBe("computer");
});
