#!/usr/bin/env node
// cpu-trace.mjs: run the fake engine's interpreter from a command script and print one
// line per instruction, for tests/web/test_fake_cpu_conformance.py to compare with the
// real CPU (`build/engine/sx-cpu`).
//
//   node cpu-trace.mjs IMAGE.json < script
//
// Script lines: `keys HEX64` (bit k = key k), `sr HEX` (the switch register) and `step N`.
// Output per instruction:
//   PC=hhhh R=hhhh,...(16) CC=h KS=hh*8 DAC=hhhh,...(16) G=hhhh
import { readFileSync } from "node:fs";
import { loadImage } from "./cpu.mjs";

const image = JSON.parse(readFileSync(process.argv[2], "utf8"));
const cpu = loadImage(image);
const hex = (v, n = 4) => v.toString(16).toUpperCase().padStart(n, "0");
const out = [];
for (const raw of readFileSync(0, "utf8").split("\n")) {
  const [cmd, arg] = raw.trim().split(/\s+/);
  if (cmd === "keys") cpu.setKeys(BigInt("0x" + arg));
  else if (cmd === "sr") cpu.sr = parseInt(arg, 16) & 0xffff;
  else if (cmd === "step") {
    for (let i = 0; i < Number(arg); i++) {
      if (!cpu.step()) {
        out.push(`FAULT ${cpu.fault.code} pc=${hex(cpu.fault.pc)} op=${hex(cpu.fault.op, 2)}`);
        process.stdout.write(out.join("\n") + "\n");
        process.exit(3);
      }
      out.push(
        `PC=${hex(cpu.pc)} R=${[...cpu.r].map((v) => hex(v)).join(",")} CC=${hex(cpu.cc, 1)} ` +
          `KS=${[...cpu.keysSeen].map((v) => hex(v, 2)).join("")} DAC=${[...cpu.dac].map((v) => hex(v)).join(",")} G=${hex(cpu.gates)}`,
      );
    }
  }
}
process.stdout.write(out.join("\n") + "\n");
