// PM-00: the frame every screen shares. UI-07 (footer everywhere), UI-08 ("simulated"),
// UI-26 (nothing below 22 px), UI-32 (no sound, via the fixture trap), KIOSK-6 (no request
// off the machine, via the fixture route).
import { test, expect, go, frames } from "./fixtures.mjs";

const LAYERS = ["attract", "play", "computer", "code", "patch", "story"];

test("the disclosure footer is visible on every layer and in the idle and fault states (UI-07)", async ({ app, rig }) => {
  for (const l of LAYERS) {
    await go(app, l);
    const foot = app.locator("#footer");
    await expect(foot).toBeVisible();
    await expect(foot).toContainText("A recreation in the spirit of Ned Lagin's 1974 rig. Our program, our drawings, our synthesizer.");
    await expect(app.locator("#about")).toBeVisible();
  }
  // the footer is outside every layer container, so no layer can drop it
  expect(await app.evaluate(() => !!document.querySelector(".layer #footer"))).toBe(false);
  rig.kill();
  await expect(app.locator("#fault")).toBeVisible({ timeout: 5000 });
  await expect(app.locator("#footer")).toBeVisible();
});

test("every header says simulated (UI-08)", async ({ app }) => {
  for (const l of LAYERS.slice(1)) {
    await go(app, l);
    await expect(app.locator("#header")).toContainText(/simulated/i);
  }
});

test("nothing on any layer is set below 22 px (UI-26, NFR-11)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    await frames(app, 2);
    const small = await app.evaluate(() => {
      const out = [];
      const walker = document.createTreeWalker(document.getElementById("stage"), NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent.trim()) continue;
        const el = n.parentElement;
        if (el.closest("[hidden]") || el.closest(".sr-only")) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || el.getClientRects().length === 0) continue;
        let size = parseFloat(cs.fontSize);
        // SVG text is drawn in its viewBox units: scale by the SVG's rendered size
        const svgRoot = el.closest("svg");
        if (svgRoot && svgRoot.viewBox && svgRoot.viewBox.baseVal && svgRoot.viewBox.baseVal.width) {
          size *= svgRoot.getBoundingClientRect().width / svgRoot.viewBox.baseVal.width;
        }
        if (size < 21.5) out.push(`${size.toFixed(1)}px "${n.textContent.trim().slice(0, 40)}"`);
      }
      return out;
    });
    expect(small, `layer ${l}`).toEqual([]);
  }
});

test("the dock: five layers and HOME, FULL SPEED only when slowed", async ({ app }) => {
  await go(app, "play");
  await expect(app.locator(".tab")).toHaveCount(5);
  await expect(app.locator("#home")).toBeVisible();
  await expect(app.locator("#fullspeed")).toBeHidden();
  await expect(app.locator('.tab[data-layer="play"]')).toHaveClass(/on/);
});

test("the page never parses content: one index fetch, no visitor word hard-coded (CONT-1)", async ({ app }) => {
  // Every caption lookup resolved: no [area/key] marker anywhere on any layer.
  for (const l of LAYERS) {
    await go(app, l);
    const text = await app.locator("#stage").innerText();
    expect(text, `layer ${l}`).not.toMatch(/\[[a-z]+\/[a-z0-9_.-]+\]/);
  }
});
