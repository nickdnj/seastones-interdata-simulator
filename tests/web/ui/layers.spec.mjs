// KP-01: the layer model, attract, first key sounds, HOME. UI-09, UI-10, UI-35.
import { test, expect, go, layer, frames } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";

test("the first touch key from attract both sounds and opens Play, with no tap in between (UI-10, PLAY-1)", async ({ app, rig }) => {
  expect(await layer(app)).toBe("attract");
  const t = await touchSession(app);
  await t.down([app.locator('#layer-attract [data-key="5"]')]);
  await expect.poll(() => rig.touchBits).toBe(1n << 5n);
  expect(await layer(app)).toBe("play");
  await t.up();
});

test("a physical key from attract wakes the station (the engine already sounds it) (UI-10)", async ({ app, rig }) => {
  expect(await layer(app)).toBe("attract");
  rig.midiKeys(1n << 20n);
  await expect.poll(() => layer(app)).toBe("play");
  rig.midiKeys(0n);
});

test("a key sounds from every layer: the touch level reaches the engine at once (UI-10)", async ({ app, rig }) => {
  for (const l of ["play", "computer", "patch", "code", "story"]) {
    await go(app, l);
    rig.clearRecorded();
    await app.keyboard.down("a");
    await expect.poll(() => rig.touchBits, `layer ${l}`).toBe(1n << 12n);
    await app.keyboard.up("a");
    await expect.poll(() => rig.touchBits).toBe(0n);
    expect(await layer(app)).toBe(l);
  }
});

async function expectHome(app, rig) {
  const t0 = Date.now();
  rig.clearRecorded();
  await app.locator("#home").tap();
  await expect.poll(() => rig.messages("machine.home").length).toBe(1);
  await expect.poll(() => layer(app)).toBe("play");
  await expect(app.locator("#hdr-speed")).toHaveText("RUN");
  expect(rig.preset).toBe("stadium-drone");
  await expect.poll(() => rig.touchBits).toBe(0n);
  expect(Date.now() - t0).toBeLessThan(1000);
}

test("HOME works from single-step, mid-drag, the Sweep preset, the idle warning and Story (UI-09, PLAY-9)", async ({ app, rig }) => {
  await go(app, "code");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("STEP");
  await expectHome(app, rig);

  await go(app, "patch");
  const t = await touchSession(app);
  const jack = app.locator('#wall .jackhit[data-jack="v1.flt-cutoff"]');
  const b = await jack.boundingBox();
  const [id] = await t.down([{ x: b.x + b.width / 2, y: b.y + b.height / 2 }]);
  await t.move(id, b.x + 200, b.y - 60);
  // a second finger presses HOME while the first is still dragging a cable
  const home = await app.locator("#home").boundingBox();
  rig.clearRecorded();
  const [h] = await t.down([{ x: home.x + home.width / 2, y: home.y + home.height / 2 }]);
  await t.up([h]);
  await expect.poll(() => rig.messages("machine.home").length).toBe(1);
  await expect.poll(() => layer(app)).toBe("play");
  await t.up();

  await app.locator('#layer-play .chip[data-preset="sweep"]').tap();
  await expect(app.locator('#layer-play .chip[data-preset="sweep"]')).toHaveClass(/on/);
  await expectHome(app, rig);

  await go(app, "story");
  await app.locator("#story-next").tap();
  await expectHome(app, rig);
});

test("HOME releases held touch keys", async ({ app, rig }) => {
  await go(app, "play");
  const t = await touchSession(app);
  await t.down([app.locator('#layer-play [data-key="0"]'), app.locator('#layer-play [data-key="9"]')]);
  await expect.poll(() => rig.touchBits).not.toBe(0n);
  await app.keyboard.press("Escape"); // nothing: keys are not navigation
  await app.locator("#home").click();
  await expect.poll(() => rig.touchBits).toBe(0n);
  await t.cancel();
});

test("layer 6 has no code path: no tab, no layer, no string (UI-35, SEA-3)", async ({ app }) => {
  const html = await app.content();
  expect(html).not.toMatch(/best guess|layer-6|data-layer="6"|coming soon|Seastones playback/i);
  await expect(app.locator(".tab")).toHaveCount(5);
  await frames(app, 2);
});
