#!/usr/bin/env node
// cli.mjs: run the fake engine on its own, for developing the page without rigd.
//
//   node tests/web/fake-engine/cli.mjs [--port 7690] [--image build/program/rig.img.json]
//                                      [--content content] [--trace FILE.json [--loop]]
//
// Then serve the page (python3 src/web/serve.py) and open http://127.0.0.1:8080/.
// Type on stdin to drive it: `freeze`, `thaw`, `fault CODE`, `clear CODE`, `kill`,
// `revive`, `midi HEX64`, `audio off|on`, `keyboard off|on`. It makes no sound.
import { readFileSync } from "node:fs";
import readline from "node:readline";
import { FakeEngine } from "./engine.mjs";

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : dflt;
};

const engine = new FakeEngine({ image: opt("image"), content: opt("content") });
await engine.start(Number(opt("port", 7690)));
if (opt("trace")) engine.play(JSON.parse(readFileSync(opt("trace"), "utf8")).frames, { loop: args.includes("--loop") });
console.log(`fake engine on ${engine.url} (protocol v1, no sound)`);

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  const [cmd, arg] = line.trim().split(/\s+/);
  const actions = {
    freeze: () => engine.freeze(true),
    thaw: () => engine.freeze(false),
    fault: () => engine.fault(arg),
    clear: () => engine.clearFault(arg),
    kill: () => engine.kill(),
    revive: () => engine.revive(),
    midi: () => engine.midiKeys(BigInt("0x" + (arg || "0"))),
    audio: () => engine.setHealth({ audio_ok: arg !== "off" }),
    keyboard: () => engine.setHealth({ midi_present: arg !== "off" }),
  };
  if (actions[cmd]) { actions[cmd](); console.log(`ok ${cmd}`); }
  else if (cmd) console.log(`unknown: ${cmd}`);
});
process.on("SIGINT", async () => { await engine.stop(); process.exit(0); });
