// Patch wall against the real rigd (QA-ADV-01).
import { test, expect, touch, go } from "./real.mjs";

const jackCentre = (page, id) => page.evaluate((j) => {
  const r = document.querySelector(`.jackhit[data-jack="${j}"]`).getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
}, id);

async function drag(page, a, b) {
  await touch(page, "touchStart", [{ x: a.x, y: a.y, id: 1 }]);
  for (let i = 1; i <= 10; i++) await touch(page, "touchMove", [{ x: a.x + ((b.x - a.x) * i) / 10, y: a.y + ((b.y - a.y) * i) / 10, id: 1 }]);
  await touch(page, "touchEnd", []);
}

// QA-ADV-01 (fixed in this branch, patch.js): moving a plugged cable's end onto a jack rigd
// refuses (output to output) pulled the cable out first and never put it back. The toast said
// "That cable did not take. Try another jack." and the cable was gone from the wall and the
// engine. A refused move must leave the patch as it was.
test("QA-ADV-01: a refused cable move leaves the original cable in place", async ({ app: page }) => {
  await go(page, "patch");
  await page.waitForTimeout(500);
  const before = await page.evaluate(() => window.__seastones.live.patch.cables);
  const c = before.find((x) => x.from === "dac.0" && x.to === "v1.pitch");
  expect(c, "Stadium drone has dac.0 -> v1.pitch").toBeTruthy();
  // drag the v1.pitch end onto dac.4, another OUTPUT: rigd refuses output-to-output
  await drag(page, await jackCentre(page, "v1.pitch"), await jackCentre(page, "dac.4"));
  await expect(page.locator("#toast")).toHaveText(/did not take/);
  await page.waitForTimeout(600);
  const after = await page.evaluate(() => window.__seastones.live.patch.cables);
  expect(after.some((x) => x.from === "dac.0" && x.to === "v1.pitch"), "the cable the visitor moved").toBe(true);
  expect(after.length).toBe(before.length);
});
