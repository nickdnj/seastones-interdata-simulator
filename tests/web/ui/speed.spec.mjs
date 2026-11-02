// PR-07: the speed knob, detents, STEP and FULL SPEED. UI-13, UI-14, UI-15.
import { test, expect, go, frames } from "./fixtures.mjs";
import { SPEEDS } from "../fake-engine/engine.mjs";

const LAYERS = ["play", "computer", "code", "patch", "story"];

test("FULL SPEED shows at all five non-RUN detents in every layer and restores RUN in one tap (UI-13, PLAY-11)", async ({ app, rig }) => {
  for (const l of LAYERS) {
    await go(app, l);
    for (const sp of SPEEDS.slice(1)) {
      rig.speed = sp.id;
      await expect(app.locator("#hdr-speed")).toHaveText(sp.label);
      await expect(app.locator("#fullspeed")).toBeVisible();
      await app.locator("#fullspeed").tap();
      await expect(app.locator("#hdr-speed")).toHaveText("RUN");
      await expect(app.locator("#fullspeed")).toBeHidden();
      expect(rig.speed).toBe("run");
    }
  }
});

test("the header SPEED always equals the engine's speed, over 100 seeded transitions (UI-13)", async ({ app, rig }) => {
  const seed = 1974;
  let x = seed;
  const rnd = () => ((x = (x * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  console.log(`speed transitions seed ${seed}`);
  await go(app, "play");
  for (let i = 0; i < 100; i++) {
    const sp = SPEEDS[Math.floor(rnd() * SPEEDS.length)];
    if (rnd() < 0.5) rig.speed = sp.id; // the engine changed (another visitor, HOME, idle)
    else await app.locator(`#layer-play .det[data-speed="${sp.id}"]`).tap(); // this visitor
    await expect(app.locator("#hdr-speed")).toHaveText(sp.label);
    await expect(app.locator(`#layer-play .det[data-speed="${sp.id}"]`)).toHaveClass(/on/);
  }
});

test("six detents in knob order with the engine's labels; the page fakes no lateness (UI-14)", async ({ app }) => {
  await go(app, "play");
  await expect(app.locator("#layer-play .det")).toHaveText(SPEEDS.map((s) => s.label).map((l) => new RegExp(`^${l.replace("/", "\\/")}`)));
  for (const sp of SPEEDS) {
    await app.locator(`#layer-play .det[data-speed="${sp.id}"]`).tap();
    await expect(app.locator("#speed-say")).not.toHaveText("");
  }
  await expect(app.locator("#k2s")).toHaveText("waits for STEP");
});

test("dragging the knob 60 px a detent, and a tap advances one (UI-14)", async ({ app, rig }) => {
  await go(app, "computer");
  const knob = app.locator("#panel-knob");
  const b = await knob.boundingBox();
  await app.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await app.mouse.down();
  await app.mouse.move(b.x + b.width / 2 + 125, b.y + b.height / 2, { steps: 8 });
  await app.mouse.up();
  await expect.poll(() => rig.speed).toBe("div300");
  await knob.click();
  await expect.poll(() => rig.speed).toBe("div3000");
});

test("STEP sends exactly one machine.step per touch, and repeats at 3 a second after 600 ms held (UI-15)", async ({ app, rig }) => {
  await go(app, "code");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("STEP");
  rig.clearRecorded();
  for (let i = 0; i < 5; i++) await app.locator("#step-code").tap();
  await expect.poll(() => rig.messages("machine.step").length).toBe(5);
  rig.clearRecorded();
  const b = await app.locator("#step-code").boundingBox();
  await app.mouse.move(b.x + 40, b.y + 30);
  await app.mouse.down();
  await app.waitForTimeout(2000);
  await app.mouse.up();
  const n = rig.messages("machine.step").length;
  // 1 at touch, then (2000 - 600) / 333 = 4.2 repeats: 5 or 6 with timer jitter
  expect(n).toBeGreaterThanOrEqual(5);
  expect(n).toBeLessThanOrEqual(6);
});

test("STEP does nothing at speed: the button is dimmed and sends no step", async ({ app, rig }) => {
  await go(app, "computer");
  rig.clearRecorded();
  await app.locator("#step-computer").tap();
  await frames(app, 2);
  expect(rig.messages("machine.step").length).toBe(0);
  await expect(app.locator("#step-computer")).toHaveClass(/off/);
});
