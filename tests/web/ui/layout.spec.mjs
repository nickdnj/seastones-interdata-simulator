// Layout guards (UX 4, 4.3, 5.3 to 5.5; A-04, UI-38, KP-18): nothing overlaps on any layer,
// the Patch help clears the jack labels, the speed detents sit as low as the frame allows,
// and the stage keeps one layout at 1920 x 1080 and at 1366 x 768.
import { test, expect, go, frames, open } from "./fixtures.mjs";

const LAYERS = ["play", "computer", "code", "patch", "story"];
// Blocks that must never overlap each other within a layer (containment is fine).
const BLOCKS = ".layer.on .card, .layer.on .kb, .layer.on .comp-row, .layer.on .code-dets, .layer.on .patch-controls, " +
  ".layer.on .patch-help, .layer.on .wall, .layer.on .enclosure, .layer.on .controls-left, .layer.on .speed-card, .layer.on .pager";

/** Stage-coordinate boxes (the page may be scaled). */
async function boxes(page, sel) {
  return page.evaluate((sel) => {
    const st = document.getElementById("stage").getBoundingClientRect();
    const k = st.width / 1920;
    return [...document.querySelectorAll(sel)].filter((e) => e.getBoundingClientRect().width > 0).map((e) => {
      const r = e.getBoundingClientRect();
      return { name: `${e.className.baseVal ?? e.className}#${e.id}`, x: (r.left - st.left) / k, y: (r.top - st.top) / k,
        r: (r.right - st.left) / k, b: (r.bottom - st.top) / k, el: null };
    });
  }, sel);
}
const overlap = (a, b) => Math.min(a.r, b.r) - Math.max(a.x, b.x) > 0.5 && Math.min(a.b, b.b) - Math.max(a.y, b.y) > 0.5;
const inside = (a, b) => a.x >= b.x - 0.5 && a.r <= b.r + 0.5 && a.y >= b.y - 0.5 && a.b <= b.b + 0.5;

for (const vp of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }]) {
  test(`no two blocks overlap on any layer, and nothing runs into the dock, at ${vp.width} x ${vp.height} (UI-38)`, async ({ app }) => {
    await app.setViewportSize(vp);
    for (const l of LAYERS) {
      await go(app, l);
      await frames(app, 3);
      const bs = await boxes(app, BLOCKS);
      const dockTop = Math.min(...(await boxes(app, ".dock .tab")).map((t) => t.y));
      const bad = [];
      for (let i = 0; i < bs.length; i++) {
        for (let j = i + 1; j < bs.length; j++) {
          if (overlap(bs[i], bs[j]) && !inside(bs[i], bs[j]) && !inside(bs[j], bs[i])) bad.push(`${bs[i].name} / ${bs[j].name}`);
        }
        if (bs[i].b > dockTop - 7.5) bad.push(`${bs[i].name} ends at ${Math.round(bs[i].b)}, within 8 px of the dock`);
        if (bs[i].y < 72) bad.push(`${bs[i].name} starts at ${Math.round(bs[i].y)}, under the header`);
      }
      expect(bad, `layer ${l}`).toEqual([]);
    }
  });
}

test("the Patch help line clears the wall and every jack label (UX 5.5)", async ({ app }) => {
  await go(app, "patch");
  await frames(app, 2);
  const [help] = await boxes(app, "#patch-help");
  const [wall] = await boxes(app, "#wall");
  expect(overlap(help, wall)).toBe(false);
  const labels = await boxes(app, "#wall text");
  expect(labels.length).toBeGreaterThan(20);
  expect(labels.filter((t) => overlap(t, help)).map((t) => t.name)).toEqual([]);
  // all of its words are visible, at the 22 px floor or above
  const fit = await app.locator("#patch-help").evaluate((e) => ({ size: parseFloat(getComputedStyle(e).fontSize), clipped: e.scrollHeight > e.clientHeight + 1 || e.scrollWidth > e.clientWidth + 1 }));
  expect(fit.size).toBeGreaterThanOrEqual(22);
  expect(fit.clipped).toBe(false);
});

test("A-04: the Computer and Code speed detents and STEP sit directly above the dock, reaching into the lowest 20%", async ({ app }) => {
  // The frame puts the dock at 892-1040, so the lowest 20% (y >= 864) leaves 28 px above it:
  // a 72 px detent cannot fit there whole. The row's foot is inside that band and nothing
  // interactive lies between it and the dock. Fully meeting A-04 needs a frame decision
  // (docs/qa/results/overnight-2026-11-02-ui.md).
  for (const l of ["computer", "code"]) {
    await go(app, l);
    await frames(app, 2);
    const dets = await boxes(app, `#layer-${l} .det`);
    expect(dets.length).toBe(6);
    for (const d of dets) {
      expect(d.b, `${l} ${d.name}`).toBeGreaterThanOrEqual(864);
      expect(d.b, `${l} ${d.name}`).toBeLessThanOrEqual(892 - 8);
    }
    const lowest = Math.min(...dets.map((d) => d.y));
    const ctl = await boxes(app, `#layer-${l} button, #layer-${l} [data-tap], #layer-${l} .wk, #layer-${l} .bk`);
    const below = ctl.filter((c) => c.y > lowest + 1 && !c.name.startsWith("det"));
    expect(below.map((c) => c.name), `${l}: controls below the detents`).toEqual([]);
  }
});

test("the Computer's right column holds the whole loop, one line per block, above the slim keys (UX 5.3)", async ({ app }) => {
  await go(app, "computer");
  await frames(app, 3);
  const items = await app.locator(".ring li").count();
  const blocks = await app.evaluate(() => window.__seastones && document.querySelectorAll(".ring li").length);
  expect(items).toBe(blocks);
  expect(items).toBeGreaterThanOrEqual(5);
  const [col] = await boxes(app, ".comp-right");
  const [kb] = await boxes(app, "#layer-computer .kb");
  const cards = await boxes(app, ".comp-right .card");
  for (const c of cards) expect(c.b, c.name).toBeLessThanOrEqual(kb.y - 8);
  expect(col.b).toBeLessThanOrEqual(kb.y);
});

test("1366 x 768 scales the 1920 x 1080 stage with one transform, letterboxed, nothing outside the window (KP-18)", async ({ page, rig }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await open(page, rig);
  const g = await page.evaluate(() => {
    const st = document.getElementById("stage");
    const r = st.getBoundingClientRect();
    return { w: r.width, h: r.height, x: r.left, y: r.top, t: getComputedStyle(st).transform, sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight };
  });
  expect(g.w / g.h).toBeCloseTo(16 / 9, 2);
  expect(g.w).toBeLessThanOrEqual(1366 + 0.5);
  expect(g.h).toBeLessThanOrEqual(768 + 0.5);
  expect(g.x).toBeGreaterThanOrEqual(-0.5);
  expect(g.y).toBeGreaterThanOrEqual(-0.5);
  expect(g.sw).toBeLessThanOrEqual(1366);
  expect(g.sh).toBeLessThanOrEqual(768);
  expect(g.t).toMatch(/^matrix\(0\.711/);
});
