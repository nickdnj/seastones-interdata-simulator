// Stop the static server this run started (only that PID).
import { readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";

export default async function globalTeardown() {
  const f = path.join(os.tmpdir(), `sx-web-serve-${process.pid}.pid`);
  try {
    process.kill(Number(readFileSync(f, "utf8")), "SIGTERM");
  } catch {
    /* already gone */
  }
  rmSync(f, { force: true });
}
