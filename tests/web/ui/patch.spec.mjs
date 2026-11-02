// PM-10, PM-11, PM-12, PM-13, PM-15: the patch panel. UI-18 (drag and tap make the same
// messages), UI-20 (silence hint, PUT IT BACK), UI-21 (voice cards, our channel map), UI-25.
import { test, expect, go, frames, open } from "./fixtures.mjs";
import { FakeEngine } from "../fake-engine/engine.mjs";
import { touchSession } from "./touch.mjs";

const jack = (page, id) => page.locator(`#wall .jackhit[data-jack="${id}"]`);
const has = (rig, a, b) => rig.cables.some((c) => (c.from === a && c.to === b) || (c.from === b && c.to === a));

async function centre(loc) {
  const b = await loc.boundingBox();
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}

test("a drag makes a connection and the engine confirms it; dropping a plug in empty space breaks it (UI-18, PATCH-1)", async ({ app, rig }) => {
  await go(app, "patch");
  expect(has(rig, "lfo.tri", "echo.time")).toBe(false);
  const t = await touchSession(app);
  const a = await centre(jack(app, "lfo.tri"));
  const b = await centre(jack(app, "echo.time"));
  const [id] = await t.down([a]);
  for (let i = 1; i <= 10; i++) await t.move(id, a.x + ((b.x - a.x) * i) / 10, a.y + ((b.y - a.y) * i) / 10);
  await t.up([id]);
  await expect.poll(() => has(rig, "lfo.tri", "echo.time")).toBe(true);
  expect(rig.messages("patch.connect").pop()).toMatchObject({ from: "lfo.tri", to: "echo.time" });
  await app.waitForFunction(() => window.__seastones.live.patch.cables.some((c) => c.to === "echo.time"));
  // pick that plug up again and drop it on empty panel: the cable is pulled out
  const [id2] = await t.down([b]);
  for (let i = 1; i <= 6; i++) await t.move(id2, b.x - 20 * i, b.y + 30 * i);
  await t.up([id2]);
  await expect.poll(() => has(rig, "lfo.tri", "echo.time")).toBe(false);
});

test("moving a plug from one jack to another rewires it in one gesture (UX 6.1)", async ({ app, rig }) => {
  await go(app, "patch");
  expect(has(rig, "lfo.sine", "v1.flt-cutoff")).toBe(true);
  const t = await touchSession(app);
  const a = await centre(jack(app, "v1.flt-cutoff"));
  const b = await centre(jack(app, "echo.time"));
  const [id] = await t.down([a]);
  for (let i = 1; i <= 8; i++) await t.move(id, a.x + ((b.x - a.x) * i) / 8, a.y + ((b.y - a.y) * i) / 8);
  await t.up([id]);
  await expect.poll(() => has(rig, "lfo.sine", "echo.time")).toBe(true);
  expect(has(rig, "lfo.sine", "v1.flt-cutoff")).toBe(false);
});

test("every patch operation works with taps only: tap, tap to join; tap a plug, then Remove (UI-18, PM-11, WCAG 2.5.7)", async ({ app, rig }) => {
  await go(app, "patch");
  await jack(app, "lfo.tri").tap();
  await expect(jack(app, "lfo.tri")).toHaveClass(/sel/);
  await jack(app, "echo.time").tap();
  await expect.poll(() => rig.cables.filter((c) => c.from === "lfo.tri").length).toBe(1);
  expect(has(rig, "lfo.tri", "echo.time")).toBe(true);
  await jack(app, "lfo.tri").tap();
  await expect(app.locator("#remove-bubble")).toBeVisible();
  await app.locator("#remove-bubble").click();
  await expect.poll(() => has(rig, "lfo.tri", "echo.time")).toBe(false);
  // the tap path sends the same messages as the drag path
  const types = rig.messages().map((m) => m.t).filter((t) => t.startsWith("patch."));
  expect(types).toEqual(["patch.connect", "patch.disconnect"]);
});

test("remove every cable: the hint appears within 2 s of the next key; PUT IT BACK restores sound in one tap (UI-20, PATCH-4)", async ({ app, rig }) => {
  await go(app, "patch");
  // pull them all through the UI's own path: tap each plug, then Remove
  while (rig.cables.length) {
    const c = rig.cables[0];
    await jack(app, c.to).tap();
    await app.locator("#remove-bubble").click();
    await expect.poll(() => rig.cables.some((x) => x === c)).toBe(false);
  }
  const hint = app.locator("#silence-hint");
  await expect(hint).toBeHidden();
  const t0 = Date.now();
  await app.keyboard.down("a");
  await expect(hint).toBeVisible({ timeout: 2000 });
  expect(Date.now() - t0).toBeLessThan(2000);
  await app.keyboard.up("a");
  await app.locator("#putback-patch").tap();
  await expect(hint).toBeHidden();
  expect(rig.preset).toBe("stadium-drone");
  expect(rig.patchMsg().reaches_out).toBe(true);
});

test("the wall has one voice card per voice of the four-voice wall, and says the channel map is our choice (UI-21, PATCH-2, PATCH-7)", async ({ app }) => {
  await go(app, "patch");
  for (let v = 1; v <= 4; v++) await expect(jack(app, `v${v}.pitch`)).toHaveCount(1);
  await expect(jack(app, "v5.pitch")).toHaveCount(0);
  const svg = await app.locator("#wall").innerHTML();
  expect(svg).toContain("Channel map: our choice.");
  // rail names come from content/rig/channel-map.md (the all-da-4 map: gates on D/A 4-7)
  expect(svg).toContain("Pitch 1");
  expect(svg).toContain("Gate 4");
  expect(svg).toContain("Cutoff");
  expect(svg).not.toContain(">GATES<"); // no gate-latch column on an all-D/A map
  // the plates are the Stadium drone patch's own modules
  for (const t of ["VOICE 1", "VOICE 4", "LFO", "MIXER 1", "MIXER 2", "ECHO SEND", "ECHO", "LEFT", "RIGHT", "OUTPUT"]) expect(svg).toContain(`>${t}<`);
  expect(svg).not.toMatch(/E-?mu|ARP|Buchla|Moog/i);
  expect(svg).not.toMatch(/<image\b/);
});

test("the eight-voice map: one card per voice, eight of them, and every jack still a real touch target (PM-12 AC 1, UI-21)", async ({ page }) => {
  const rig8 = new FakeEngine({ voices: 8 });
  await rig8.start(0);
  try {
    await open(page, rig8);
    await go(page, "patch");
    for (let v = 1; v <= 8; v++) await expect(jack(page, `v${v}.out`)).toHaveCount(1);
    await expect(jack(page, "v9.out")).toHaveCount(0);
    const svg = await page.locator("#wall").innerHTML();
    for (let v = 1; v <= 8; v++) expect(svg).toContain(`VOICE ${v}`);
    expect(svg).toContain("Pitch 8"); // the rail's names still come from content
    const boxes = await page.locator("#wall .jackhit").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, e.dataset.jack]; }));
    // the same rule as the four-voice wall: every hit area 54 px, 8 px apart (A-06)
    const close = [];
    for (let i = 0; i < boxes.length; i++) {
      expect(Math.min(boxes[i][2], boxes[i][3])).toBeGreaterThanOrEqual(54);
      for (let j = i + 1; j < boxes.length; j++) {
        if (Math.hypot(boxes[i][0] - boxes[j][0], boxes[i][1] - boxes[j][1]) < 62) close.push(`${boxes[i][4]} / ${boxes[j][4]}`);
      }
    }
    expect(close).toEqual([]);
    expect(svg).toContain(">GATES<"); // the gate-latch column: this map's gates are latch lines
    // a voice-8 cable is a real one: pull it out through the UI
    const out8 = () => rig8.cables.some((c) => c.from === "v8.out" || c.to === "v8.out");
    expect(out8()).toBe(true);
    await jack(page, "v8.out").tap();
    await page.locator("#remove-bubble").click();
    await expect.poll(out8).toBe(false);
  } finally {
    await rig8.stop();
  }
});

test("jack touch targets are at least 54 px and 8 px apart (UI-25, PM-11, A-06)", async ({ app }) => {
  await go(app, "patch");
  const boxes = await app.locator("#wall .jackhit").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height, e.dataset.jack]; }));
  for (const [, , w, h, id] of boxes) {
    expect(w, id).toBeGreaterThanOrEqual(54);
    expect(h, id).toBeGreaterThanOrEqual(54);
  }
  // UX A-06: targets separated by at least 8 px (the hit boxes themselves, edge to edge)
  const gaps = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const [ax, ay, aw, ah] = boxes[i], [bx, by, bw, bh] = boxes[j];
      const gx = Math.max(0, Math.max(ax, bx) - Math.min(ax + aw, bx + bw));
      const gy = Math.max(0, Math.max(ay, by) - Math.min(ay + ah, by + bh));
      if (Math.max(gx, gy) < 7.5) gaps.push(`${boxes[i][4]} / ${boxes[j][4]}`);
    }
  }
  expect(gaps).toEqual([]);
});

test("a preset relays the cables and the chip on Patch follows the engine (PM-15)", async ({ app, rig }) => {
  await go(app, "patch");
  await app.locator('#layer-patch .chip[data-preset="sweep"]').tap();
  await expect(app.locator('#layer-patch .chip[data-preset="sweep"]')).toHaveClass(/on/);
  expect(has(rig, "lfo.tri", "v1.flt-cutoff")).toBe(true);
  await frames(app, 2);
});
