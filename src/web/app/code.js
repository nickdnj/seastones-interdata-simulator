// code.js: layer 3, The Code (PR-09, PR-10, PR-11; CODE-1, CODE-2, CODE-3, CODE-4).
//
// The real listing from the assembler, a highlight from the engine's PC, registers, a heat
// band from pc_hist, and one plain-English note per block from content/code/. At CRAWL and
// STEP the exact line is lit and kept about 300 px from the top; at speed no single line can
// be current, so the busiest block is tinted and the heat band shows where time goes.
//
// Read-only (CODE-4): nothing in the listing is a control, and the protocol has no message
// that writes memory (protocol.js). The disassembly column (SIMH's own reading of memory,
// from hello.disasm) is for staff and experts and hidden from visitors by default (CODE-3).

import { el } from "./blocks.js";
import { S } from "./strings.js";
import { fit, refitOnFonts } from "./fit.js";
import * as content from "./content.js";
import * as rig from "./rig.js";
import * as speed from "./speed.js";
import * as listing from "./listing.js";

const BLK_H = 54;
const LN_H = 44;
const KEEP_FROM_TOP = 300;
const hex4 = (v) => v.toString(16).toUpperCase().padStart(4, "0");

export function mount(section, ctx) {
  section.textContent = "";
  const card = el("div", "card listing");
  card.id = "listing";
  const heat = el("div", "heat");
  const scroll = el("div", "scroll");
  card.append(scroll, heat);
  section.appendChild(card);

  const right = el("div", "code-right");
  const c1 = el("div", "card");
  c1.appendChild(el("div", "lbl amber", S("code", "what-this-does")));
  const ntitle = el("div", "note-title", "");
  ntitle.id = "block-title";
  const ntext = el("div", "note", "");
  ntext.id = "block-note";
  c1.append(ntitle, ntext);
  right.appendChild(c1);
  const c2 = el("div", "card");
  c2.appendChild(el("div", "lbl amber", S("code", "registers")));
  const regs = el("div", "regs");
  regs.id = "regs";
  const regCells = [];
  for (let i = 0; i < 16; i++) {
    const d = el("div");
    d.appendChild(el("span", null, `R${i}`));
    const b = el("b", null, "••••");
    d.appendChild(b);
    regs.appendChild(d);
    regCells.push({ d, b, v: null });
  }
  c2.appendChild(regs);
  // "Now running" and STEP share a row: STEP runs the instruction named beside it.
  const nowRow = el("div", "now-row");
  const nowText = el("div", "now-text");
  nowText.appendChild(el("span", "lbl", S("code", "now")));
  const now = el("div", "now", "");
  now.id = "now-running";
  nowText.appendChild(now);
  nowRow.appendChild(nowText);
  const stepBtn = el("button", "btn amber sm", `${S("computer", "step")} ▶`);
  stepBtn.type = "button";
  stepBtn.id = "step-code";
  speed.stepButton(stepBtn);
  nowRow.appendChild(stepBtn);
  c2.appendChild(nowRow);
  right.appendChild(c2);
  // The detents sit at the foot of the column, directly above the dock, within a child's
  // and a seated visitor's reach (UX 4.3, A-04).
  const c3 = el("div", "code-dets");
  const dets = speed.detents(c3);
  right.appendChild(c3);
  section.appendChild(right);

  let built = null;
  let rows = new Map(); // listing line -> row element
  let blockRows = new Map();
  let heatBars = new Map();
  let curRow = null;
  let curBlock = null;
  let scrollY = 0;

  const build = (lst) => {
    scroll.textContent = "";
    heat.textContent = "";
    rows = new Map();
    blockRows = new Map();
    heatBars = new Map();
    let y = 0;
    const disasm = (rig.live.hello && rig.live.hello.disasm) || {};
    lst.blocks.forEach((b, bi) => {
      const note = content.item("code", b.id);
      const hdr = el("div", "blk");
      hdr.appendChild(el("span", "disc", String(bi + 1)));
      hdr.appendChild(el("span", "bt", note ? note.title : b.id));
      scroll.appendChild(hdr);
      blockRows.set(b.id, { el: hdr, y });
      y += BLK_H;
      for (const l of b.lines) {
        const r = el("div", "ln" + (l.data ? " data" : ""));
        r.dataset.addr = l.hex;
        r.append(el("span", "a", l.hex), el("span", "l", l.label), el("span", "m", l.op), el("span", "o", l.args));
        r.appendChild(el("span", "d", disasm[l.hex] || ""));
        r.appendChild(el("span", "c", l.comment));
        scroll.appendChild(r);
        rows.set(l, { el: r, y });
        const bar = el("i");
        bar.style.top = `${y}px`;
        bar.style.height = `${LN_H}px`;
        bar.style.opacity = "0";
        heat.appendChild(bar);
        heatBars.set(l, bar);
        y += LN_H;
      }
    });
    built = lst;
  };

  const setScroll = (y) => {
    const max = Math.max(0, scroll.scrollHeight - 790);
    const v = Math.max(0, Math.min(max, y));
    if (v !== scrollY) {
      scrollY = v;
      scroll.style.transform = `translateY(${-v}px)`;
      heat.style.transform = `translateY(${-v}px)`;
    }
  };

  const refit = refitOnFonts(() => fit(c1, (px) => { ntext.style.fontSize = `${px}px`; }, 32, 24));
  // the card shrinks when the registers card grows (a wrapped "now running" line): refit then too
  if (typeof ResizeObserver === "function") new ResizeObserver(() => refit()).observe(c1);

  const showBlock = (id) => {
    if (curBlock === id) return;
    if (curBlock && blockRows.get(curBlock)) blockRows.get(curBlock).el.classList.remove("cur");
    curBlock = id;
    if (id && blockRows.get(id)) blockRows.get(id).el.classList.add("cur");
    const note = id && content.item("code", id);
    const t = note ? note.title : "";
    const n = note ? (note.blocks || []).filter((b) => b.type === "paragraph").map((b) => b.text).join(" ") : "";
    if (ntitle.textContent !== t) ntitle.textContent = t;
    if (ntext.textContent !== n) {
      ntext.textContent = n;
      // a note at the 40-word limit steps down rather than push the controls off the column
      refit();
    }
    for (const [l, r] of rows) r.el.classList.toggle("tint", !!id && l.block === id && !(curRow && curRow === r));
  };

  return {
    paint(state) {
      const lst = listing.get();
      if (lst && built !== lst) build(lst);
      dets(state);
      stepBtn.classList.toggle("off", !state || state.speed !== "step");
      if (!lst) return;
      const exact = !!(state && state.lamps.exact);
      // heat band
      let max = 1e-9;
      for (const l of lst.lines) max = Math.max(max, state ? state.pc_hist[l.hex] || 0 : 0);
      for (const [l, bar] of heatBars) {
        const o = state ? Math.round(((state.pc_hist[l.hex] || 0) / max) * 100) / 100 : 0;
        if (bar._o !== o) { bar._o = o; bar.style.opacity = String(o); }
      }
      // current line (exact) or busiest block (at speed)
      let line = null;
      let block = null;
      if (state && exact) {
        line = listing.lineAt(state.pc);
        block = line ? line.block : null;
      } else if (state) {
        const per = new Map();
        for (const l of lst.lines) per.set(l.block, (per.get(l.block) || 0) + (state.pc_hist[l.hex] || 0));
        let best = 0;
        for (const [b, v] of per) if (v > best) { best = v; block = b; }
      }
      const row = line ? rows.get(line) : null;
      if (row !== curRow) {
        if (curRow) curRow.el.classList.remove("cur");
        curRow = row;
        if (row) row.el.classList.add("cur");
      }
      showBlock(block);
      if (row) setScroll(row.y - KEEP_FROM_TOP);
      else if (block && blockRows.get(block)) setScroll(blockRows.get(block).y - 120);
      // registers: exact only
      for (let i = 0; i < 16; i++) {
        const c = regCells[i];
        const v = state && exact ? hex4(state.r[i]) : "••••";
        if (c.b.textContent !== v) {
          if (c.v !== null && v !== "••••" && c.v !== "••••") {
            c.d.classList.remove("flash");
            void c.d.offsetWidth;
            c.d.classList.add("flash");
            setTimeout(() => c.d.classList.remove("flash"), 200);
          }
          c.b.textContent = v;
          c.v = v;
        }
      }
      // "Now running": the PC from the snapshot and that line of our source. Staff also see
      // SIMH's own disassembly of the word in memory there, as proof it is the real memory.
      let nowText = state && !exact ? S("code", "blurred") : "";
      now.classList.toggle("blur", !!state && !exact);
      if (state && exact) {
        nowText = `${hex4(state.pc)}  ${line ? `${line.op} ${line.args}` : "?"}`;
        if (document.body.classList.contains("staff") && rig.live.hello) {
          nowText += `   · SIMH: ${rig.live.hello.disasm[hex4(state.pc)] || "?"}`;
        }
      }
      if (now.textContent !== nowText) now.textContent = nowText;
    },
  };
}
