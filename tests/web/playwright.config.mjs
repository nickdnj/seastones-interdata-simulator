// Playwright for the page against the fake engine (QA-STRATEGY 3.8; TEST-PLAN 4.10).
// Chromium, headless, 1920 x 1080, every push. `make web-test` runs it.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./ui",
  timeout: 60000,
  // The whole run, so a hung page or fake engine fails the job instead of stalling it.
  globalTimeout: 20 * 60 * 1000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  workers: 2,
  reporter: [["list"]],
  globalSetup: "./ui/global-setup.mjs",
  globalTeardown: "./ui/global-teardown.mjs",
  use: {
    browserName: "chromium",
    headless: true,
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    hasTouch: true,
    reducedMotion: "no-preference",
  },
});
