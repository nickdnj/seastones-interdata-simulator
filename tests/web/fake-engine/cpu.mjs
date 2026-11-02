// cpu.mjs: a tiny, deterministic 7/16 interpreter for the fake engine (VS-28).
//
// It runs the real program image (`build/program/rig.img.json`) with the same three
// devices the engine has (ARCHITECTURE 5: KEYS X'20', DAC X'21', GATE X'22'), so that the
// UI tests see the PC, registers, lamps, key rows, D/A codes and gates the real engine
// would publish for the same key input. It is a test double, not an emulator: it knows
// only the opcodes rig.s uses today, and an opcode it does not know is a loud failure
// (`unknown_opcode`), never a guess.
//
// Its semantics are copied from SIMH's id16_cpu.c (the vendored file under
// src/engine/simh/Interdata/) and from src/engine/devices/id_seastones.c, and
// tests/web/test_fake_cpu_conformance.py checks it against the real CPU (`sx-cpu`)
// instruction by instruction. If the program grows an opcode this file lacks, that test
// and every fake-engine run stop with the opcode named.

export const CC_C = 8, CC_V = 4, CC_G = 2, CC_L = 1;
const MEM_BYTES = 32768;
const DEV_KEYS = 0x20, DEV_DAC = 0x21, DEV_GATE = 0x22;
const DEV_PANEL = 0x01, DEV_PIC = 0x6c; // the front panel's switches, the interval clock
const OC_MODE = 0xc0, OC_AUTO = 0x40, OC_NORMAL = 0x80;

/** Load a `seastones.image/1` object into a fresh machine. */
export function loadImage(image, { dacWordBits = 12, instrPerTick = 1000 } = {}) {
  if (!image || image.format !== "seastones.image/1") throw new Error("not a seastones.image/1");
  const mem = new Uint8Array(MEM_BYTES);
  for (const seg of image.segments) {
    let a = parseInt(seg.addr, 16);
    for (const w of seg.words) {
      const v = parseInt(w, 16);
      mem[a] = v >> 8;
      mem[a + 1] = v & 0xff;
      a += 2;
    }
  }
  const cpu = new Cpu(mem, parseInt(image.entry_pc, 16), dacWordBits, image.sha256);
  cpu.instrPerTick = instrPerTick;
  return cpu;
}

export class Cpu {
  constructor(mem, entry, dacWordBits, imageSha) {
    this.mem = mem;
    this.image = mem.slice();
    this.entry = entry;
    this.imageSha = imageSha;
    this.dacMask = (0xffff << (16 - Math.max(1, Math.min(16, dacWordBits)))) & 0xffff;
    // The operator's switch register: physical switches, so a reset leaves them alone.
    this.sr = 0;
    // Interval clock ticks, in executed instructions. 1000 is `sx-cpu`'s instruction mode
    // (one tick per instruction; id_uvc.c timer mode with sim_rtcn_init(1000)); the fake
    // engine sets its own figure for one emulated millisecond.
    this.instrPerTick = 1000;
    this.reset();
  }

  /** Power-up state: what `sx_load_image` gives (registers zero, PC at the entry). */
  reset() {
    this.mem.set(this.image);
    this.r = new Uint16Array(16);
    this.pc = this.entry;
    this.psw = 0;
    this.cc = 0;
    this.keysRows = new Uint8Array(8); // what the device offers now (keys_raw)
    this.keysSeen = new Uint8Array(8); // the last value the program read per row
    this.keysRow = 0;
    this.keysAuto = 0;
    this.dac = new Uint16Array(16);
    this.dacCh = 0;
    this.dacAuto = 0;
    this.gates = 0;
    this.srPos = 0;
    this.drMode = 0;
    // id_uvc.c's PIC, the parts the program uses: a buffer, a start command, a count that
    // goes down by one each tick and reloads from the buffer when it runs out.
    this.picBuf = 0;
    this.picRic = 0;
    this.picCic = 0;
    this.picDue = null; // instruction count at which the next tick happens
    this.picWdp = 0;
    this.picRdp = 0;
    this.instructions = 0;
    this.fault = null;
  }

  /** Key bitmap, bit k = key k (BigInt), as `sx_keys_set` takes it. */
  setKeys(bits) {
    for (let row = 0; row < 8; row++) {
      let v = 0;
      for (let b = 0; b < 8; b++) {
        if ((bits >> BigInt(row * 8 + b)) & 1n) v |= 0x80 >> b;
      }
      this.keysRows[row] = v;
    }
  }

  rh(a) { return (this.mem[a & 0x7ffe] << 8) | this.mem[(a & 0x7ffe) + 1]; }
  rb(a) { return this.mem[a & 0x7fff]; }
  wb(a, v) { this.mem[a & 0x7fff] = v & 0xff; }
  wh(a, v) { this.mem[a & 0x7ffe] = (v >> 8) & 0xff; this.mem[(a & 0x7ffe) + 1] = v & 0xff; }

  /** The halfword the panel's DATA lamps show: the instruction word at the PC. */
  word(a = this.pc) { return this.rh(a); }

  ccGL(x) { this.cc = x & 0x8000 ? CC_L : x ? CC_G : 0; }

  picSchedule() {
    // the starting instruction's own tick is charged at its fetch, before it executes
    this.picDue = this.instructions + 1 + this.instrPerTick;
  }

  /** Clock ticks that are due before the next instruction (SIMH processes events first). */
  picRun() {
    while (this.picDue !== null && this.instructions >= this.picDue) {
      this.picCic -= 1;
      if (this.picCic <= 0) {
        this.picRic = this.picBuf;
        this.picCic = this.picRic & 0x0fff;
        if ((this.picRic & 0xf000) === 0) { this.picDue = null; break; }
      }
      this.picDue += this.instrPerTick;
    }
  }

  io(dev, op, dat) {
    if (dev === DEV_PANEL) {
      if (op === "sel") { if (!this.drMode) this.srPos = 0; return 0; }
      if (op === "oc") {
        const c = dat & 0xc0;
        if (c === 0x40) { this.drMode = 1; this.srPos = 0; } else if (c === 0x80) this.drMode = 0;
        return 0;
      }
      if (op === "rd") { const t = (this.sr >> (this.srPos * 8)) & 0xff; this.srPos ^= 1; return t; }
      if (op === "rh") { const hi = (this.sr >> (this.srPos * 8)) & 0xff; this.srPos ^= 1; const lo = (this.sr >> (this.srPos * 8)) & 0xff; this.srPos ^= 1; return (hi << 8) | lo; }
      return 0; // writes go to the display register, which nothing here reads
    }
    if (dev === DEV_PIC) {
      if (op === "sel") return 0;
      if (op === "wh") { this.picWdp = 0; this.picBuf = dat & 0xffff; return 0; }
      if (op === "wd") { this.picBuf = this.picWdp ? (this.picBuf & 0xff00) | (dat & 0xff) : (this.picBuf & 0xff) | ((dat & 0xff) << 8); this.picWdp ^= 1; return 0; }
      if (op === "oc") {
        if (dat & 0x20) { // start
          this.picRic = this.picBuf;
          this.picCic = this.picRic & 0x0fff;
          this.picDue = null;
          this.picRdp = this.picWdp = 0;
          if (this.picRic & 0xf000) this.picSchedule();
        }
        return 0;
      }
      if (op === "rh") { this.picRdp = 0; return this.picCic & 0xffff; }
      if (op === "rd") { const t = this.picRdp ? this.picCic & 0xff : (this.picCic >> 8) & 0xff; this.picRdp ^= 1; return t; }
      return 0;
    }
    if (op === "sel") return dev === DEV_KEYS || dev === DEV_DAC || dev === DEV_GATE ? 0 : null;
    if (op === "rh" && (dev === DEV_KEYS)) {
      const hi = this.io(dev, "rd", 0);
      const lo = this.io(dev, "rd", 0);
      return (hi << 8) | lo;
    }
    if (dev === DEV_KEYS) {
      if (op === "oc") {
        if ((dat & OC_MODE) === OC_AUTO) this.keysAuto = 1;
        else if ((dat & OC_MODE) === OC_NORMAL) this.keysAuto = 0;
        this.keysRow = dat & 7;
        return 0;
      }
      if (op === "rd") {
        const v = this.keysRows[this.keysRow];
        this.keysSeen[this.keysRow] = v;
        if (this.keysAuto) this.keysRow = (this.keysRow + 1) & 7;
        return v;
      }
      return 0;
    }
    if (dev === DEV_DAC) {
      if (op === "oc") {
        if ((dat & OC_MODE) === OC_AUTO) this.dacAuto = 1;
        else if ((dat & OC_MODE) === OC_NORMAL) this.dacAuto = 0;
        this.dacCh = dat & 0xf;
        return 0;
      }
      if (op === "wh" || op === "wd") {
        const code = op === "wd" ? (dat & 0xff) << 8 : dat & 0xffff;
        this.dac[this.dacCh] = code & this.dacMask;
        if (this.dacAuto) this.dacCh = (this.dacCh + 1) & 0xf;
      }
      return 0;
    }
    if (dev === DEV_GATE) {
      if (op === "wh") this.gates = dat & 0xffff;
      else if (op === "wd") this.gates = ((dat & 0xff) << 8) | (this.gates & 0xff);
      return 0;
    }
    return null; // no such device
  }

  /** Execute one instruction. Returns false (and sets `fault`) on anything unknown. */
  step() {
    if (this.fault) return false;
    this.picRun();
    const oPC = this.pc;
    const ir1 = this.rh(oPC);
    const op = ir1 >> 8, r1 = (ir1 >> 4) & 0xf, r2 = ir1 & 0xf;
    const R = this.r;
    let pc = (oPC + 2) & 0xffff;
    const rx = () => {
      let ea = this.rh(pc);
      pc = (pc + 2) & 0xffff;
      if (r2) ea = (ea + R[r2]) & 0xffff;
      return ea;
    };
    const add = (a, b) => {
      const s = (a + b) & 0xffff;
      this.ccGL(s);
      if (s < b) this.cc |= CC_C;
      if ((~a ^ b) & (a ^ s) & 0x8000) this.cc |= CC_V;
      return s;
    };
    const cmp = (a, b) => {
      const sa = (a << 16) >> 16, sb = (b << 16) >> 16;
      this.cc = sa < sb ? CC_C | CC_L : sa > sb ? CC_G : 0;
      if ((a ^ b) & (~b ^ (sa - sb)) & 0x8000) this.cc |= CC_V;
    };
    const ioCC = (res) => { this.cc = res === null ? CC_V : 0; };
    const dev = () => R[r1] & 0xff;
    const devOk = (d) => this.io(d, "sel", 0) !== null;
    const rd = (kind) => { // RD/RH: zero and V when there is no such device
      const d = dev();
      if (!devOk(d)) { this.cc = CC_V; return 0; }
      this.cc = 0;
      return this.io(d, kind, 0);
    };
    const out = (kind, v) => { const d = dev(); if (!devOk(d)) { this.cc = CC_V; return; } this.io(d, kind, v); this.cc = 0; };
    const sub = (a, b) => {
      const s = (a - b) & 0xffff;
      this.ccGL(s);
      if (a < b) this.cc |= CC_C;
      if ((a ^ b) & (~b ^ s) & 0x8000) this.cc |= CC_V;
      return s;
    };
    switch (op) {
      case 0x01: { const t = R[r2]; R[r1] = pc; pc = t; break; } // BALR
      case 0x02: if (this.cc & r1) pc = R[r2]; break; // BTCR
      case 0x03: if ((this.cc & r1) === 0) pc = R[r2]; break; // BFCR
      case 0x04: R[r1] &= R[r2]; this.ccGL(R[r1]); break; // NHR
      case 0x06: R[r1] |= R[r2]; this.ccGL(R[r1]); break; // OHR
      case 0x0b: R[r1] = sub(R[r1], R[r2]); break; // SHR
      case 0x25: R[r1] = (-r2) & 0xffff; this.ccGL(R[r1]); break; // LCS
      case 0x41: { const ea = rx(); R[r1] = pc; pc = ea; break; } // BAL
      case 0x44: R[r1] &= this.rh(rx()); this.ccGL(R[r1]); break; // NH
      case 0x46: R[r1] |= this.rh(rx()); this.ccGL(R[r1]); break; // OH
      case 0x49: cmp(R[r1], this.rh(rx())); break; // CH
      case 0x4b: R[r1] = sub(R[r1], this.rh(rx())); break; // SH
      case 0x90: { // SRLS
        const v = R[r1], res = v >> r2;
        this.ccGL(res);
        if (r2 && (v >> (r2 - 1)) & 1) this.cc |= CC_C;
        R[r1] = res;
        break;
      }
      case 0x99: R[r2] = rd("rh") & 0xffff; break; // RHR
      case 0x9e: out("oc", R[r2] & 0xff); break; // OCR
      case 0xc3: this.ccGL(R[r1] & rx()); break; // THI
      case 0xc4: R[r1] &= rx(); this.ccGL(R[r1]); break; // NHI
      case 0xc7: R[r1] ^= rx(); this.ccGL(R[r1]); break; // XHI
      case 0xca: R[r1] = add(R[r1], rx()); break; // AHI
      case 0xcb: R[r1] = sub(R[r1], rx()); break; // SHI
      case 0xd4: { // CLB
        const t = R[r1] & 0xff, o = this.rb(rx());
        this.ccGL((t - o) & 0xffff);
        if (t < o) this.cc |= CC_C;
        break;
      }
      case 0x07: R[r1] ^= R[r2]; this.ccGL(R[r1]); break; // XHR
      case 0x08: R[r1] = R[r2]; this.ccGL(R[r1]); break; // LHR
      case 0x09: cmp(R[r1], R[r2]); break; // CHR
      case 0x0a: R[r1] = add(R[r1], R[r2]); break; // AHR
      case 0x24: R[r1] = r2; this.ccGL(R[r1]); break; // LIS
      case 0x26: R[r1] = add(R[r1], r2); break; // AIS
      case 0x27: R[r1] = sub(R[r1], r2); break; // SIS
      case 0x91: { // SLLS
        const raw = R[r1] << r2;
        R[r1] = raw & 0xffff;
        this.ccGL(R[r1]);
        if (r2 && raw & 0x10000) this.cc |= CC_C;
        break;
      }
      case 0x98: out("wh", R[r2]); break; // WHR
      case 0x9a: out("wd", R[r2] & 0xff); break; // WDR
      case 0x40: this.wh(rx(), R[r1]); break; // STH (no CC)
      case 0x42: { const ea = rx(); if (this.cc & r1) pc = ea; break; } // BTC
      case 0x43: { const ea = rx(); if ((this.cc & r1) === 0) pc = ea; break; } // BFC
      case 0x47: R[r1] ^= this.rh(rx()); this.ccGL(R[r1]); break; // XH
      case 0x48: R[r1] = this.rh(rx()); this.ccGL(R[r1]); break; // LH
      case 0x4a: R[r1] = add(R[r1], this.rh(rx())); break; // AH
      case 0xc8: R[r1] = rx(); this.ccGL(R[r1]); break; // LHI
      case 0xc9: cmp(R[r1], rx()); break; // CHI
      case 0xd2: this.wb(rx(), R[r1] & 0xff); break; // STB (no CC)
      case 0xd3: R[r1] = this.rb(rx()); break; // LB (LDB: no CC)
      case 0xd8: { const v = this.rh(rx()); out("wh", v); break; } // WH
      case 0xdb: { const ea = rx(); this.wb(ea, rd("rd")); break; } // RD
      case 0xde: { const v = this.rb(rx()); out("oc", v); break; } // OC
      default:
        this.fault = { code: "unknown_opcode", pc: oPC, op };
        return false;
    }
    this.pc = pc;
    this.instructions += 1;
    return true;
  }
}
