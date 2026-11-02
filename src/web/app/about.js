// about.js: the About page (CT-09; STORY-3, STORY-6, LEGAL-REVIEW 5 and 7).
//
// One tap from the footer on every layer, and from the staff screen. It shows the full
// 52-word disclosure first (the same words as Story 1, from captions/disclosure.md), then
// the credits, the notices and the privacy statement (captions/about.md). Every word comes
// from content; a missing card shows as a bracketed marker, never a guess.
//
// It is a sheet over the layers, not a layer: the dock, HOME and the footer stay live, the
// keyboard still plays under it, and HOME or the idle reset closes it.

import { el } from "./blocks.js";
import { S } from "./strings.js";
import * as content from "./content.js";
import { tap } from "./touch.js";

let sheet = null;

export function install(stage) {
  sheet = el("div", "about-page");
  sheet.id = "about-page";
  sheet.hidden = true;
  sheet.setAttribute("role", "dialog");
  sheet.setAttribute("aria-modal", "false");
  sheet.setAttribute("aria-labelledby", "about-heading");
  const card = el("div", "card about-card");
  const head = el("div", "about-head");
  const h = el("h2", null, S("about", "heading"));
  h.id = "about-heading";
  const close = el("button", "btn amber sm", S("about", "close"));
  close.type = "button";
  close.id = "about-close";
  tap(close, () => hide());
  head.append(h, close);
  card.appendChild(head);

  const disc = el("section", "about-sec about-disclosure");
  disc.id = "about-disclosure";
  disc.appendChild(el("h3", null, S("about", "disclosure-heading")));
  for (const p of content.captionBody("disclosure")) disc.appendChild(el("p", null, p));
  card.appendChild(disc);

  const grid = el("div", "about-grid");
  for (const k of ["credits", "notices", "privacy"]) {
    const sec = el("section", "about-sec");
    sec.id = `about-${k}`;
    sec.appendChild(el("h3", null, S("about", `${k}-heading`)));
    sec.appendChild(el("p", null, S("about", k)));
    grid.appendChild(sec);
  }
  card.appendChild(grid);
  sheet.appendChild(card);
  stage.appendChild(sheet);
}

export function show() { if (sheet) sheet.hidden = false; }
export function hide() { if (sheet) sheet.hidden = true; }
export const showing = () => !!sheet && !sheet.hidden;
