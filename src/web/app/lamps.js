// lamps.js: lamp brightness from the engine's duty cycles (PR-06; UX 6.3, DESIGN-SYSTEM 4.2).
//
// A lamp is a duty cycle, not a snapshot: the engine reports, per frame, the fraction of
// executed instructions during which each bit was set. Brightness is that fraction,
// smoothed over about 80 ms so nothing strobes (NFR-10):
//
//   brightness = onePole(40 ms, mean of the last 4 reported fractions)
//
// The four-frame mean cancels any frame-to-frame alternation exactly (a lamp driven
// 0, 1, 0, 1 reads as a steady 0.5, UI-02), and the pole softens what is left. In CRAWL
// and STEP the engine reports exact 0 or 1 and the lamp shows it at once (UI-03).
//
// Brightness moves only when a `state` message arrives (update() is called from the state
// handler, never from a timer): frozen state means frozen lamps (UI-04, PLAY-3). There is
// no random source anywhere in this file or its callers.

const TAU_MS = 40;
const WINDOW = 4;

export class LampBank {
  constructor(n) {
    this.n = n;
    this.hist = Array.from({ length: n }, () => []);
    this.b = new Float32Array(n);
    this.lastFrames = null;
  }

  /** Feed one frame's fractions. `frames` is the engine's frame counter (48 kHz). */
  update(fractions, exact, frames) {
    let dt = 1000 / 60;
    if (this.lastFrames !== null && Number.isFinite(frames)) {
      dt = Math.min(100, Math.max(1, (frames - this.lastFrames) / 48));
    }
    this.lastFrames = frames;
    const a = 1 - Math.exp(-dt / TAU_MS);
    for (let i = 0; i < this.n; i++) {
      const f = Math.min(1, Math.max(0, Number(fractions[i]) || 0));
      const h = this.hist[i];
      if (exact) {
        h.length = 0;
        for (let k = 0; k < WINDOW; k++) h.push(f);
        this.b[i] = f;
        continue;
      }
      h.push(f);
      if (h.length > WINDOW) h.shift();
      const mean = h.reduce((s, x) => s + x, 0) / h.length;
      this.b[i] += a * (mean - this.b[i]);
    }
  }

  /** Forget everything (the link went down: no stale lamp may stay lit, KIOSK-4). */
  clear() {
    for (const h of this.hist) h.length = 0;
    this.b.fill(0);
    this.lastFrames = null;
  }
}

/** Write a brightness to a lamp element only when it changed by a visible amount. */
export function paint(el, value) {
  const v = Math.round(value * 100) / 100;
  if (el._b !== v) {
    el._b = v;
    el.style.setProperty("--b", String(v));
  }
}
