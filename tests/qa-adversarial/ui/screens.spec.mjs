// What the screens say and draw against the real rigd (QA-ADV-04, QA-ADV-05).
import { test, expect, go } from "./real.mjs";

// QA-ADV-04 (fixed, UI lane round 6: the line shows only while midi_absent is up). rigd sets
// heartbeat.midi_present false whenever no keyboard is attached, and play.js shows the
// visitor line "The keyboard has gone quiet. The touch keys on screen still work." from that
// alone. A station that never had a keyboard (the touch-only mirror, UX 9 / KIOSK-9, or a
// keyboard that is not plugged in at boot) shows the "gone quiet" line for ever. INPUT-3 and
// UX 5.8 define the line as the unplug notice; rigd's own midi_absent fault is raised only on
// an unplug, so the page and rigd disagree.
test("QA-ADV-04: no 'keyboard has gone quiet' line when no keyboard was ever plugged in", async ({ app: page }) => {
  await go(page, "play");
  await page.waitForTimeout(1500); // a heartbeat (1 Hz) has arrived
  const hb = await page.evaluate(() => window.__seastones.live.heartbeat);
  expect(hb.faults).not.toContain("midi_absent"); // rigd itself says nothing was unplugged
  await expect(page.locator("#kb-notice-play")).toBeHidden();
});

// QA-ADV-05 (fixed, UI lane round 6: the operand column grows, the comment ellipsises). It was 200 px wide, and six
// operands are wider (DC tables and long indexed operands, up to 409 px), so they are drawn
// over the plain-English comment beside them (up to 209 px of overprint).
test("QA-ADV-05: no listing operand runs into its comment", async ({ app: page }) => {
  await go(page, "code");
  await page.waitForTimeout(800);
  const overlaps = await page.evaluate(() => {
    const out = [];
    for (const o of document.querySelectorAll("#layer-code span.o")) {
      const c = o.parentElement.querySelector("span.c");
      if (!c || !c.textContent.trim()) continue;
      const r = document.createRange();
      r.selectNodeContents(o);
      const over = r.getBoundingClientRect().right - c.getBoundingClientRect().left;
      if (over > 1) out.push(`${o.textContent} over "${c.textContent.slice(0, 30)}" by ${Math.round(over)} px`);
    }
    return out;
  });
  expect(overlaps).toEqual([]);
});
