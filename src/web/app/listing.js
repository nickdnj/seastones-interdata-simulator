// listing.js: the program listing from the assembler (PR-09; CODE-1, ARCHITECTURE 7).
//
// `rig.lst.json` (seastones.listing/1, written by sxasm) maps every source line to its
// address, words and *@block. The code view is built from it, never from disassembly, and
// it must belong to the image the engine is running: if `hello.listing_id` and the
// listing's `image_sha256` differ, the code view says so instead of guessing (UX 5.4).

const URL_ = "/program/rig.lst.json";
let doc = null;
let failure = null;

export async function load(url = URL_) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`rig.lst.json: HTTP ${res.status}`);
    const j = await res.json();
    if (j.format !== "seastones.listing/1") throw new Error("not a seastones.listing/1");
    doc = parse(j);
    failure = null;
  } catch (e) {
    doc = null;
    failure = String(e.message || e);
  }
  return doc;
}

export const get = () => doc;
export const failureReason = () => failure;

const DATA_OPS = new Set(["DC", "DS", "EQU", "ORG", "END"]);

/** Split a CAL source line into label, mnemonic, operands and comment. */
export function splitLine(text) {
  const m = /^(\S*)\s+(\S+)(?:\s+(\S+))?(?:\s+(.*))?$/.exec(text);
  if (!m) return { label: "", op: "", args: "", comment: text.trim() };
  return { label: m[1] || "", op: m[2] || "", args: m[3] || "", comment: (m[4] || "").trim() };
}

export function parse(j) {
  const lines = [];
  const blocks = [];
  const byAddr = new Map();
  for (const ln of j.lines) {
    if (!ln.words.length) continue; // only lines that put words in memory are shown
    const parts = splitLine(ln.text);
    const entry = {
      addr: parseInt(ln.addr, 16),
      hex: ln.addr,
      words: ln.words,
      block: ln.block || "",
      file: ln.file || "",
      ...parts,
      data: DATA_OPS.has(parts.op.toUpperCase()),
    };
    if (!blocks.length || blocks[blocks.length - 1].id !== entry.block) {
      blocks.push({ id: entry.block, lines: [], executable: false, file: entry.file });
    }
    const b = blocks[blocks.length - 1];
    b.lines.push(entry);
    if (!entry.data) b.executable = true;
    lines.push(entry);
    for (let i = 0; i < ln.words.length; i++) byAddr.set(entry.addr + 2 * i, entry);
  }
  // The loop the computer repeats: the executable blocks of the source file that holds the
  // LOOP label (the scan loop; the routines it calls are not the loop). A program without
  // that label: every executable block after the entry block.
  const exec = blocks.filter((b) => b.executable);
  const top = lines.find((l) => l.label === "LOOP");
  const loop = top && top.file ? exec.filter((b) => b.file === top.file) : exec.slice(1);
  return { name: j.name, sha: j.image_sha256, lines, blocks, byAddr, loop };
}

/** The listing line for an address (an instruction's second word maps to its line). */
export const lineAt = (addr) => (doc ? doc.byAddr.get(addr) || null : null);
export const blockAt = (addr) => {
  const l = lineAt(addr);
  return l ? l.block : null;
};
