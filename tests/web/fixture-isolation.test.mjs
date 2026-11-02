// node --test tests/web/fixture-isolation.test.mjs  (SP-S8A acceptance 2)
// Planted violations are generated in a temp dir at run time and never committed (QA-STRATEGY 13.4).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkIsolation } from './check-fixture-isolation.mjs';

const here = dirname(fileURLToPath(import.meta.url));

function planted(files) {
  const dir = mkdtempSync(join(tmpdir(), 'sx-isolation-'));
  for (const [name, body] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, name)), { recursive: true });
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

test('the real src/web has no fixture references', () => {
  const r = checkIsolation(resolve(here, '..', '..', 'src', 'web'));
  assert.deepEqual(r.violations, []);
});

test('a clean module passes', () => {
  const dir = planted({ 'app.js': "import { connect } from './rig.js';\nconnect();\n" });
  try { assert.equal(checkIsolation(dir).violations.length, 0); } finally { rmSync(dir, { recursive: true }); }
});

for (const [label, body] of [
  ['static import', "import { createSyntheticFeed } from '../../tests/web/fixtures/synthetic-feed.js';\n"],
  ['dynamic import', "const m = await import('./fixtures/synthetic-feed.js');\n"],
  ['script tag', '<script type="module" src="/tests/web/fixtures/synthetic-feed.js"></script>\n'],
  ['fetch of a fixture', "fetch('fixtures/state.json');\n"],
  ['generator call', 'const feed = createSyntheticFeed();\n'],
]) {
  test(`a planted ${label} is caught`, () => {
    const dir = planted({ 'panel.js': "export const x = 1;\n", 'sub/bad.html': body });
    try {
      const r = checkIsolation(dir);
      assert.ok(r.violations.length >= 1, `expected a violation for ${label}`);
      assert.match(r.violations[0].file, /bad\.html$/);
    } finally { rmSync(dir, { recursive: true }); }
  });
}

test('the fixture refuses to load from a src/web page', async () => {
  globalThis.location = { pathname: '/src/web/index.html' };
  try {
    await assert.rejects(import(`./fixtures/synthetic-feed.js?guard=${Date.now()}`), /must not load from src\/web/);
  } finally { delete globalThis.location; }
});

test('the synthetic feed is deterministic for a seed and labelled synthetic', async () => {
  const { createSyntheticFeed, SYNTHETIC } = await import('./fixtures/synthetic-feed.js');
  assert.equal(SYNTHETIC, true);
  const a = createSyntheticFeed({ seed: 7 }), b = createSyntheticFeed({ seed: 7 });
  for (let i = 0; i < 120; i++) { a.step(); b.step(); }
  assert.deepEqual([...a.state.dac], [...b.state.dac]);
  assert.deepEqual([...a.state.lamps], [...b.state.lamps]);
  assert.equal(a.state.synthetic, true);
});

test('measure.mjs summary counts dropped 60 Hz slots', async () => {
  const { summarize } = await import('./s8-render-budget/measure.mjs');
  const frames = [0, 16.7, 33.3, 66.7, 83.3, 133.3]; // one slot missed, then two
  const s = summarize(frames, [1, 1, 1, 1, 1, 1]);
  assert.equal(s.dropped_frames, 3);
  assert.equal(s.frames, 6);
});
