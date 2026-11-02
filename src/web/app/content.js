// content.js: the page's only door to content (CT-01, CONT-1, CONT-6).
//
// The page fetches /content/index.json once at boot (built by src/content/tool, the only
// content parser) and never parses a content file. Rules this module keeps:
//   1. An item's `staff` block (claim, note, ledger) is never handed to a renderer.
//   2. A broken item stays in its place as an error card (`error_card: true`); the rest
//      of the station carries on.
//   3. No demo fallback: if the index cannot be read, `ok()` is false and the page shows
//      its content-down state. There is no built-in copy of the words.
//   4. Draft-hidden items appear only in review mode (CT-07), each with its draft stamp.

const INDEX_URL = "/content/index.json";

let doc = null;
let failure = null;
let review = false;

export async function load(url = INDEX_URL) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`index.json: HTTP ${res.status}`);
    const parsed = await res.json();
    if (!parsed || parsed.schema !== "seastones.content-index/1" || !parsed.collections) {
      throw new Error("index.json is not a seastones content index");
    }
    doc = parsed;
    failure = null;
  } catch (err) {
    doc = null;
    failure = String(err && err.message ? err.message : err);
  }
  return ok();
}

export const ok = () => doc !== null;
export const failureReason = () => failure;
export const reviewMode = () => review;
const reviewListeners = new Set();
/** Review mode (CT-07). Listeners hear every change at once, visible or not. */
export function setReviewMode(on) {
  const was = review;
  review = !!on;
  if (was !== review) for (const fn of reviewListeners) fn(review);
}
export function onReviewChange(fn) { reviewListeners.add(fn); return () => reviewListeners.delete(fn); }

/** kiosk.conf tunables (private keys are already stripped by the indexer). */
export function conf(key, fallback) {
  const v = doc && doc.conf ? doc.conf[key] : undefined;
  return v === undefined || v === null || v === "" ? fallback : v;
}
export function confNumber(key, fallback) {
  const n = Number(conf(key, NaN));
  return Number.isFinite(n) ? n : fallback;
}
export function confFlag(key, fallback) {
  const v = String(conf(key, "")).trim().toLowerCase();
  if (!v) return fallback;
  return ["yes", "on", "true", "1"].includes(v);
}
export function confList(key) {
  return String(conf(key, "")).split(",").map((s) => s.trim()).filter(Boolean);
}

function strip(entry) {
  if (!entry) return null;
  const { staff, ...visitor } = entry; // eslint-disable-line no-unused-vars
  return visitor;
}

/** Items of a collection in visitor order (or review order in review mode). */
export function items(collection) {
  if (!doc) return [];
  const list = (review ? doc.review_order : doc.order)[collection] || [];
  const all = doc.collections[collection] || [];
  return list.map((slug) => strip(all.find((e) => e.slug === slug))).filter(Boolean);
}

export function item(collection, slug) {
  if (!doc) return null;
  const e = (doc.collections[collection] || []).find((x) => x.slug === slug);
  if (!e) return null;
  if (e.hidden && !review && !e.error_card) return null;
  return strip(e);
}

/** A slot's public fields (id, status, kind, claim, tags). */
export function slot(id) {
  return doc && doc.slots ? doc.slots[id] || null : null;
}

/** Does this item name a slot that is not confirmed? Then it is a draft, never shipped. */
export function notShippable(entry) {
  return (entry.slots || []).some((id) => {
    const s = slot(id);
    return !s || s.claim !== "confirmed" || s.status !== "ready";
  });
}

/** One string from a captions file: the card named `key` (CONT-1). */
export function caption(area, key, field = "text") {
  const c = doc && (doc.collections.captions || []).find((e) => e.slug === area);
  if (!c || c.error_card) return null;
  for (const b of c.blocks || []) {
    if (b.type !== "cards") continue;
    const hit = b.items.find((i) => i.title === key);
    if (hit) return hit[field] ?? null;
  }
  return null;
}

/** A caption file's body paragraphs (the disclosure). */
export function captionBody(area) {
  const c = doc && (doc.collections.captions || []).find((e) => e.slug === area);
  if (!c) return [];
  return (c.blocks || []).filter((b) => b.type === "paragraph").map((b) => b.text);
}

/** Table rows of a rig file, as objects keyed by the header row. */
export function rigTable(slug) {
  const r = doc && (doc.collections.rig || []).find((e) => e.slug === slug);
  const t = r && (r.blocks || []).find((b) => b.type === "table");
  if (!t) return [];
  return t.rows.map((row) => Object.fromEntries(t.headers.map((h, i) => [h.toLowerCase(), row[i]])));
}

/** Staff-facing: every problem the indexer found. Only the staff screen may call this. */
export function problems() {
  return doc && Array.isArray(doc.problems) ? doc.problems : [];
}
