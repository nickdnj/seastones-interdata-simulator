// PR-09, PR-10, PR-11: the code view. UI-16 (highlight is the PC), UI-17 (read-only, staff
// disassembly hidden), CODE-2 notes from content, CODE-4 (no memory-writing message).
import { test, expect, go, frames } from "./fixtures.mjs";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MESSAGE_TYPES } from "../../../src/web/app/protocol.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const LISTING = JSON.parse(readFileSync(path.join(ROOT, "build/program/rig.lst.json"), "utf8"));
const lineAddr = (pc) => {
  for (const l of LISTING.lines) {
    const a = parseInt(l.addr, 16);
    if (l.words.length && pc >= a && pc < a + 2 * l.words.length) return l.addr;
  }
  return null;
};

test("in single-step the highlighted line is the engine PC at every one of 200 steps (UI-16, CODE-1)", async ({ app, rig }) => {
  // 200 real taps, each waiting for the press transition to settle: about 0.3 s apiece,
  // so this one test needs more than the default 60 s, more so with two workers.
  test.setTimeout(180000);
  await go(app, "code");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await expect(app.locator("#hdr-speed")).toHaveText("STEP");
  for (let i = 0; i < 200; i++) {
    const seq = await app.evaluate(() => window.__seastones.live.state.cycles);
    await app.locator("#step-code").tap();
    await app.waitForFunction((c) => window.__seastones.live.state.cycles > c, seq);
    const { pc } = await app.evaluate(() => window.__seastones.live.state);
    await expect(app.locator("#listing .ln.cur")).toHaveAttribute("data-addr", lineAddr(pc));
    if (i % 50 === 0) await expect(app.locator("#now-running")).toContainText(pc.toString(16).toUpperCase().padStart(4, "0"));
  }
});

test("registers show exact values in STEP and dots at speed", async ({ app }) => {
  await go(app, "code");
  await frames(app, 3);
  await expect(app.locator("#regs b").first()).toHaveText("••••");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await frames(app, 3);
  const st = await app.evaluate(() => window.__seastones.live.state);
  await expect(app.locator("#regs b").nth(10)).toHaveText(st.r[10].toString(16).toUpperCase().padStart(4, "0"));
});

test("at speed the busiest block is lit and the heat band follows pc_hist (UI-16)", async ({ app, rig }) => {
  await go(app, "code");
  await frames(app, 20);
  const hist = (await app.evaluate(() => window.__seastones.live.state)).pc_hist;
  const top = Object.entries(hist).sort((a, b) => b[1] - a[1])[0][0];
  const bar = await app.evaluate((a) => {
    const rows = [...document.querySelectorAll("#listing .ln")];
    const i = rows.findIndex((r) => r.dataset.addr === a);
    return Number(document.querySelectorAll("#listing .heat i")[i].style.opacity);
  }, top);
  expect(bar).toBe(1);
  await expect(app.locator("#block-note")).not.toHaveText("");
});

test("each block's note comes from content and is at most 40 words (CODE-2)", async ({ app }) => {
  await go(app, "code");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await expect.poll(() => app.evaluate(() => window.__seastones.live.state.speed)).toBe("step");
  await expect.poll(async () => (await app.locator("#block-note").innerText()).length).toBeGreaterThan(10);
  const note = await app.locator("#block-note").innerText();
  expect(note.split(/\s+/).length).toBeLessThanOrEqual(40);
});

test("every block's note fits its card: the controls below it stay clear of the dock (UI-38)", async ({ app }) => {
  // A longer note once pushed STEP into the dock. Render each note from content/code/ in
  // the card, staff mode on (the longest "now running" line), and measure.
  const dir = path.join(ROOT, "content/code");
  const notes = readdirSync(dir).filter((f) => f.endsWith(".md")).map((f) => {
    const [head, body] = readFileSync(path.join(dir, f), "utf8").split(/\n\n/);
    return { f, title: /^title:\s*(.*)$/m.exec(head)[1], body: body.trim() };
  });
  await go(app, "code");
  await app.locator('#layer-code .det[data-speed="step"]').tap();
  await app.evaluate(() => window.__seastones.setStaff(true));
  for (const n of notes) {
    const r = await app.evaluate(({ title, body }) => {
      document.querySelector("#block-title").textContent = title;
      document.querySelector("#block-note").textContent = body;
      const dock = document.querySelector(".dock .tab").getBoundingClientRect(); // the tabs, as layout.spec
      const last = [...document.querySelectorAll("#layer-code .code-right button")].map((b) => b.getBoundingClientRect().bottom);
      const note = document.querySelector("#block-note");
      return { gap: dock.top - Math.max(...last), clipped: note.scrollHeight > note.clientHeight + 1 };
    }, n);
    expect(r.gap, `${n.f}: controls end ${-r.gap} px into the dock`).toBeGreaterThanOrEqual(8);
    expect(r.clipped, `${n.f}: note clipped`).toBe(false);
  }
  await app.evaluate(() => window.__seastones.setStaff(false));
});

test("the code view is read-only and the disassembly column is hidden from visitors (UI-17, CODE-3, CODE-4)", async ({ app, rig }) => {
  await go(app, "code");
  expect(await app.locator("#listing [contenteditable], #listing input, #listing button, #listing [data-tap]").count()).toBe(0);
  await expect(app.locator("#listing .ln .d").first()).toBeHidden();
  await app.evaluate(() => window.__seastones.setStaff(true));
  await expect(app.locator("#listing .ln .d").first()).toBeVisible();
  await expect(app.locator("#listing .ln .d").first()).toHaveText(/\S/);
  await app.evaluate(() => window.__seastones.setStaff(false));
  // every message the page sent in this session is in the protocol's visitor set
  for (const m of rig.messages()) expect(MESSAGE_TYPES).toContain(m.t);
  expect(MESSAGE_TYPES.some((t) => /dep|mem|sr|staff|passage/.test(t))).toBe(false);
});

test("no listing operand or label runs into the column after it (QA-ADV-05)", async ({ app }) => {
  await go(app, "code");
  await frames(app, 3);
  const bad = await app.evaluate(() => {
    const out = [];
    for (const row of document.querySelectorAll("#listing .ln")) {
      const cells = [...row.children].filter((c) => getComputedStyle(c).display !== "none" && c.textContent.trim());
      for (let i = 0; i + 1 < cells.length; i++) {
        const r = document.createRange();
        r.selectNodeContents(cells[i]);
        const over = r.getBoundingClientRect().right - cells[i + 1].getBoundingClientRect().left;
        if (over > 1) out.push(`${row.dataset.addr}: "${cells[i].textContent}" over "${cells[i + 1].textContent.slice(0, 20)}"`);
      }
    }
    return out;
  });
  expect(bad).toEqual([]);
});
