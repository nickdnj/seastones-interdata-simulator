// Edge cases (KP-03, KP-05, KIOSK-1, KIOSK-2, KIOSK-4, UI-23, UI-34): rapid multi-touch on keys
// and cables, a network blip with reconnect, a protocol version mismatch, snapshot gaps and
// reordering, and kiosk keys and gestures that must never reach the browser.
import { test, expect, go, frames, open, brightness } from "./fixtures.mjs";
import { touchSession } from "./touch.mjs";
import { FakeEngine } from "../fake-engine/engine.mjs";

/** A small seeded generator, so a failure replays exactly (no Math.random in tests either). */
function lcg(seed) {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
}
const litKeys = (page) => page.evaluate(() => [...document.querySelectorAll("#layer-play .wk.on, #layer-play .bk.on")].map((e) => Number(e.dataset.key)).sort((a, b) => a - b));
const bitsOf = (keys) => keys.reduce((b, k) => b | (1n << BigInt(k)), 0n);

test("rapid multi-touch on the keys: 60 seeded bursts of up to five fingers leave no stuck or lost key (KP-03, INPUT-4)", async ({ app, rig }) => {
  await go(app, "play");
  const rnd = lcg(1974);
  const t = await touchSession(app);
  const keyLoc = (k) => app.locator(`#layer-play [data-key="${k}"]`);
  let down = new Map(); // touch id -> key
  for (let i = 0; i < 60; i++) {
    const r = rnd();
    if (down.size < 5 && (r < 0.6 || down.size === 0)) {
      let k;
      do { k = Math.floor(rnd() * 37); } while ([...down.values()].includes(k));
      const [id] = await t.down([keyLoc(k)]);
      down.set(id, k);
    } else {
      const ids = [...down.keys()];
      const id = ids[Math.floor(rnd() * ids.length)];
      await t.up([id]);
      down.delete(id);
    }
    if (i % 15 === 14) {
      const want = [...down.values()].sort((a, b) => a - b);
      await expect.poll(() => litKeys(app)).toEqual(want);
      await expect.poll(() => rig.touchBits).toBe(bitsOf(want));
    }
  }
  await t.up();
  down = new Map();
  await expect.poll(() => litKeys(app)).toEqual([]);
  await expect.poll(() => rig.touchBits).toBe(0n);
});

test("two cables dragged at once by two fingers both land, and a burst of taps leaves the wall equal to the engine (PM-10, PM-11)", async ({ app, rig }) => {
  await go(app, "patch");
  const jack = (id) => app.locator(`#wall .jackhit[data-jack="${id}"]`);
  const c = async (id) => { const b = await jack(id).boundingBox(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; };
  const t = await touchSession(app);
  const a1 = await c("lfo.tri"), b1 = await c("mix0.in3");
  const a2 = await c("lfo.square"), b2 = await c("echo.time");
  const [i1, i2] = await t.down([a1, a2]);
  for (let s = 1; s <= 8; s++) {
    await t.move(i1, a1.x + ((b1.x - a1.x) * s) / 8, a1.y + ((b1.y - a1.y) * s) / 8);
    await t.move(i2, a2.x + ((b2.x - a2.x) * s) / 8, a2.y + ((b2.y - a2.y) * s) / 8);
  }
  await t.up();
  const has = (a, b) => rig.cables.some((x) => (x.from === a && x.to === b) || (x.from === b && x.to === a));
  await expect.poll(() => has("lfo.tri", "mix0.in3") && has("lfo.square", "echo.time")).toBe(true);
  // a fast burst of tap-to-join pairs and repeat taps
  for (const [a, b] of [["dac.9", "send.in3"], ["dac.10", "busl.in4"], ["dac.9", "send.in3"], ["dac.11", "lfo.rate"]]) {
    await jack(a).tap();
    await jack(b).tap();
  }
  await frames(app, 4);
  const pagePatch = await app.evaluate(() => window.__seastones.live.patch.cables.map((x) => [x.from, x.to].sort().join("|")).sort());
  expect(pagePatch).toEqual(rig.cables.map((x) => [x.from, x.to].sort().join("|")).sort());
  // no drag left behind: nothing is lifted, no jack is still selected after a completed pair
  expect(await app.locator("#wall .jackhit.sel").count()).toBeLessThanOrEqual(1);
});

test("a network blip: lamps go dark at once, the page reconnects by itself, and shows only the new state (KIOSK-2, KIOSK-4)", async ({ app, rig }) => {
  await go(app, "computer");
  const lamps = app.locator("#layer-computer .lamprow").first().locator(".lamp-s");
  const A = Array.from({ length: 16 }, (_, i) => (i % 2 ? 1 : 0));
  const B = Array.from({ length: 16 }, (_, i) => (i < 8 ? 1 : 0));
  rig.override({ lamps: { addr: A, data: A, exact: false } });
  await expect.poll(() => brightness(lamps.nth(1))).toBeGreaterThan(0.9);
  // the link drops; rigd keeps running but does not take the reconnect yet
  rig.accepting = false;
  rig.blip();
  await expect.poll(async () => { let s = 0; for (let i = 0; i < 16; i++) s += await brightness(lamps.nth(i)); return s; }, { timeout: 4000 }).toBe(0);
  // while it was away the machine moved on
  rig.override({ lamps: { addr: B, data: B, exact: false } });
  rig.accepting = true;
  await expect.poll(() => app.evaluate(() => window.__seastones.live.connected), { timeout: 10000 }).toBe(true);
  // recovery starts the station over at attract (UX 5.8); the visitor comes back to Computer
  await expect.poll(() => app.evaluate(() => window.__seastones.layer())).toBe("attract");
  await go(app, "computer");
  await expect.poll(() => brightness(lamps.nth(0))).toBeGreaterThan(0.9);
  // lamp 1 was lit before the drop and is dark now: no stale value came back
  for (let i = 0; i < 16; i++) expect(Math.abs((await brightness(lamps.nth(i))) - B[i]), `lamp ${i}`).toBeLessThanOrEqual(0.1);
  rig.clearOverrides();
});

test("a key held through a blip sounds again after the reconnect; one let go during it does not stick (INPUT-4)", async ({ app, rig }) => {
  await go(app, "play");
  const t = await touchSession(app);
  const [held] = await t.down([app.locator('#layer-play [data-key="12"]')]);
  const [gone] = await t.down([app.locator('#layer-play [data-key="16"]')]);
  await expect.poll(() => rig.touchBits).toBe((1n << 12n) | (1n << 16n));
  rig.accepting = false;
  rig.blip();
  await expect.poll(() => rig.touchBits, { timeout: 2000 }).toBe(0n); // rigd clears touch 250 ms after the page goes
  await t.up([gone]);
  rig.accepting = true;
  await expect.poll(() => app.evaluate(() => window.__seastones.live.connected), { timeout: 10000 }).toBe(true);
  await expect.poll(() => rig.touchBits, { timeout: 3000 }).toBe(1n << 12n);
  await t.up([held]);
  await expect.poll(() => rig.touchBits).toBe(0n);
});

test("protocol version mismatch: a named fault card, nothing drawn from rigd, and the dock disabled (KIOSK-4)", async ({ page }) => {
  const rig2 = new FakeEngine({ protocolVersion: 2 });
  await rig2.start(0);
  try {
    await page.goto(`${process.env.SX_WEB_URL}/?rig=${encodeURIComponent(rig2.url)}&hooks=1`);
    await expect(page.locator("#fault")).toBeVisible({ timeout: 5000 });
    await expect(page.locator("#fault-headline")).toHaveText("The computer is restarting.");
    await expect(page.locator("#fault-staff")).toContainText("rigd speaks protocol v2, this page v1");
    const live = await page.evaluate(() => ({ s: window.__seastones.live.state, h: window.__seastones.live.hello, m: window.__seastones.live.mismatch }));
    expect(live).toEqual({ s: null, h: null, m: 2 });
    await expect(page.locator("#dock")).toHaveClass(/disabled/);
    await expect(page.locator("#hdr-speed")).toHaveText("·");
  } finally {
    await rig2.stop();
  }
});

test("snapshot gaps lose nothing and a stale snapshot is never drawn (UI-34)", async ({ app, rig }) => {
  await go(app, "computer");
  await frames(app, 3);
  const seq0 = await app.evaluate(() => window.__seastones.live.state.seq);
  rig.dropStates(20);
  await frames(app, 3);
  const after = await app.evaluate(() => ({ seq: window.__seastones.live.state.seq, gaps: window.__seastones.live.gaps }));
  expect(after.seq).toBeGreaterThan(seq0 + 20);
  expect(after.gaps).toBeGreaterThanOrEqual(20);
  // a reordered, older snapshot with a different PC arrives: the page keeps the newer one
  rig.freeze(true);
  await frames(app, 2);
  const before = await app.evaluate(() => window.__seastones.live.state);
  rig.sendStale({ pc: 0x7ffe });
  await app.waitForTimeout(150);
  const now = await app.evaluate(() => window.__seastones.live.state);
  expect(now.pc).not.toBe(0x7ffe);
  expect(now.seq).toBeGreaterThanOrEqual(before.seq);
  rig.freeze(false);
});

test("kiosk keys never reach the browser: reload, zoom, history, find, print, devtools, fullscreen, select-all (KIOSK-1)", async ({ app }) => {
  await go(app, "play");
  const url = app.url();
  await app.evaluate(() => {
    window.__keys = [];
    window.addEventListener("keydown", (e) => window.__keys.push([e.key, e.ctrlKey || e.metaKey || e.altKey, e.defaultPrevented]));
  });
  const combos = ["F5", "Control+r", "Meta+r", "Control+Shift+r", "Control+w", "Control+t", "Control+n", "Control+p", "Control+s", "Control+f",
    "Control+a", "Control+Equal", "Control+Minus", "Control+0", "Alt+ArrowLeft", "Alt+ArrowRight", "Backspace", "F11", "F12",
    "Control+Shift+i", "Escape", "Meta+q", "Alt+F4", "Control+l", "F1", "ContextMenu", "PageDown", "Home"];
  for (const k of combos) await app.keyboard.press(k);
  const seen = await app.evaluate(() => window.__keys);
  const passed = seen.filter(([key, , prevented]) => !prevented && !["Control", "Meta", "Alt", "Shift"].includes(key));
  expect(passed).toEqual([]);
  expect(app.url()).toBe(url);
  expect(await app.evaluate(() => String(window.getSelection()))).toBe("");
  // plain keys still reach the page: the dev QWERTY keyboard plays (and is not blocked)
  await app.keyboard.down("a");
  await expect.poll(() => app.evaluate(() => window.__keys.at(-1))).toEqual(["a", false, false]);
  await app.keyboard.up("a");
});

test("no context menu, no selection, no file drop, no pinch or ctrl-wheel zoom (KIOSK-1, UI-23)", async ({ app }) => {
  await go(app, "story");
  const r = await app.evaluate(() => {
    const fire = (type, init = {}, Ctor = Event) => { const e = new Ctor(type, { bubbles: true, cancelable: true, ...init }); document.querySelector("#story-text, .text, body").dispatchEvent(e); return e.defaultPrevented; };
    return {
      contextmenu: fire("contextmenu", {}, MouseEvent),
      selectstart: fire("selectstart"),
      dragover: fire("dragover", {}, DragEvent),
      drop: fire("drop", {}, DragEvent),
      wheel: fire("wheel", { ctrlKey: true, deltaY: -100 }, WheelEvent),
      gesturestart: fire("gesturestart"),
      copy: fire("copy"),
      paste: fire("paste"),
      auxclick: fire("auxclick", { button: 1 }, MouseEvent),
      userSelect: getComputedStyle(document.querySelector("#story-text, .text") || document.body).userSelect,
      touchAction: getComputedStyle(document.body).touchAction,
      viewport: document.querySelector('meta[name="viewport"]').content,
    };
  });
  expect(r).toMatchObject({ contextmenu: true, selectstart: true, dragover: true, drop: true, wheel: true, gesturestart: true, copy: true, paste: true, auxclick: true, userSelect: "none", touchAction: "none" });
  expect(r.viewport).toContain("user-scalable=no");
  expect(r.viewport).toContain("maximum-scale=1");
  // a triple tap on story text selects nothing
  await app.locator(".text .body").first().click({ clickCount: 3 });
  expect(await app.evaluate(() => String(window.getSelection()))).toBe("");
});

test("every fault screen: each code's card, its staff line, the dock disabled, HOME and the footer live (KP-05)", async ({ app, rig }) => {
  const codes = ["program_stalled", "dsp_fault", "audio_device_missing", "audio_stalled", "image_missing", "image_hash_mismatch", "config_invalid", "engine_load_failed"];
  for (const code of codes) {
    await go(app, "play"); // each recovery starts the station over at attract
    rig.fault(code);
    await expect(app.locator("#fault")).toBeVisible();
    await expect(app.locator("#fault-staff")).not.toContainText("[faults/");
    await expect(app.locator("#fault-headline")).not.toHaveText("");
    await expect(app.locator("#dock")).toHaveClass(/disabled/);
    await expect(app.locator("#home")).toBeVisible();
    await expect(app.locator("#footer")).toContainText("A recreation in the spirit of Ned Lagin's 1974 rig.");
    rig.clearFault(code);
    await expect(app.locator("#fault")).toBeHidden();
  }
  // the two notice-only codes never raise a card
  for (const code of ["midi_absent", "ui_absent_muted"]) {
    rig.fault(code);
    await frames(app, 3);
    await expect(app.locator("#fault")).toBeHidden();
    rig.clearFault(code);
  }
});

test("holding STEP keeps the station awake, but only up to the held-key cap (QA-ADV-02b, NFR-10, PLAY-8)", async ({ app, rig }) => {
  test.setTimeout(60000);
  await go(app, "computer");
  await app.locator('#layer-computer .det[data-speed="step"]').tap();
  await expect.poll(() => rig.speed).toBe("step");
  // idle 6 s with a 3 s warning; a held STEP counts for 5 s at most
  await app.evaluate(() => window.__seastones.timings({ timeoutMs: 6000, warningMs: 3000, stepCapMs: 5000 }));
  const t = await touchSession(app);
  const n0 = rig.cpu.instructions;
  await t.down([app.locator("#step-computer")]);
  await app.waitForTimeout(4500); // past the warning point (3 s) with STEP held: no veil
  await expect(app.locator("#veil")).toBeHidden();
  expect(rig.cpu.instructions - n0).toBeGreaterThan(5); // it really was stepping
  // past the cap the held button is no longer a visitor at work: warning, then reset
  await expect(app.locator("#veil")).toBeVisible({ timeout: 6000 });
  await expect.poll(() => app.evaluate(() => window.__seastones.layer()), { timeout: 6000 }).toBe("attract");
  await t.up();
});
