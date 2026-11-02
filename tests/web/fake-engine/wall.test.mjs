// wall.test.mjs: the patch wall from the engine's patch format (PM-10, PM-12, UI-25).
//
//   node --test tests/web/fake-engine/wall.test.mjs
//
// Every preset in content, on its own map's wall: it fits, its jacks are real touch targets,
// and every cable the engine format implies lands on a jack the wall has.
import test from "node:test";
import assert from "node:assert/strict";
import { layoutOf, jacksOf, cablesOf, evalIndex, fill, reachesOut } from "../../../src/web/app/wallmodel.js";
import { layout, W, H } from "../../../src/web/app/patchwall.js";
import { REGISTRY, loadPresets } from "./engine.mjs";
import { validate } from "./schema.mjs";

test("every preset in content lays out on its wall: no overflow, jacks inside, 54 px targets 8 px apart (A-06), cables on real jacks", () => {
  const presets = loadPresets();
  assert.ok(Object.keys(presets).length >= 10, "the engine lane's ten presets");
  for (const [slug, doc] of Object.entries(presets)) {
    const desc = layoutOf(doc, REGISTRY);
    assert.deepEqual(validate("server", { v: 1, t: "patch", cables: [], reaches_out: false, preset: null, layout: desc }), [], slug);
    const lay = layout([], desc);
    assert.equal(lay.overflow, false, `${slug} overflows the wall`);
    for (const j of lay.jacks) assert.ok(j.x >= 34 && j.x <= W - 34 && j.y >= 34 && j.y <= H - 34, `${slug} ${j.id} at ${j.x},${j.y}`);
    for (let a = 0; a < lay.jacks.length; a++) {
      for (let b = a + 1; b < lay.jacks.length; b++) {
        const d = Math.hypot(lay.jacks[a].x - lay.jacks[b].x, lay.jacks[a].y - lay.jacks[b].y);
        assert.ok(d >= 62, `${slug}: ${lay.jacks[a].id} and ${lay.jacks[b].id} ${d.toFixed(0)} px apart (54 px targets need 62 for an 8 px gap)`);
      }
    }
    const ids = new Set(jacksOf(desc).map((j) => j.id));
    const cables = cablesOf(doc, desc);
    for (const c of cables) assert.ok(ids.has(c.from) && ids.has(c.to), `${slug}: ${c.from} -> ${c.to}`);
    assert.ok(reachesOut(cables, desc), `${slug} reaches the speaker`);
  }
});

test("a voice card per voice; wildcard ports become card jacks; the gate column only on a latch map", () => {
  const presets = loadPresets();
  const big = layoutOf(presets["big-steps"], REGISTRY);
  assert.equal(big.voices.count, 4);
  assert.deepEqual(big.voices.ports.map((p) => p.id), ["flt-cutoff", "osc-mod"]);
  assert.equal(big.rail.gates, false);
  const eight = layoutOf(presets["eight-voices"], REGISTRY);
  assert.equal(eight.voices.count, 8);
  assert.equal(eight.rail.gates, true);
  assert.ok(jacksOf(eight).some((j) => j.id === "gate.7"));
  assert.ok(!jacksOf(big).some((j) => j.id.startsWith("gate.")));
});

test("wallmodel's {i} arithmetic is sxpatch's: whole numbers, / rounds down, % never negative, nothing else", () => {
  assert.equal(fill("mix{i%2}.in{i/2+1}", 3), "mix1.in2");
  assert.equal(fill("dac.{i+4}", 2), "dac.6");
  assert.equal(evalIndex("(i+1)*2", 3), 8);
  assert.equal(evalIndex("i-5", 2), -3);
  assert.equal(evalIndex("(i-5)/2", 2), -2, "Python // rounds towards minus infinity");
  assert.throws(() => evalIndex("i+x", 1));
  assert.throws(() => evalIndex("process.exit()", 1));
});
