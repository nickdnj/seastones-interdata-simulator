// blocks.js: content blocks turned into DOM (CT-01; ported from the Model 4 kiosk).
//
// index.json carries `paragraph`, `bullets`, `table` and `cards`; `**bold**` is the only
// inline mark. This module builds elements, never HTML strings, so a content file can never
// inject markup.

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/** SVG element with attributes. */
export function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (parent) parent.appendChild(node);
  return node;
}

/** Escape text for the few places a drawing is built as an SVG string. */
export function esc(text) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(text ?? "").replace(/[&<>"']/g, (c) => map[c]);
}

export function inline(parent, text) {
  const parts = String(text ?? "").split(/\*\*([^*]+)\*\*/g);
  for (let i = 0; i < parts.length; i++) {
    if (!parts[i]) continue;
    if (i % 2 === 1) parent.appendChild(el("strong", null, parts[i]));
    else parent.appendChild(document.createTextNode(parts[i]));
  }
  return parent;
}

export function para(text, className = "body") {
  return inline(el("p", className), text);
}

export function renderBlock(block, opts = {}) {
  switch (block.type) {
    case "paragraph": return para(block.text, opts.paraClass || "body");
    case "bullets": {
      const ul = el("ul", "bullets");
      for (const item of block.items || []) ul.appendChild(inline(el("li"), item));
      return ul;
    }
    case "table": {
      const tbl = el("table", "data-table");
      const head = el("tr");
      for (const h of block.headers || []) head.appendChild(inline(el("th"), h));
      tbl.appendChild(head);
      for (const cells of block.rows || []) {
        const row = el("tr");
        for (const c of cells) row.appendChild(inline(el("td"), c));
        tbl.appendChild(row);
      }
      return tbl;
    }
    default:
      return null; // cards are lookups (captions), not rendered as blocks here
  }
}

export function renderBlocks(parent, blocks, opts = {}) {
  for (const block of blocks || []) {
    const node = renderBlock(block, opts);
    if (node) parent.appendChild(node);
  }
  return parent;
}
