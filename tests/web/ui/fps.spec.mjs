// Frame rate of the real page on each layer, headless, against the fake engine at 60 Hz
// state (NFR-9, DES-2 smoke). Patch is measured with a cable being dragged and 16 cables
// drawn. This is a laptop smoke figure only: UI-42 / S-8b on the station box is the real one.
// Writes docs/qa/results/ui/fps.json only when SX_UI_SHOTS=1.
import { test, expect, go } from "./fixtures.mjs";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { touchSession } from "./touch.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

async function measure(page, ms = 2000) {
  return page.evaluate((dur) => new Promise((resolve) => {
    const t = [];
    const t0 = performance.now();
    const step = (now) => { t.push(now); if (now - t0 < dur) requestAnimationFrame(step); else {
      const d = t.slice(1).map((x, i) => x - t[i]).sort((a, b) => a - b);
      resolve({ fps: Math.round(((t.length - 1) * 1000) / (t[t.length - 1] - t[0])), p95_ms: Math.round(d[Math.floor(d.length * 0.95)] * 10) / 10 });
    } };
    requestAnimationFrame(step);
  }), ms);
}

test("each layer holds at least 50 fps headless with live state (NFR-9 smoke)", async ({ app }) => {
  const out = {};
  for (const l of ["attract", "play", "computer", "code", "story"]) {
    await go(app, l);
    await app.keyboard.down("a");
    await app.waitForTimeout(400);
    out[l] = await measure(app);
    await app.keyboard.up("a");
  }
  await go(app, "patch");
  const t = await touchSession(app);
  const b = await app.locator('#wall .jackhit[data-jack="lfo.tri"]').boundingBox();
  const [id] = await t.down([{ x: b.x + 34, y: b.y + 34 }]);
  const run = measure(app);
  for (let i = 0; i < 60; i++) { await t.move(id, b.x + 34 - i * 6, b.y + 34 + i * 3); await app.waitForTimeout(25); }
  out.patch_dragging = await run;
  await t.up();
  console.log(JSON.stringify(out));
  if (process.env.SX_UI_SHOTS) writeFileSync(path.join(ROOT, "docs/qa/results/ui/fps.json"), JSON.stringify({ note: "headless Chromium on the dev Mac, fake engine at 60 Hz; smoke only, UI-42 on the station is the measurement", ...out }, null, 2) + "\n");
  for (const [l, r] of Object.entries(out)) expect(r.fps, l).toBeGreaterThanOrEqual(50);
});
