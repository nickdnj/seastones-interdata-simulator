// The Patch screen with the engine's larger preset set (PM-10, PM-11, PM-12, PM-15, CT-07):
// presets with different modules rebuild the wall under a visitor's fingers, and nothing
// half-done (a drag, a selected jack, a remove bubble) may act on a jack that has gone.
import { test, expect, go, frames, open } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";
import { FakeEngine } from "../fake-engine/engine.mjs";

const FLOOR = ["stadium-drone", "two-voice-duet", "bell", "sweep", "computer-rhythm"];
const jack = (page, id) => page.locator(`#wall .jackhit[data-jack="${id}"]`);
const centre = async (loc) => { const b = await loc.boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
const chipSlugs = (page) => page.locator("#layer-patch .chip").evaluateAll((els) => els.map((e) => e.dataset.preset));
const wallJacks = (page) => page.locator("#wall .jackhit").evaluateAll((els) => els.map((e) => e.dataset.jack).sort());
const sameCables = async (page, rig) => {
  const norm = (cs) => cs.map((c) => [c.from, c.to].sort().join("|")).sort();
  return JSON.stringify(norm(await page.evaluate(() => window.__seastones.live.patch.cables))) === JSON.stringify(norm(rig.cables));
};

function errorsOf(page) {
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  return errs;
}

test("the floor strip is the UX five, in kiosk.conf order; review mode adds the engine lane's drafts (PM-15, CT-07)", async ({ app }) => {
  await go(app, "patch");
  await expect.poll(() => chipSlugs(app)).toEqual(FLOOR);
  await app.evaluate(() => window.__seastones.setReview(true));
  await expect.poll(async () => (await chipSlugs(app)).length).toBe(9);
  const slugs = await chipSlugs(app);
  expect(slugs.slice(0, 5)).toEqual(FLOOR);
  expect(slugs).toContain("big-steps");
  expect(slugs).not.toContain("eight-voices"); // another map's patch is never offered
  // nine chips still fit the row, clear of the help and the keys, at the touch height
  const r = await app.evaluate(() => {
    const box = (s) => document.querySelector(s).getBoundingClientRect();
    const row = box("#layer-patch .patch-controls"), help = box("#patch-help"), kb = box("#layer-patch .kb");
    const chips = [...document.querySelectorAll("#layer-patch .chip")].map((c) => c.getBoundingClientRect());
    return { rowBottom: row.bottom, helpTop: help.top, kbTop: kb.top, minH: Math.min(...chips.map((c) => c.height)), oneLine: new Set(chips.map((c) => Math.round(c.top))).size };
  });
  expect(r.oneLine).toBe(1);
  expect(r.minH).toBeGreaterThanOrEqual(54);
  expect(r.rowBottom).toBeLessThanOrEqual(Math.min(r.helpTop, r.kbTop));
  // on Play the same nine chips and PUT IT BACK stay above the keys
  await go(app, "play");
  await expect(app.locator("#putback")).toBeVisible();
  const p = await app.evaluate(() => {
    const kb = document.querySelector("#layer-play .kb").getBoundingClientRect();
    const items = [...document.querySelectorAll("#layer-play .chip, #putback")].map((c) => c.getBoundingClientRect());
    return { bottom: Math.max(...items.map((c) => c.bottom)), kbTop: kb.top, n: items.length };
  });
  expect(p.n).toBe(10);
  expect(p.bottom).toBeLessThanOrEqual(p.kbTop - 8);
  await go(app, "patch");
  await app.evaluate(() => window.__seastones.setReview(false));
  await expect.poll(() => chipSlugs(app)).toEqual(FLOOR);
});

test("every preset, loaded from its chip, rebuilds the wall to the engine's modules and cables (PM-15)", async ({ app, rig }) => {
  const errs = errorsOf(app);
  await go(app, "patch");
  await app.evaluate(() => window.__seastones.setReview(true));
  await expect.poll(async () => (await chipSlugs(app)).length).toBe(9);
  for (const slug of await chipSlugs(app)) {
    await app.locator(`#layer-patch .chip[data-preset="${slug}"]`).tap();
    await expect(app.locator(`#layer-patch .chip[data-preset="${slug}"]`)).toHaveClass(/on/);
    expect(rig.preset).toBe(slug);
    await expect.poll(() => sameCables(app, rig)).toBe(true);
    await expect.poll(async () => JSON.stringify(await wallJacks(app))).toBe(JSON.stringify([...rig.jackIds].sort()));
  }
  // Big steps has two wildcard ports on every voice card; Bell has no LFO plate
  await app.locator('#layer-patch .chip[data-preset="big-steps"]').tap();
  await expect(jack(app, "v4.osc-mod")).toHaveCount(1);
  await app.locator('#layer-patch .chip[data-preset="bell"]').tap();
  await expect(jack(app, "lfo.sine")).toHaveCount(0);
  await expect(jack(app, "v1.flt-cutoff")).toHaveCount(0);
  expect(errs).toEqual([]);
});

test("ten rapid chip taps end on the last one, in the engine and on the wall (PM-15, KP-03)", async ({ app, rig }) => {
  await go(app, "patch");
  const order = ["bell", "sweep", "two-voice-duet", "computer-rhythm", "stadium-drone", "bell", "sweep", "computer-rhythm", "two-voice-duet", "sweep"];
  for (const s of order) await app.locator(`#layer-patch .chip[data-preset="${s}"]`).tap({ delay: 0 });
  await expect.poll(() => rig.preset).toBe("sweep");
  await expect(app.locator('#layer-patch .chip.on')).toHaveCount(1);
  await expect(app.locator('#layer-patch .chip[data-preset="sweep"]')).toHaveClass(/on/);
  await expect.poll(() => sameCables(app, rig)).toBe(true);
  expect(rig.messages("patch.load").length).toBe(order.length);
});

test("a preset with other modules arrives mid-drag: the drag ends cleanly, no cable to a jack that has gone (PM-10)", async ({ app, rig }) => {
  const errs = errorsOf(app);
  await go(app, "patch");
  const t = await touchSession(app);
  const a = await centre(jack(app, "lfo.tri"));
  const b = await centre(jack(app, "echo.time"));
  const [id] = await t.down([a]);
  await t.move(id, a.x + 40, a.y + 30);
  // a second finger switches to Bell, which has no LFO: the wall is rebuilt under the drag
  const bell = await centre(app.locator('#layer-patch .chip[data-preset="bell"]'));
  const [f2] = await t.down([bell]);
  await t.up([f2]);
  await expect.poll(() => rig.preset).toBe("bell");
  await expect(jack(app, "lfo.tri")).toHaveCount(0);
  rig.clearRecorded();
  for (let i = 1; i <= 5; i++) await t.move(id, a.x + ((b.x - a.x) * i) / 5, a.y + ((b.y - a.y) * i) / 5);
  await t.up([id]);
  await frames(app, 3);
  expect(rig.messages().filter((m) => m.t.startsWith("patch.") && JSON.stringify(m).includes("lfo."))).toEqual([]);
  expect(await sameCables(app, rig)).toBe(true);
  expect(errs).toEqual([]);
});

test("a jack selected for tap-to-join, then a preset change: the next tap starts afresh (PM-11)", async ({ app, rig }) => {
  await go(app, "patch");
  await jack(app, "lfo.tri").tap();
  await expect(jack(app, "lfo.tri")).toHaveClass(/sel/);
  // the change comes from the engine (another screen, HOME on the physical panel)
  rig.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.load", id: 1, slug: "bell" }));
  rig.broadcast(rig.patchMsg());
  await expect(jack(app, "lfo.tri")).toHaveCount(0);
  rig.clearRecorded();
  await jack(app, "echo.time").tap();
  await expect(jack(app, "echo.time")).toHaveClass(/sel/); // a first tap, not a join
  expect(rig.messages("patch.connect")).toEqual([]);
  await jack(app, "echo.time").tap(); // tapping it again clears the selection
  await expect(app.locator("#wall .jackhit.sel")).toHaveCount(0);
});

test("the remove bubble for a plug goes when the wall is rebuilt (PM-11)", async ({ app, rig }) => {
  await go(app, "patch");
  await jack(app, "lfo.sine").tap();
  await expect(app.locator("#remove-bubble")).toBeVisible();
  rig.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.load", id: 1, slug: "bell" }));
  rig.broadcast(rig.patchMsg());
  await expect(app.locator("#remove-bubble")).toBeHidden();
  rig.clearRecorded();
  await app.locator("#remove-bubble").evaluate((b) => b.click()); // even a stray click does nothing
  await frames(app, 2);
  expect(rig.messages("patch.disconnect")).toEqual([]);
});

test("the eight-voice map offers no four-voice preset; PUT IT BACK asks the engine for its own default (PM-12, PM-13)", async ({ page }) => {
  const rig8 = new FakeEngine({ voices: 8 });
  await rig8.start(0);
  try {
    await open(page, rig8);
    await go(page, "patch");
    await expect.poll(() => chipSlugs(page)).toEqual([]); // eight-voices is review-only
    await page.evaluate(() => window.__seastones.setReview(true));
    await expect.poll(() => chipSlugs(page)).toEqual(["eight-voices"]);
    await page.evaluate(() => window.__seastones.setReview(false));
    // pull one cable, then PUT IT BACK: machine.home, and the cables come back
    const n = rig8.cables.length;
    await jack(page, "v8.out").tap();
    await page.locator("#remove-bubble").click();
    await expect.poll(() => rig8.cables.length).toBe(n - 1);
    await page.locator("#putback-patch").tap();
    await expect.poll(() => rig8.messages("machine.home").length).toBe(1);
    await expect.poll(() => rig8.cables.length).toBe(n);
    expect(rig8.messages("patch.load")).toEqual([]);
  } finally {
    await rig8.stop();
  }
});

test("Computer rhythm sets the program going by itself: its routine runs from the switch register the patch names", async ({ app, rig }) => {
  await go(app, "patch");
  await app.locator('#layer-patch .chip[data-preset="computer-rhythm"]').tap();
  await expect.poll(() => rig.preset).toBe("computer-rhythm");
  await expect.poll(() => app.evaluate(() => (window.__seastones.live.state.sr >> 4) & 0xf)).toBe(1);
  await app.locator('#layer-patch .chip[data-preset="stadium-drone"]').tap();
  await expect.poll(() => app.evaluate(() => (window.__seastones.live.state.sr >> 4) & 0xf)).toBe(0);
});
