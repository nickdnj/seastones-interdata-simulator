// strings.js: visitor words, looked up in content (CONT-1).
//
// Every sentence a visitor reads comes from content/captions/*.md through content.js. A
// string that is missing shows as a visible bracketed marker, never as a guess, so a
// content mistake is seen and fixed rather than papered over (the UI tests fail on any
// marker in the shipped content).
//
// The only words written here are the last resort for when the content index itself cannot
// be read (no content means no captions to look up). They say what is wrong and nothing else.

import * as content from "./content.js";

export const CONTENT_DOWN = {
  headline: "This exhibit's words did not load.",
  body: "Please tell a staff member. Nothing here is broken that a restart will not fix.",
  staff: "STAFF · /content/index.json could not be read · runbook p.4",
};

export const MISSING = (area, key) => `[${area}/${key}]`;

/** The text of card `key` in captions/`area`.md, with {name} filled from `vars`. */
export function S(area, key, vars) {
  let t = content.caption(area, key, "text");
  if (t === null || t === undefined) return MISSING(area, key);
  if (vars) t = t.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
  return t;
}

/** The `meta` line of a card (second line: captions, sub-labels). */
export function M(area, key) {
  const t = content.caption(area, key, "meta");
  return t === null || t === undefined ? MISSING(area, `${key}.meta`) : t;
}
