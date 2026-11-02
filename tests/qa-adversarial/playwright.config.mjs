// The adversarial browser tests (docs/qa/results/adversarial-2026-11-03.md): the real page
// against a real rigd on the null audio device. `make qa-adversarial` runs them.
import { defineConfig } from "../web/node_modules/@playwright/test/index.mjs";

export default defineConfig({
  testDir: "./ui",
  testMatch: "*.spec.mjs",
  timeout: 120000,
  globalTimeout: 15 * 60 * 1000,
  expect: { timeout: 5000 },
  fullyParallel: true,
  workers: 3,
  reporter: [["list"]],
  globalSetup: "../web/ui/global-setup.mjs",
  globalTeardown: "../web/ui/global-teardown.mjs",
  use: {
    browserName: "chromium",
    headless: true,
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    hasTouch: true,
  },
});
