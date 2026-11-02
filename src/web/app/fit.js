// fit.js: keep a prose box inside its card when content reaches its word limit (UI-38, B-07).
//
// The design sizes (32 px story and note text) hold the shipped words with room to spare.
// A content editor may write up to the limit (70 words a story screen, 40 a block note), and
// Story 1 also carries the 52-word disclosure; then the text steps down a pixel at a time,
// never below `min` (24 px for body text, above the 22 px floor, NFR-11), until nothing is
// clipped. It runs only when the words change, never per frame.

/** Largest size in [min, max] at which `box` does not overflow; `apply(px)` sets it. */
export function fit(box, apply, max, min) {
  for (let px = max; px > min; px--) {
    apply(px);
    if (box.scrollHeight <= box.clientHeight + 1 && box.scrollWidth <= box.clientWidth + 1) return px;
  }
  apply(min);
  return min;
}

// Text metrics change when a web font finishes loading (the station serves its own fonts,
// and the first paint can come before them): every box that fits its words is refitted then.
const refits = new Set();
export function refitOnFonts(fn) {
  refits.add(fn);
  return fn;
}
if (typeof document !== "undefined" && document.fonts) {
  const all = () => { for (const f of refits) f(); };
  document.fonts.addEventListener("loadingdone", all);
  document.fonts.ready.then(all);
}
