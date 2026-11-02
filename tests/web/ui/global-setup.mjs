// Start one static server (src/web/serve.py) for the whole run, on a free port, serving the
// real content set and the real program listing. Each test starts its own fake engine.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

export function freePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

export async function startServe({ content = path.join(ROOT, "content"), port, extra = [] } = {}) {
  const p = port || (await freePort());
  const indexDir = mkdtempSync(path.join(os.tmpdir(), "sx-web-index-"));
  const run = mkdtempSync(path.join(os.tmpdir(), "sx-web-run-"));
  const proc = spawn("python3", [path.join(ROOT, "src/web/serve.py"), "--port", String(p), "--content", content,
    "--index-dir", indexDir, "--program", path.join(ROOT, "build/program"), "--run", run, ...extra], { stdio: ["ignore", "pipe", "pipe"] });
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("serve.py did not start")), 15000);
    proc.stdout.on("data", (d) => { if (String(d).includes("serve.py: http")) { clearTimeout(t); resolve(); } });
    proc.on("exit", (code) => reject(new Error(`serve.py exited ${code}`)));
  });
  return { proc, url: `http://127.0.0.1:${p}`, indexDir, run };
}

export default async function globalSetup() {
  if (!existsSync(path.join(ROOT, "build/program/rig.lst.json"))) {
    throw new Error("build/program/rig.lst.json missing: run `make program` first");
  }
  const s = await startServe();
  process.env.SX_WEB_URL = s.url;
  writeFileSync(path.join(os.tmpdir(), `sx-web-serve-${process.pid}.pid`), String(s.proc.pid));
}
