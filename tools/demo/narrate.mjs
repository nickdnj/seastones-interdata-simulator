#!/usr/bin/env node
// narrate.mjs: render each segment's narration with macOS `say` and measure it with ffprobe.
//   node tools/demo/narrate.mjs <workdir>   ->  <workdir>/nar-<id>.aiff, <workdir>/durations.json
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { SEGMENTS, VOICE, RATE } from "./segments.mjs";

const work = process.argv[2];
if (!work) { console.error("usage: narrate.mjs <workdir>"); process.exit(2); }
mkdirSync(work, { recursive: true });
const out = {};
for (const s of SEGMENTS) {
  const f = path.join(work, `nar-${s.id}.aiff`);
  execFileSync("say", ["-v", VOICE, "-r", String(RATE), "-o", f, s.text]);
  const dur = Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).toString().trim());
  out[s.id] = { file: f, seconds: dur, gap: s.gap };
  console.log(`${s.id.padEnd(10)} ${dur.toFixed(2)} s + ${s.gap} s`);
}
const total = Object.values(out).reduce((t, x) => t + x.seconds + x.gap + 0.5, 0);
console.log(`total about ${(total / 60).toFixed(2)} min`);
writeFileSync(path.join(work, "durations.json"), JSON.stringify(out, null, 2));
