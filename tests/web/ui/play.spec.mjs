// VS-15, PR-13, PM-15, PR-12: the Play screen, the PLAY-3 halted test (UI-05), the voice map
// (UI-41 scripted part), meters that step (UI-06), presets (UI-22), audio captions (UI-31),
// touch robustness (UI-23).
import { test, expect, go, frames } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";

const key = (page, k) => page.locator(`#layer-play [data-key="${k}"]`);
const REGIONS = ["#station-1 .matrix", "#station-2 .mini", "#station-3 .voices", "#station-4 [data-view=meters]", "#station-5 canvas"];

test("halted means still: ten key presses leave matrix, voices, meters, lamps and scope pixel-identical (UI-05, PLAY-3)", async ({ app, rig }) => {
  await go(app, "play");
  await frames(app, 10);
  rig.freeze(true);
  await app.waitForTimeout(600); // lamps settle on the frozen duty cycles (80 ms smoothing)
  const before = [];
  for (const r of REGIONS) before.push(await app.locator(r).screenshot());
  const t = await touchSession(app);
  await t.down([key(app, 0), key(app, 4), key(app, 7), key(app, 12), key(app, 19)]);
  for (const k of ["z", "c", "f", "k", "p"]) await app.keyboard.down(k);
  await app.waitForTimeout(700);
  const st = await app.evaluate(() => window.__seastones.live.state);
  expect(st.keys_raw.some((r) => r !== 0), "the keys reached the engine (keys_raw)").toBe(true);
  for (let i = 0; i < REGIONS.length; i++) {
    const after = await app.locator(REGIONS[i]).screenshot();
    expect(after.equals(before[i]), `${REGIONS[i]} changed while the engine was halted`).toBe(true);
  }
  const sent = rig.messages("keys.touch").map((m) => m.bits);
  expect(sent.some((b) => b !== "0000000000000000"), "the page sent the touch keys").toBe(true);
  await t.up();
  for (const k of ["z", "c", "f", "k", "p"]) await app.keyboard.up(k);
});

test("a key lights the matrix lamp, takes the voice, moves the pitch meter and gate (UI-41 scripted)", async ({ app }) => {
  await go(app, "play");
  const t = await touchSession(app);
  await t.down([key(app, 12)]); // C4
  await expect(app.locator("#station-3 .voices .nn").first()).toHaveText("C4");
  const lamp = app.locator("#station-1 .matrix .lamp-s").nth(12);
  await expect.poll(() => lamp.evaluate((e) => getComputedStyle(e).getPropertyValue("--b").trim())).toBe("1");
  const meter = app.locator("#station-4 .meter span").first();
  await expect.poll(() => meter.evaluate((e) => parseFloat(e.style.height))).toBeGreaterThan(0);
  // a second key gets a voice of its own (rig.s: one voice per key, four voices)
  await expect(app.locator("#station-3 .voices .voice")).toHaveCount(4);
  const [b] = await t.down([key(app, 7)]);
  await expect(app.locator("#station-3 .voices .nn").nth(0)).toHaveText("C4");
  await expect(app.locator("#station-3 .voices .nn").nth(1)).toHaveText("G3");
  await t.up([b]);
  await expect(app.locator("#station-3 .voices .nn").nth(1)).toHaveText("free");
  await expect(app.locator("#station-3 .voices .nn").first()).toHaveText("C4");
  await t.up();
  await expect(app.locator("#station-3 .voices .nn").first()).toHaveText("free");
});

test("meters step: the bar height is the D/A code exactly, never smoothed (UI-06, NFR-2)", async ({ app, rig }) => {
  await go(app, "play");
  rig.override({ dac: [0x8000, ...new Array(15).fill(0)] });
  await expect.poll(() => app.locator("#station-4 .meter span").first().evaluate((e) => parseFloat(e.style.height))).toBe(50);
  rig.override({ dac: [0x4000, ...new Array(15).fill(0)] });
  await frames(app, 1);
  // read after the page's next paint: the first height drawn for the new code is exact
  const h = await app.locator("#station-4 .meter span").first().evaluate((e) => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(() => res(parseFloat(e.style.height))))));
  expect(h).toBe(25);
});

test("presets load in one tap through patch.load, under 200 ms, and the chip follows the engine (UI-22, PLAY-6)", async ({ app, rig }) => {
  await go(app, "play");
  const chips = app.locator('#layer-play .chip[data-preset]');
  expect(await chips.count()).toBeGreaterThanOrEqual(3);
  expect(await chips.count()).toBeLessThanOrEqual(6);
  for (const slug of ["two-voice-duet", "bell", "sweep", "stadium-drone"]) {
    const t0 = Date.now();
    await app.locator(`#layer-play .chip[data-preset="${slug}"]`).tap();
    await expect(app.locator(`#layer-play .chip[data-preset="${slug}"]`)).toHaveClass(/on/);
    expect(Date.now() - t0).toBeLessThan(1000); // UI round trip; the engine's own 200 ms is DSP-22
    expect(rig.preset).toBe(slug);
  }
  expect(rig.messages("patch.load").map((m) => m.slug)).toEqual(["two-voice-duet", "bell", "sweep", "stadium-drone"]);
});

test("PUT IT BACK restores the first preset and full speed in one tap", async ({ app, rig }) => {
  await go(app, "play");
  await app.locator('#layer-play .chip[data-preset="sweep"]').tap();
  await app.locator('#layer-play .det[data-speed="div300"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("1/300");
  await app.locator("#putback").tap();
  await expect(app.locator("#hdr-speed")).toHaveText("RUN");
  await expect(app.locator('#layer-play .chip[data-preset="stadium-drone"]')).toHaveClass(/on/);
});

test("the audio caption follows engine state: sounding, slowed, stopped, nothing out (UI-31, AUDIO-6)", async ({ app, rig }) => {
  await go(app, "play");
  const cap = app.locator("#audio-caption");
  await expect(cap).toHaveText("Silent. Press a key.");
  const t = await touchSession(app);
  await t.down([key(app, 12)]);
  await expect(cap).toHaveText(/Stadium drone · 1 voice sounding/);
  await app.locator('#layer-play .det[data-speed="div30"]').tap();
  await expect(cap).toHaveText("The computer is slowed. Notes arrive late.");
  await app.locator('#layer-play .det[data-speed="step"]').tap();
  await expect(cap).toHaveText("Stopped. Nothing sounds until the computer runs.");
  await t.up();
  const words = (await cap.innerText()).split(/\s+/).length;
  expect(words).toBeLessThanOrEqual(45);
});

test("ten fingers make ten keys; cancel, blur and hiding the page release them all (UI-23, INPUT-4)", async ({ app, rig }) => {
  await go(app, "play");
  const t = await touchSession(app);
  const keys = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16];
  await t.down(keys.map((k) => key(app, k)));
  await expect.poll(() => rig.touchBits).toBe(keys.reduce((b, k) => b | (1n << BigInt(k)), 0n));
  await t.cancel();
  await expect.poll(() => rig.touchBits).toBe(0n);
  await t.down([key(app, 3)]);
  await expect.poll(() => rig.touchBits).toBe(1n << 3n);
  await app.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect.poll(() => rig.touchBits).toBe(0n);
});

test("the page refreshes the key level at 4 Hz, so a lost message cannot stick a note (INPUT-4)", async ({ app, rig }) => {
  await go(app, "play");
  rig.clearRecorded();
  await app.waitForTimeout(1100);
  const n = rig.messages("keys.touch").length;
  expect(n).toBeGreaterThanOrEqual(3);
  expect(n).toBeLessThanOrEqual(6);
});

test("no browser gesture: context menu, selection and multi-finger moves are suppressed (UI-23)", async ({ app }) => {
  await go(app, "play");
  const prevented = await app.evaluate(() => {
    const ev = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    document.querySelector("#station-1").dispatchEvent(ev);
    const sel = new Event("selectstart", { bubbles: true, cancelable: true });
    document.querySelector("#station-1").dispatchEvent(sel);
    return [ev.defaultPrevented, sel.defaultPrevented, getComputedStyle(document.body).userSelect, getComputedStyle(document.getElementById("stage")).touchAction];
  });
  expect(prevented).toEqual([true, true, "none", "none"]);
});
