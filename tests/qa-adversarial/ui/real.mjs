// Fixtures for the adversarial browser tests: the real page against a REAL rigd (not the fake
// engine), on the null audio device (paced, no hardware, nothing audible), one rigd per test.
//
// A known, unfixed bug is a `test.fail()` with its id (QA-ADV-nn in
// docs/qa/results/adversarial-2026-11-03.md): Playwright then fails the run if the test starts
// passing, the same contract as pytest's xfail(strict=True). Fixed bugs are plain tests.
import { test as base, expect } from "../../web/node_modules/@playwright/test/index.mjs";
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

const freePort = () => new Promise((resolve) => {
  const s = net.createServer();
  s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
});

/** Start rigd. `staffConf` seeds <data>/staff.conf (e.g. a 30 s idle timeout). */
export async function startRigd({ args = [], staffConf = null } = {}) {
  const port = await freePort();
  const tmp = mkdtempSync(path.join(os.tmpdir(), "sx-qa-adv-"));
  const data = path.join(tmp, "data");
  mkdirSync(data);
  if (staffConf) writeFileSync(path.join(data, "staff.conf"), JSON.stringify(staffConf));
  writeFileSync(path.join(tmp, "pin"), "2468\n");
  const proc = spawn("python3", ["-m", "rigd", "--port", String(port), "--audio", "null", "--no-midi", "--test-hooks",
    "--content", path.join(ROOT, "content"), "--data", data, "--staff-pin-file", path.join(tmp, "pin"), ...args],
  { cwd: ROOT, env: { ...process.env, PYTHONPATH: path.join(ROOT, "src"), PYTHONUNBUFFERED: "1" }, stdio: ["ignore", "pipe", "pipe"] });
  let log = "";
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`rigd did not start:\n${log}`)), 20000);
    const read = (d) => { log += String(d); if (log.includes("listening on")) { clearTimeout(t); resolve(); } };
    proc.stdout.on("data", read);
    proc.stderr.on("data", read);
    proc.on("exit", (code) => { clearTimeout(t); reject(new Error(`rigd exited ${code}:\n${log}`)); });
  });
  proc.removeAllListeners("exit");
  return {
    url: `ws://127.0.0.1:${port}`,
    log: () => log,
    async stop() {
      if (proc.exitCode === null) {
        proc.kill("SIGTERM");
        await new Promise((r) => { const t = setTimeout(() => { proc.kill("SIGKILL"); r(); }, 5000); proc.on("exit", () => { clearTimeout(t); r(); }); });
      }
      rmSync(tmp, { recursive: true, force: true });
    },
  };
}

export const test = base.extend({
  rigdArgs: [[], { option: true }],
  staffConf: [null, { option: true }],
  rigd: async ({ rigdArgs, staffConf }, use) => {
    const r = await startRigd({ args: rigdArgs, staffConf });
    await use(r);
    await r.stop();
  },
  app: async ({ page, rigd }, use) => {
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`${process.env.SX_WEB_URL}/?rig=${encodeURIComponent(rigd.url)}&hooks=1&dev=1`);
    await page.waitForFunction(() => window.__seastones && window.__seastones.live.connected && window.__seastones.live.state && window.__seastones.live.patch, null, { timeout: 20000 });
    await use(page);
    expect(errors, "uncaught page errors").toEqual([]);
  },
});

/** CDP touch: `pts` is the whole list of fingers down after this event. */
export async function touch(page, type, pts) {
  if (!page.__cdp) page.__cdp = await page.context().newCDPSession(page);
  await page.__cdp.send("Input.dispatchTouchEvent", { type, touchPoints: pts });
}

export async function centre(page, selector) {
  const b = await page.locator(selector).first().boundingBox();
  if (!b) throw new Error(`${selector} is not on screen`);
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}

export const go = (page, layer) => page.evaluate((l) => window.__seastones.go(l), layer);
export const layer = (page) => page.evaluate(() => window.__seastones.layer());

export { expect };
