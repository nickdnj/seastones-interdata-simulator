// SYNTHETIC STATE GENERATOR: TEST FIXTURE ONLY. NEVER SHIPPED. (SP-S8A, NFR-9, DES-2)
//
// Produces a fake rig state at 60 Hz for the S-8 render-budget page: 24 panel lamps, 16 D/A
// values, 16 gates, 8 voices and a scope trace. None of it comes from the emulated machine, so
// by the no-demo-fallback rule (KIOSK-4, DEV-PLAN 7.1) it must never be reachable from
// src/web/. tests/web/fixture-isolation.test.mjs enforces that statically; the guard below
// refuses to run if a page under /src/web/ ever loads it.
//
// Deterministic: a seeded xorshift32, so two runs draw the same frames (QA-STRATEGY 13 item 1).

if (typeof location !== 'undefined' && /\/src\/web\//.test(location.pathname)) {
  throw new Error('synthetic-feed.js is a test fixture and must not load from src/web/');
}

export const SYNTHETIC = true;

function xorshift32(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
}

export function createSyntheticFeed({ voices = 8, seed = 1974, rateHz = 60 } = {}) {
  const rnd = xorshift32(seed);
  const state = {
    synthetic: true,
    tick: 0,
    lamps: new Uint8Array(24),
    dac: new Uint16Array(16),
    gates: new Uint8Array(16),
    voices: Array.from({ length: voices }, (_, i) => ({ key: -1, age: 0, channel: i })),
    scope: new Float32Array(256),
  };
  let phase = 0;
  function step() {
    state.tick++;
    // lamps: a program-counter-like address walk plus status bits
    const pc = (state.tick * 37 + Math.floor(rnd() * 8)) & 0xffff;
    for (let b = 0; b < 16; b++) state.lamps[b] = (pc >> b) & 1;
    for (let b = 16; b < 24; b++) state.lamps[b] = rnd() < 0.3 ? 1 : 0;
    // voices: random note-ons and releases, at most `voices` held
    for (const v of state.voices) {
      if (v.key < 0 && rnd() < 0.05) { v.key = Math.floor(rnd() * 37); v.age = 0; }
      else if (v.key >= 0 && rnd() < 0.02) v.key = -1;
      else v.age++;
    }
    // D/A: two channels per voice (pitch, filter) plus slow sweeps on the rest
    for (let c = 0; c < 16; c++) {
      const v = state.voices[c % voices];
      const target = v.key >= 0 ? (v.key * 1771 + (c >= 8 ? (state.tick * 97) & 0x3ff : 0)) & 0xffff : 0;
      state.dac[c] = (state.dac[c] + ((target - state.dac[c]) >> 2)) & 0xffff;
      state.gates[c] = c < voices && state.voices[c].key >= 0 ? 1 : 0;
    }
    // scope: a sum of the held voices' "pitches" (purely visual)
    phase += 0.05;
    for (let i = 0; i < state.scope.length; i++) {
      let s = 0;
      for (const v of state.voices) if (v.key >= 0) s += Math.sin((i * (1 + v.key / 12)) * 0.12 + phase);
      state.scope[i] = s / voices;
    }
    return state;
  }
  return { state, step, rateHz };
}
