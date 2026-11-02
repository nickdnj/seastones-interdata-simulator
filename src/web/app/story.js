// story.js: layer 5, The Story, and the disclosure (CT-09; STORY-1, STORY-2, STORY-3, STORY-5).
//
// Screens come from content/screens/ in visitor order (only `ready` ones). A screen that
// names the `disclosure` slot carries the full disclosure card; the footer's "About this
// recreation" opens it in one tap from any layer (STORY-3). A broken screen is a calm card
// in its place and the others carry on (CONT-6). In review mode (CT-07) the draft-hidden
// screens appear too, each stamped "Draft · not shippable" because they make claims that
// are not at Tier 1 (STORY-2). The keyboard plays throughout; there is no auto-advance.

import { el, esc } from "./blocks.js";
import { S } from "./strings.js";
import { fit, refitOnFonts } from "./fit.js";
import * as content from "./content.js";
import { tap } from "./touch.js";
import { ART, VIEW } from "./story-art.js";

const SEAL = (text) => {
  const t = esc(text.toUpperCase());
  return `<svg width="140" height="140" viewBox="0 0 160 160" aria-hidden="true" style="flex:none"><defs><path id="seal-c" d="M80 80 m-58 0 a58 58 0 1 1 116 0 a58 58 0 1 1 -116 0"/></defs>` +
    `<circle cx="80" cy="80" r="77" fill="none" stroke="#F2A83B" stroke-width="3"/><circle cx="80" cy="80" r="40" fill="#2B1B33" stroke="#F2A83B" stroke-width="2"/>` +
    `<text font-family="Oswald, Arial Narrow, sans-serif" font-weight="700" font-size="25" letter-spacing="0" fill="#F2A83B" textLength="360" lengthAdjust="spacingAndGlyphs"><textPath href="#seal-c">${t} ·</textPath></text>` +
    `<path d="M50 92q7.5-7 15 0t15 0 15 0 15 0" fill="none" stroke="#F07FA3" stroke-width="3"/><ellipse cx="68" cy="78" rx="12" ry="8" fill="#F6EBD0"/><ellipse cx="91" cy="81" rx="8" ry="5" fill="#F07FA3"/></svg>`;
};

export function screens() {
  return content.items("screens");
}

export function mount(section) {
  section.textContent = "";
  const art = el("div", "card art");
  art.id = "story-art";
  const text = el("div", "card text");
  text.id = "story-text";
  section.append(art, text);
  const pager = el("div", "pager");
  const back = el("button", "btn sm", `◀ ${S("story", "back")}`);
  back.type = "button";
  back.id = "story-back";
  const dots = el("div", "dots");
  const next = el("button", "btn amber sm", `${S("story", "next")} ▶`);
  next.type = "button";
  next.id = "story-next";
  pager.append(back, dots, next, el("span", "still", S("story", "keys-still-play")));
  section.appendChild(pager);

  let list = [];
  let i = 0;

  const fitStory = refitOnFonts(() => fit(text, (px) => text.style.setProperty("--story-body", `${px}px`), 32, 24));
  const render = (pulse = false) => {
    list = screens();
    if (i >= list.length) i = Math.max(0, list.length - 1);
    const s = list[i];
    art.textContent = "";
    text.textContent = "";
    dots.textContent = "";
    list.forEach((_, k) => {
      const d = el("button", "dot" + (k === i ? " on" : ""));
      d.type = "button";
      d.setAttribute("aria-label", `Story ${k + 1} of ${list.length}`);
      d.appendChild(el("i"));
      tap(d, () => { i = k; render(); });
      dots.appendChild(d);
    });
    back.classList.toggle("off", i === 0);
    next.classList.toggle("off", i >= list.length - 1);
    if (!s) return;
    text.dataset.slug = s.slug;
    if (s.error_card) {
      text.classList.add("error-card");
      text.appendChild(el("h1", null, s.title));
      for (const b of s.blocks || []) if (b.type === "paragraph") text.appendChild(el("p", "body", b.text));
      return;
    }
    text.classList.remove("error-card");
    const v = VIEW[s.template];
    const body = v ? ART[v.from] : ART[s.template];
    if (body) {
      art.innerHTML = `<svg viewBox="${v ? v.viewBox : "0 0 1000 700"}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${body}</svg>`;
    }
    if (s.eyebrow) text.appendChild(el("div", "eyebrow", s.eyebrow));
    const h = el("h1", null, s.title);
    text.appendChild(h);
    for (const b of s.blocks || []) if (b.type === "paragraph") text.appendChild(el("p", "body", b.text));
    if ((s.slots || []).includes("disclosure")) {
      const card = el("div", "disclosure");
      card.id = "disclosure";
      card.insertAdjacentHTML("beforeend", SEAL(S("story", "seal")));
      const words = el("div");
      const title = content.item("captions", "disclosure");
      if (title) {
        const t = el("p", null, title.title);
        t.style.cssText = "font-family:var(--f-label);font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--amber);margin-bottom:6px";
        words.appendChild(t);
      }
      for (const p of content.captionBody("disclosure")) words.appendChild(el("p", null, p));
      card.appendChild(words);
      text.appendChild(card);
      if (pulse) requestAnimationFrame(() => card.classList.add("pulse"));
    }
    if (content.reviewMode() && content.notShippable(s)) {
      text.appendChild(el("div", "draft-stamp", S("story", "draft-stamp")));
    }
    // a screen at the 70-word limit, more so beside the disclosure, steps its text down
    fitStory();
  };

  tap(back, () => { if (i > 0) { i--; render(); } });
  tap(next, () => { if (i < list.length - 1) { i++; render(); } });

  return {
    show(slug, { pulse = false } = {}) {
      list = screens();
      const k = slug ? list.findIndex((s) => s.slug === slug) : -1;
      if (k >= 0) i = k;
      render(pulse);
    },
    showDisclosure() {
      list = screens();
      const k = list.findIndex((s) => (s.slots || []).includes("disclosure"));
      i = Math.max(0, k);
      render(true);
    },
    reset() { i = 0; },
    current: () => (list[i] ? list[i].slug : null),
  };
}
