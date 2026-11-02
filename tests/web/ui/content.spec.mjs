// CT-01: the page modules over the content index. A broken file is a visible error card in
// its place and the station carries on (CNT-04, CONT-6); an index that cannot be read is
// an honest content-down screen, never built-in copy (no demo fallback).
import { test, expect } from "@playwright/test";
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FakeEngine } from "../fake-engine/engine.mjs";
import { startServe } from "./global-setup.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

test("a broken story file becomes an error card in its place; the other screens and the station carry on (CNT-04, CONT-6)", async ({ page }) => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sx-content-"));
  cpSync(path.join(ROOT, "content"), dir, { recursive: true });
  const f = path.join(dir, "screens/03-jersey-city.md");
  writeFileSync(f, readFileSync(f, "utf8").replace(/^status: ready\n/m, "").replace(/^title: .*\n/m, "this line is not a header\n"));
  const serve = await startServe({ content: dir });
  const rig = new FakeEngine();
  await rig.start(0);
  try {
    await page.goto(`${serve.url}/?rig=${encodeURIComponent(rig.url)}&hooks=1`);
    await page.waitForFunction(() => window.__seastones && window.__seastones.live.connected);
    await page.evaluate(() => window.__seastones.go("story"));
    await expect(page.locator("#layer-story .dot")).toHaveCount(6);
    await page.locator("#layer-story .dot").nth(2).tap();
    await expect(page.locator("#story-text")).toHaveClass(/error-card/);
    await expect(page.locator("#story-text")).toContainText("This part of the story is being fixed.");
    await page.locator("#layer-story .dot").nth(3).tap();
    await expect(page.locator("#story-text h1")).toHaveText("An Interdata 7/16");
    // the rest of the station works
    await page.evaluate(() => window.__seastones.go("play"));
    await expect(page.locator("#station-1")).toBeVisible();
  } finally {
    await rig.stop();
    serve.proc.kill("SIGTERM");
  }
});

test("an index that cannot be read shows the content-down screen and nothing invented (CONT-6, KIOSK-4)", async ({ page }) => {
  const serve = await startServe({ extra: ["--no-build"] });
  try {
    await page.goto(`${serve.url}/`);
    await expect(page.locator(".content-down")).toBeVisible();
    await expect(page.locator(".content-down")).toContainText("did not load");
    await expect(page.locator(".content-down .staffline")).toContainText("HTTP 503");
    expect(await page.locator(".layer.on").count()).toBe(0);
  } finally {
    serve.proc.kill("SIGTERM");
  }
});

test("changing a visitor word is a content edit only: the page shows the new word (CNT-01 page half)", async ({ page }) => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sx-content-"));
  cpSync(path.join(ROOT, "content"), dir, { recursive: true });
  const f = path.join(dir, "captions/attract.md");
  writeFileSync(f, readFileSync(f, "utf8").replace("text: Play the keys", "text: Press a key"));
  const serve = await startServe({ content: dir });
  const rig = new FakeEngine();
  await rig.start(0);
  try {
    await page.goto(`${serve.url}/?rig=${encodeURIComponent(rig.url)}&hooks=1`);
    await expect(page.locator("#attract-pill")).toContainText("Press a key");
  } finally {
    await rig.stop();
    serve.proc.kill("SIGTERM");
  }
});
