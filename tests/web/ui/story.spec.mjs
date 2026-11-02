// CT-09, CT-10, CT-02, CT-07 (review half): the Story layer and the disclosure.
// UI-07 (one tap to the full disclosure from every layer), STORY-1 (screens from content,
// at most 70 words), STORY-2 (no unconfirmed claim on a visitor screen), UI-37 (drafts only
// in review mode, stamped).
import { test, expect, go } from "./fixtures.mjs";

const LAYERS = ["attract", "play", "computer", "code", "patch", "story"];
const UNSOURCED = [/Phil Lesh/, /middle of the Dead's shows/, /an hour from this room/i, /magnetic core/i, /16-bit/, /tell the staff at the desk/i, /record followed in 1975/i, /Photographs from that day show/i];

const NOT_AFFILIATED = "Not affiliated with or endorsed by Ned Lagin, the Grateful Dead or E-mu Systems.";

test("the full disclosure is one tap from every layer: the footer opens the About page (UI-07, STORY-3, CT-09)", async ({ app }) => {
  for (const l of LAYERS) {
    await go(app, l);
    await app.locator("#about").tap();
    await expect(app.locator("#about-page")).toBeVisible();
    await expect(app.locator("#about-disclosure")).toContainText(NOT_AFFILIATED);
    // the 52-word disclosure, word for word as Story 1 shows it
    const words = (await app.locator("#about-disclosure p").allInnerTexts()).join(" ").split(/\s+/).filter(Boolean);
    expect(words.length).toBe(52);
    await app.locator("#about-close").tap();
    await expect(app.locator("#about-page")).toBeHidden();
  }
  // Story 1 still carries the same disclosure
  await go(app, "story");
  await expect(app.locator("#disclosure")).toContainText(NOT_AFFILIATED);
});

test("the About page carries credits, notices and the privacy statement from content (CT-09, STORY-6)", async ({ app }) => {
  await app.locator("#about").tap();
  await expect(app.locator("#about-credits")).toContainText("open-simh");
  await expect(app.locator("#about-credits")).toContainText("Robert M. Supnik");
  await expect(app.locator("#about-notices")).toContainText("SIL Open Font License");
  await expect(app.locator("#about-notices")).toContainText("THIRD-PARTY-NOTICES");
  await expect(app.locator("#about-privacy")).toHaveText(/collects no personal information/);
  await expect(app.locator("#about-page")).not.toContainText("[about/");
  // the dock, HOME and the footer stay live under it; HOME closes it
  await expect(app.locator("#home")).toBeVisible();
  await app.locator("#home").tap();
  await expect(app.locator("#about-page")).toBeHidden();
  // a dock tab closes it too
  await app.locator("#about").tap();
  await app.locator('.tab[data-layer="code"]').tap();
  await expect(app.locator("#about-page")).toBeHidden();
});

test("six screens from content, each at most 70 words, none with an unsourced claim (STORY-1, STORY-2)", async ({ app }) => {
  await go(app, "story");
  await expect(app.locator("#layer-story .dot")).toHaveCount(6);
  for (let i = 0; i < 6; i++) {
    const text = await app.locator("#story-text").innerText();
    const body = (await app.locator("#story-text .body").allInnerTexts()).join(" ");
    expect(body.split(/\s+/).filter(Boolean).length, `screen ${i + 1}`).toBeLessThanOrEqual(70);
    for (const re of UNSOURCED) expect(text, `screen ${i + 1}`).not.toMatch(re);
    await expect(app.locator("#story-text .draft-stamp")).toHaveCount(0);
    if (i < 5) await app.locator("#story-next").tap();
  }
  await expect(app.locator("#story-next")).toHaveClass(/off/);
});

test("pictures make no unsourced claim either: the shipped screen 4 does not label core memory", async ({ app }) => {
  await go(app, "story");
  for (let i = 0; i < 6; i++) {
    const art = await app.locator("#story-art").innerHTML();
    expect(art, `screen ${i + 1}`).not.toMatch(/CORE MEMORY|E-mu/i);
    if (i < 5) await app.locator("#story-next").tap();
  }
});

test("review mode shows the drafts, each stamped not shippable; leaving it hides them again (UI-37, CT-07)", async ({ app }) => {
  await go(app, "story");
  await app.evaluate(() => window.__seastones.setReview(true));
  await expect(app.locator("#layer-story .dot")).toHaveCount(10);
  const n = 10;
  let stamped = 0;
  for (let i = 0; i < n; i++) {
    await app.locator("#layer-story .dot").nth(i).tap();
    if (await app.locator("#story-text .draft-stamp").count()) {
      stamped++;
      await expect(app.locator("#story-text .draft-stamp")).toHaveText(/not shippable/i);
    }
  }
  expect(stamped).toBe(4);
  await app.evaluate(() => window.__seastones.setReview(false));
  await expect(app.locator("#layer-story .dot")).toHaveCount(6);
});

test("the keyboard still plays in Story and the pager never advances by itself", async ({ app, rig }) => {
  await go(app, "story");
  const slug = await app.locator("#story-text").getAttribute("data-slug");
  await app.keyboard.down("a");
  await expect.poll(() => rig.touchBits).toBe(1n << 12n);
  await app.keyboard.up("a");
  await app.waitForTimeout(1500);
  expect(await app.locator("#story-text").getAttribute("data-slug")).toBe(slug);
});
