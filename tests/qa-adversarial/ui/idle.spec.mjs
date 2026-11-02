// Idle reset under a visitor who is plainly mid-action (QA-ADV-02; NFR-10 "the idle reset warns
// first and never resets a visitor mid-action", PLAY-8). The staff idle timeout is set to its
// floor, 30 s (warning at 15 s), through staff.conf, so each case runs in about 35 s.
import { test, expect, touch, go, layer, centre } from "./real.mjs";

test.use({ staffConf: { settings: { idle_timeout_s: 30 } } });

/** Watch for the veil and the reset for `ms` while `act()` runs each 100 ms. */
async function watch(page, ms, act) {
  const t0 = Date.now();
  const seen = { veil: null, reset: null };
  let i = 0;
  while (Date.now() - t0 < ms) {
    if (act) await act(i++);
    const v = await page.evaluate(() => ({ veil: !document.getElementById("veil").hidden, layer: window.__seastones.layer() }));
    if (v.veil && seen.veil === null) seen.veil = Date.now() - t0;
    if (v.layer === "attract" && seen.reset === null) seen.reset = Date.now() - t0;
    await page.waitForTimeout(100);
  }
  return seen;
}

// QA-ADV-02a (fixed in this branch, touch.js + app.js): pointermove was not activity, so a
// visitor dragging a cable around the wall without lifting got the "Still playing?" veil at
// 15 s and was reset to attract mid-drag at 30 s (75 s / 90 s with the defaults).
test("QA-ADV-02a: a cable being dragged keeps the station awake", async ({ app: page }) => {
  test.setTimeout(90000);
  await go(page, "patch");
  await page.waitForTimeout(600);
  const j = await page.evaluate(() => {
    const p = window.__seastones.live.patch.cables[0];
    const r = document.querySelector(`.jackhit[data-jack="${p.to}"]`).getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await touch(page, "touchStart", [{ x: j.x, y: j.y, id: 1 }]);
  const seen = await watch(page, 34000, (i) => touch(page, "touchMove", [{ x: j.x + 200 + 150 * Math.sin(i / 10), y: j.y + 100 + 80 * Math.cos(i / 10), id: 1 }]));
  await touch(page, "touchEnd", []);
  expect(seen).toEqual({ veil: null, reset: null });
  expect(await layer(page)).toBe("patch");
});

// QA-ADV-02b (fixed, UI lane round 6): holding STEP auto-repeats three instructions a second
// (UI-15). Each repeat is now activity (kind "move", which never wakes attract), for as long as
// the held-key rule allows a held key (held_key_release_s, 60 s), so a pinned button still
// cannot keep the station awake for ever.
test("QA-ADV-02b: holding STEP (auto-repeat) keeps the station awake", async ({ app: page }) => {
  test.setTimeout(90000);
  await go(page, "computer");
  await page.waitForTimeout(400);
  const det = await centre(page, '#layer-computer [data-speed="step"]');
  await touch(page, "touchStart", [{ x: det.x, y: det.y, id: 1 }]);
  await touch(page, "touchEnd", []);
  await expect.poll(() => page.evaluate(() => window.__seastones.live.state.speed)).toBe("step");
  const b = await centre(page, "#step-computer");
  const c0 = await page.evaluate(() => window.__seastones.live.state.cycles);
  await touch(page, "touchStart", [{ x: b.x, y: b.y, id: 2 }]);
  const seen = await watch(page, 34000);
  const c1 = await page.evaluate(() => window.__seastones.live.state && window.__seastones.live.state.cycles);
  await touch(page, "touchEnd", []);
  expect(c1, "the program stepped while STEP was held").toBeGreaterThan(c0);
  expect(seen).toEqual({ veil: null, reset: null });
});
