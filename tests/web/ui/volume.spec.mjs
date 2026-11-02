// AUDIO-3 (PRD v0.2, M), KP-06 and NFR-10: a visitor volume below the staff ceiling and a
// visible mute, on every layer, through rigd's audio.volume (dB below the ceiling, -40 to 0)
// and audio.mute, shown from state.volume.
import { test, expect, go, frames } from "./fixtures.mjs";

const vol = (rig) => rig.volume;

test("the volume button is in the dock on every layer, in reach, and shows rigd's level (AUDIO-3, A-04)", async ({ app }) => {
  for (const l of ["play", "computer", "code", "patch", "story"]) {
    await go(app, l);
    await expect(app.locator("#volume")).toBeVisible();
    await expect(app.locator("#volume")).toBeEnabled();
  }
  const b = await app.locator("#volume").boundingBox();
  expect(b.y + b.height).toBeGreaterThanOrEqual(1080 * 0.8); // the lowest 20%
  expect(Math.min(b.width, b.height)).toBeGreaterThanOrEqual(54);
  await expect(app.locator("#volume")).toHaveAttribute("aria-label", "Volume: 5 / 5"); // 0 dB: at the ceiling
});

test("quieter and louder step 6 dB below the ceiling, down to rigd's floor, and never above 0 dB (AUDIO-3, STAFF-2)", async ({ app, rig }) => {
  await go(app, "play");
  await app.locator("#volume").tap();
  await expect(app.locator("#volume-panel")).toBeVisible();
  await expect(app.locator("#volume-bars i.on")).toHaveCount(5);
  rig.clearRecorded();
  await app.locator("#volume-up").tap(); // at the ceiling: nothing louder exists, nothing is sent
  await frames(app, 3);
  expect(rig.messages("audio.volume")).toEqual([]);
  await app.locator("#volume-down").tap();
  await expect.poll(() => vol(rig).db).toBe(-6);
  await expect(app.locator("#volume-bars i.on")).toHaveCount(4);
  for (let i = 0; i < 6; i++) await app.locator("#volume-down").tap();
  await expect.poll(() => vol(rig).db).toBe(-40);
  await expect(app.locator("#volume-bars i.on")).toHaveCount(0);
  for (const m of rig.messages("audio.volume")) expect(m.db).toBeGreaterThanOrEqual(-40), expect(m.db).toBeLessThanOrEqual(0);
  await app.locator("#volume-up").tap();
  await expect.poll(() => vol(rig).db).toBe(-24);
});

test("mute is visible on the dock on every layer, and Sound on (or Louder) brings it back (AUDIO-3)", async ({ app, rig }) => {
  await go(app, "play");
  await app.locator("#volume").tap();
  await app.locator("#volume-down").tap();
  await app.locator("#volume-mute").tap();
  await expect.poll(() => vol(rig).muted).toBe(true);
  await expect(app.locator("#volume")).toHaveClass(/muted/);
  await expect(app.locator("#volume")).toContainText("Muted");
  await expect(app.locator("#volume-mute")).toHaveText("Sound on");
  await expect.poll(() => app.evaluate(() => window.__seastones.live.heartbeat.muted)).toBe(true);
  for (const l of ["computer", "code", "patch", "story"]) {
    await go(app, l);
    await expect(app.locator("#volume")).toContainText("Muted");
  }
  await app.locator("#volume").tap();
  await app.locator("#volume-up").tap();
  await expect.poll(() => vol(rig).muted).toBe(false);
  await expect(app.locator("#volume")).not.toHaveClass(/muted/);
  // a staff mute shows the same way: the visitor always sees that the station is muted
  rig.staffCfg.muted = true;
  rig.broadcast(rig.heartbeatMsg());
  await expect(app.locator("#volume")).toContainText("Muted");
  rig.staffCfg.muted = false;
  rig.broadcast(rig.heartbeatMsg());
  await expect(app.locator("#volume")).toContainText("Volume");
});

test("HOME puts rigd back to 0 dB and unmuted, so the next visitor is never left silent (AUDIO-3, PLAY-9)", async ({ app, rig }) => {
  await go(app, "play");
  await app.locator("#volume").tap();
  await app.locator("#volume-down").tap();
  await app.locator("#volume-mute").tap();
  await expect.poll(() => vol(rig)).toEqual({ db: -6, muted: true });
  await app.locator("#home").tap();
  await expect(app.locator("#volume-panel")).toBeHidden();
  await expect.poll(() => vol(rig)).toEqual({ db: 0, muted: false });
  await expect(app.locator("#volume")).not.toHaveClass(/muted/);
});

test("the panel closes by itself, and on a layer change; the page makes no sound (AUDIO-3)", async ({ app }) => {
  await go(app, "play");
  await app.locator("#volume").tap();
  await expect(app.locator("#volume-panel")).toBeVisible();
  await app.locator('.tab[data-layer="code"]').tap();
  await expect(app.locator("#volume-panel")).toBeHidden();
  await app.locator("#volume").tap();
  await expect(app.locator("#volume-panel")).toBeVisible();
  await expect(app.locator("#volume-panel")).toBeHidden({ timeout: 9000 });
});

test("a rigd without state.volume: the button is shown disabled, never guessing a level", async ({ app, rig }) => {
  await go(app, "play");
  const orig = rig.stateMsg.bind(rig);
  rig.stateMsg = (res) => { const s = orig(res); delete s.volume; return s; };
  await expect(app.locator("#volume")).toBeDisabled();
  rig.stateMsg = orig;
  await expect(app.locator("#volume")).toBeEnabled();
});

test("underruns: a count on the staff screen, a storm is a staff line and no visitor card (KIOSK-5, QA-ADV-06)", async ({ app, rig }) => {
  await go(app, "play");
  rig.underrun(1);
  await frames(app, 3);
  await expect(app.locator("#fault")).toBeHidden();
  rig.underrun(3); // a storm: rigd raises audio_underruns
  await expect.poll(() => app.evaluate(() => window.__seastones.live.heartbeat.faults)).toContain("audio_underruns");
  await frames(app, 3);
  await expect(app.locator("#fault")).toBeHidden(); // the sound carries on; staff are told
  // the staff screen shows the count and the storm
  const t = await (await import("./touch.mjs")).touchSession(app);
  const box = await app.locator("#header .mark").boundingBox();
  await t.down([{ x: box.x + box.width / 2, y: box.y + box.height / 2 }]);
  await app.waitForTimeout(3300);
  await t.up();
  for (const d of rig.staffPin) await app.locator(`#staff-key-${d}`).tap();
  await app.locator("#staff-key-ok").tap();
  await expect(app.locator("#staff-h-underruns")).toHaveText("4, a storm now");
  await expect(app.locator("#staff-h-faults")).toContainText("audio_underruns");
});
