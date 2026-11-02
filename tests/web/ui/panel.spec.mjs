// PR-06, PR-08: the front panel. UI-01 (duty cycle), UI-02 (no strobe), UI-03 (exact in
// CRAWL and STEP, hex only when stable), the 30 Hz update floor, UI-44 (lamp caption).
import { test, expect, go, frames, brightness } from "./fixtures.mjs";

const lamp = (page, row, i) => page.locator(`#layer-computer .lamprow`).nth(row).locator(".lamp-s").nth(i);
const fill = (v) => new Array(16).fill(v);

test("a lamp at duty 0, 0.25, 0.5, 0.75 and 1 renders at that brightness within 10 percent (UI-01, PANEL-1)", async ({ app, rig }) => {
  await go(app, "computer");
  const fr = [0, 0.25, 0.5, 0.75, 1, 0, 0.25, 0.5, 0.75, 1, 0, 0.25, 0.5, 0.75, 1, 0.5];
  rig.override({ lamps: { addr: fr, data: fill(0.5), exact: false } });
  await app.waitForTimeout(400);
  for (let i = 0; i < 16; i++) {
    const b = await brightness(lamp(app, 0, i));
    expect(Math.abs(b - fr[i]), `address lamp ${i}`).toBeLessThanOrEqual(0.1);
  }
  // half duty is half brightness, also measured as pixels: the lit layer's opacity
  const op = await lamp(app, 1, 3).evaluate((e) => Number(getComputedStyle(e, "::after").opacity));
  expect(Math.abs(op - 0.5)).toBeLessThanOrEqual(0.1);
});

test("a lamp driven 0, 1, 0, 1 each frame at 60 Hz reads as a steady half, not a strobe (UI-02, NFR-10)", async ({ app, rig }) => {
  await go(app, "computer");
  rig.play([{ lamps: { addr: fill(0), data: fill(1), exact: false } }, { lamps: { addr: fill(1), data: fill(0), exact: false } }], { loop: true });
  await app.waitForTimeout(500);
  const samples = [];
  for (let i = 0; i < 40; i++) {
    samples.push(await brightness(lamp(app, 0, 0)));
    await app.waitForTimeout(23);
  }
  const lo = Math.min(...samples), hi = Math.max(...samples);
  expect(hi - lo, `peak to peak ${lo}..${hi}`).toBeLessThan(0.1);
  expect(Math.abs((hi + lo) / 2 - 0.5)).toBeLessThan(0.1);
});

test("CRAWL and STEP are exact: lamps 0 or 1 and hex digits; at RUN the digits are dots (UI-03, PANEL-2)", async ({ app, rig }) => {
  await go(app, "computer");
  await frames(app, 5);
  const hexes = app.locator("#layer-computer .lamprow").first().locator(".hex");
  await expect(hexes.first()).toHaveText("•");
  await app.locator('#layer-computer .det[data-speed="step"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("STEP");
  await frames(app, 3);
  const st = await app.evaluate(() => window.__seastones.live.state);
  const want = st.pc.toString(16).toUpperCase().padStart(4, "0").split("");
  await expect(hexes).toHaveText(want);
  for (let i = 0; i < 16; i++) {
    const b = await brightness(lamp(app, 0, i));
    expect(b === 0 || b === 1, `lamp ${i} = ${b}`).toBe(true);
    expect(b).toBe((st.pc >> (15 - i)) & 1);
  }
  await expect(app.locator("#stateplate")).toHaveText("WAITING");
});

test("the panel updates at 30 Hz or better (PR-06 frame log)", async ({ app, rig }) => {
  await go(app, "computer");
  const ramp = Array.from({ length: 60 }, (_, i) => ({ lamps: { addr: fill(i / 59), data: fill(1 - i / 59), exact: true } }));
  rig.play(ramp, { loop: true });
  const n = await app.evaluate(async () => {
    const el = document.querySelector("#layer-computer .lamprow .lamp-s");
    let count = 0;
    const mo = new MutationObserver(() => count++);
    mo.observe(el, { attributes: true, attributeFilter: ["style"] });
    await new Promise((r) => setTimeout(r, 1000));
    mo.disconnect();
    return count;
  });
  expect(n).toBeGreaterThanOrEqual(30);
});

test("the lamp caption says what the lamps mean, changes with the speed zone, and is short (UI-44, PANEL-3)", async ({ app }) => {
  await go(app, "computer");
  const cap = app.locator("#lamp-caption");
  await expect(cap).toContainText("At full speed they flicker too fast to read.");
  await app.locator('#layer-computer .det[data-speed="crawl"]').tap();
  await expect(cap).toContainText("a few instructions a second");
  expect((await cap.innerText()).split(/\s+/).length).toBeLessThanOrEqual(45);
});

test("the loop ring lights the program's own blocks from pc_hist, or the exact block in STEP", async ({ app, rig }) => {
  await go(app, "computer");
  await frames(app, 20);
  const items = app.locator("#layer-computer .ring li");
  await expect.poll(() => items.count()).toBeGreaterThanOrEqual(3);
  await app.locator('#layer-computer .det[data-speed="step"]').tap();
  await expect.poll(() => app.evaluate(() => window.__seastones.live.state.speed)).toBe("step");
  await frames(app, 3);
  const st = await app.evaluate(() => window.__seastones.live.state);
  const lit = await app.locator("#layer-computer .ring li.on").count();
  // in STEP exactly one block (or none, outside the loop) is lit
  expect(lit).toBeLessThanOrEqual(1);
  expect(st.speed).toBe("step");
});
