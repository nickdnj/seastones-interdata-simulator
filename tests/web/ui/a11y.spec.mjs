// KP-19 and KP-18: accessibility checks that can be automated (UX 10, WCAG 2.2 AA), and the
// 15.6 inch / touch-only layout. UI-25 (touch targets), UI-26 (type, also shell.spec),
// UI-27 (contrast, the part a script can check), UI-29 (reduced motion), UI-30 (names, live
// regions, headings), UI-38 (no clipping). What a script cannot check is listed in
// docs/qa/results/ui/a11y-manual.md for KP-21.
import { test, expect, go, frames, open } from "./fixtures.mjs";

const LAYERS = ["attract", "play", "computer", "code", "patch", "story"];
const TARGETS = "[data-tap], button, .wk, .bk, .jackhit, [role=button], [role=slider]";

test("every touch target is at least 54 px, and controls are at least 8 px apart (UI-25, A-05, A-06)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    await frames(app, 2);
    const res = await app.evaluate((sel) => {
      const vis = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && !e.closest("[hidden]") && cs.display !== "none"; };
      const els = [...document.querySelectorAll(sel)].filter(vis).filter((e) => !e.closest(".layer:not(.on)"));
      const small = els.filter((e) => { const r = e.getBoundingClientRect(); return r.width < 53.5 || r.height < 53.5; })
        .map((e) => `${e.className || e.id} ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`);
      // spacing: not for piano keys (adjacent by design, like the physical keyboard) or jacks (checked in patch.spec)
      const ctl = els.filter((e) => !e.matches(".wk, .bk, .jackhit, .kb"));
      const close = [];
      for (let i = 0; i < ctl.length; i++) for (let j = i + 1; j < ctl.length; j++) {
        const a = ctl[i].getBoundingClientRect(), b = ctl[j].getBoundingClientRect();
        if (ctl[i].contains(ctl[j]) || ctl[j].contains(ctl[i])) continue;
        const dx = Math.max(0, Math.max(a.left, b.left) - Math.min(a.right, b.right));
        const dy = Math.max(0, Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom));
        if (Math.max(dx, dy) < 7.5) close.push(`${ctl[i].className || ctl[i].id} / ${ctl[j].className || ctl[j].id}`);
      }
      return { small, close };
    }, TARGETS);
    expect(res.small, `layer ${l}`).toEqual([]);
    expect(res.close, `layer ${l}`).toEqual([]);
  }
});

test("every control has an accessible name; live regions and Story headings exist (UI-30, A-28 to A-30)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    const unnamed = await app.evaluate((sel) => [...document.querySelectorAll(sel)]
      .filter((e) => !e.closest(".layer:not(.on)") && !e.closest("[hidden]"))
      .filter((e) => !(e.getAttribute("aria-label") || e.textContent.trim()))
      .map((e) => e.className || e.id), TARGETS);
    expect(unnamed, `layer ${l}`).toEqual([]);
  }
  await expect(app.locator("#live-polite")).toHaveAttribute("aria-live", "polite");
  await expect(app.locator("#live-assertive")).toHaveAttribute("aria-live", "assertive");
  await go(app, "play");
  await app.locator('#layer-play .det[data-speed="div30"]').tap();
  await expect(app.locator("#live-polite")).toContainText("1/30");
  await go(app, "story");
  await expect(app.locator("#story-text h1")).toHaveCount(1);
});

test("a fault is announced assertively (A-29)", async ({ app, rig }) => {
  await go(app, "play");
  rig.fault("program_stalled");
  await expect(app.locator("#live-assertive")).toHaveText("The computer is restarting.");
  rig.clearFault("program_stalled");
});

test("body text meets 7:1 and large text 4.5:1 where a solid background can be measured (UI-27, A-10)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    await frames(app, 2);
    const bad = await app.evaluate(() => {
      const rgb = (s) => (s.match(/[\d.]+/g) || []).map(Number);
      const lum = ([r, g, b]) => [r, g, b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
      const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
      const out = [];
      const walker = document.createTreeWalker(document.getElementById("stage"), NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const el = n.parentElement;
        if (!n.textContent.trim() || el.closest("svg") || el.closest(".layer:not(.on)") || el.closest("[hidden]") || el.closest(".sr-only")) continue;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || el.getClientRects().length === 0 || Number(cs.opacity) < 1) continue;
        if (el.closest(".off, .disabled")) continue; // inactive controls are exempt (UX 12)
        let bg = null;
        for (let p = el; p; p = p.parentElement) {
          const s = getComputedStyle(p);
          if (s.backgroundImage !== "none") { bg = null; break; } // gradients: checked by eye at DES-1
          const c = rgb(s.backgroundColor);
          if (c.length >= 3 && (c.length === 3 || c[3] === 1)) { bg = c.slice(0, 3); break; }
        }
        if (!bg) continue;
        const fg = rgb(cs.color).slice(0, 3);
        const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
        const need = size >= 24 || (size >= 18.66 && bold) ? 4.5 : 7;
        const r = ratio(fg, bg);
        if (r < need) out.push(`${r.toFixed(2)} < ${need}: "${n.textContent.trim().slice(0, 30)}"`);
      }
      return out;
    });
    expect(bad, `layer ${l}`).toEqual([]);
  }
});

test("reduced motion removes the sweep, the pill pulse and layer slides, and keeps lamps and meters (UI-29, A-23)", async ({ page, rig }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page, rig);
  const anim = await page.evaluate(() => [...document.querySelectorAll(".att .gl, .att .pill")].map((e) => getComputedStyle(e).animationName));
  expect(anim.every((a) => a === "none")).toBe(true);
  await go(page, "play");
  expect(await page.locator("#layer-play").evaluate((e) => getComputedStyle(e).animationName)).toBe("none");
  await page.keyboard.down("a");
  await expect(page.locator("#station-3 .voices .nn").first()).toHaveText("C4");
  await page.keyboard.up("a");
});

test("no text is clipped and nothing overflows its card, in every layer (UI-38, B-07)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    await app.waitForTimeout(400); // the 280 ms layer slide has finished
    const over = await app.evaluate(() => [...document.querySelectorAll(".layer.on .card, .layer.on .btn, .layer.on .chip, .layer.on .det, .tab, #footer, #header")]
      .filter((e) => !e.matches(".listing") && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1))
      .map((e) => `${e.className || e.id} ${e.scrollWidth}x${e.scrollHeight} > ${e.clientWidth}x${e.clientHeight}`));
    expect(over, `layer ${l}`).toEqual([]);
    const outside = await app.evaluate(() => [...document.querySelectorAll(".layer.on *")]
      .filter((e) => !(e.closest("svg") && e.tagName !== "svg")) // SVG children are clipped by their svg
      .filter((e) => !e.closest(".listing .scroll, .listing .heat")) // the listing scrolls inside its clipped card
      .filter((e) => { const r = e.getBoundingClientRect(); return r.width && (r.right > 1921 || r.bottom > 1081 || r.left < -1); })
      .map((e) => e.className || e.tagName));
    expect(outside, `layer ${l}`).toEqual([]);
  }
});

test("touch-only mirror configuration (15.6 inch, 1920 x 1080 CSS px, no keyboard): every layer renders and plays by touch (KP-18, UI-38, DES-5)", async ({ browser, rig }) => {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, hasTouch: true, isMobile: false, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await open(page, rig);
  for (const l of LAYERS) {
    await go(page, l);
    await expect(page.locator(`#layer-${l}`)).toBeVisible();
  }
  await go(page, "play");
  await page.locator('#layer-play [data-key="7"]').tap();
  await expect.poll(() => rig.messages("keys.touch").some((m) => m.bits === "0000000000000080")).toBe(true);
  await ctx.close();
});

test("the stage scales with one transform: a smaller window keeps the same layout (DES-5)", async ({ browser, rig }) => {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 } });
  const page = await ctx.newPage();
  await open(page, rig);
  const t = await page.locator("#stage").evaluate((e) => getComputedStyle(e).transform);
  expect(t).toMatch(/matrix\(0\.7/);
  await ctx.close();
});
