// engine.mjs: the fake engine for UI tests and UI development (VS-28, QA request 5).
//
// A deterministic WebSocket server that speaks protocol v1 (schema/protocol-v1.json) the
// way rigd will: `hello`, `state` at 60 Hz, `scope` at 30 Hz, `heartbeat` at 1 Hz, `fault`,
// `patch`, `ack`/`nack`. It records every client message.
//
// What it stands in for, and how:
//   * The 7/16 and its program: cpu.mjs runs the real image (build/program/rig.img.json)
//     with the real device semantics, checked against the real CPU by
//     tests/web/test_fake_cpu_conformance.py. PC, registers, key rows, D/A codes and gates
//     are therefore what the engine would publish for the same keys.
//   * Lamp duty cycles (PR-01, not built in the engine yet): the fraction of executed
//     instructions in each 1/60 s frame during which each address and data bit was set.
//   * The speed knob: instructions per frame = INSTR_PER_S x ratio / 60. The ratios are
//     the UX placeholders (UX 6.2) and say `calibrated: false` until PR-03.
//   * The synthesizer and the patch graph (PM-05, not built): a cable list and a
//     reachability check from the D/A and gate lines to `out.in`; the scope is a
//     deterministic saw shaped by gate 0 and D/A 0. It is a picture of the patch, not sound.
//   * rigd's session rules: touch cleared 250 ms after the page goes, mute after 10 s with
//     no page, a key held over 60 s released until let go (PLAY-8), HOME.
//
// Determinism: given the same client messages in the same ticks, every server message is
// byte-identical (tests/web/fake-engine/engine.test.mjs). With `clock: "manual"` nothing
// happens until `advance(ms)`.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "./ws.mjs";
import { loadImage } from "./cpu.mjs";
import { validate } from "./schema.mjs";
import { layoutOf, jacksOf, cablesOf, reachesOut as wallReaches } from "../../../src/web/app/wallmodel.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, "..", "..", "..");
export const DEFAULT_IMAGE = path.join(ROOT, "build", "program", "rig.img.json");
export const DEFAULT_CONTENT = path.join(ROOT, "content");
const SX_CPU = path.join(ROOT, "build", "engine", "sx-cpu");

export const TICK_HZ = 60;
const FRAMES_PER_TICK = 48000 / TICK_HZ;
/** Instructions per second at RUN: the S-4b ESTIMATE (tools/cycles, about 360 k/s). */
export const INSTR_PER_S = 360000;
const CYCLES_PER_INSTR = 11; // 250 ns cycles, about 2.8 us per instruction
const HIST_TICKS = 15; // pc_hist window: 250 ms
const HELD_KEY_MS = 60000; // PLAY-8 held-key rule
const TOUCH_CLEAR_MS = 250; // INPUT-4
const UI_ABSENT_MUTE_MS = 10000; // ARCHITECTURE 4.5
/** The fake engine's staff PIN (tests and `make web-dev` only). Override with SX_FAKE_STAFF_PIN. */
export const FAKE_STAFF_PIN = "4321";
const STAFF_TRIES = 5; // then a lockout (KP-07, QA-STRATEGY 15 item 12)
const STAFF_LOCKOUT_MS = 30000;

/** The six detents. Ratios and key-to-sound figures are UX 6.2 placeholders (PR-03). */
export const SPEEDS = [
  { id: "run", label: "RUN", ratio: 1, key_to_sound_ms: 25, calibrated: false },
  { id: "div30", label: "1/30", ratio: 1 / 30, key_to_sound_ms: 40, calibrated: false },
  { id: "div300", label: "1/300", ratio: 1 / 300, key_to_sound_ms: 150, calibrated: false },
  { id: "div3000", label: "1/3000", ratio: 1 / 3000, key_to_sound_ms: 1300, calibrated: false },
  { id: "crawl", label: "CRAWL", ratio: 1 / 30000, key_to_sound_ms: 10000, calibrated: false },
  { id: "step", label: "STEP", ratio: 0, key_to_sound_ms: null, calibrated: false },
];

/** The engine's module registry (src/toolchain/sxpatch/modules.json): ports per type. */
export const REGISTRY = (() => {
  const f = path.join(ROOT, "src", "toolchain", "sxpatch", "modules.json");
  const out = {};
  if (!existsSync(f)) return out;
  for (const m of JSON.parse(readFileSync(f, "utf8")).modules) out[m.type] = { inputs: m.inputs, outputs: m.outputs };
  return out;
})();

/** Does any voice reach the speaker on this wall? (PATCH-4; wallmodel.js) */
export function reachesOut(cables, layout) {
  return wallReaches(cables, layout);
}

/**
 * Presets from the content set: `presets/<slug>.patch.json` in the engine's format
 * (seastones.patch/1, src/toolchain/sxpatch), the single source of truth.
 */
export function loadPresets(contentDir = DEFAULT_CONTENT) {
  const dir = path.join(contentDir, "presets");
  const out = {};
  if (!existsSync(dir)) return out;
  for (const f of readdirSync(dir).sort()) {
    if (!f.endsWith(".patch.json")) continue;
    try {
      const doc = JSON.parse(readFileSync(path.join(dir, f), "utf8"));
      if (doc.schema === "seastones.patch/1" && doc.voices) out[f.replace(/\.patch\.json$/, "")] = doc;
    } catch {
      /* an unreadable preset is the validator's to report; the fake just lacks it */
    }
  }
  return out;
}

/** kiosk.conf's preset_order (the Play strip, left to right; the first is what HOME loads). */
function presetOrder(contentDir) {
  const f = path.join(contentDir, "kiosk.conf");
  if (!existsSync(f)) return [];
  const m = /^preset_order\s*=\s*(.*)$/m.exec(readFileSync(f, "utf8"));
  return m ? m[1].split(",").map((x) => x.trim()).filter(Boolean) : [];
}

/** sx_disasm for every instruction address, from the real CPU when it is built. */
function disassemble(image) {
  if (!existsSync(SX_CPU)) return {};
  const lines = ["model 716", "mem 32768", "reset"];
  const addrs = [];
  for (const seg of image.segments) {
    let a = parseInt(seg.addr, 16);
    for (const w of seg.words) {
      lines.push(`dep ${a.toString(16)} ${w}`);
      a += 2;
    }
    addrs.push([parseInt(seg.addr, 16), a - 2]);
  }
  for (const [lo, hi] of addrs) {
    if (lo < 0x1000) lines.push(`disasm ${lo.toString(16)} ${hi.toString(16)}`);
  }
  const res = spawnSync(SX_CPU, [], { input: lines.join("\n") + "\n", encoding: "utf8" });
  const map = {};
  for (const ln of (res.stdout || "").split("\n")) {
    const m = /^([0-9A-F]+):\s+(.*)$/.exec(ln.trim());
    if (m) map[m[1].padStart(4, "0")] = m[2].trim();
  }
  return map;
}

/** Symbols of an assembled image (`<name>.sym` beside `<name>.img.json`: NAME HEX per line). */
export function readSymbols(imagePath) {
  const f = imagePath.replace(/\.img\.json$/, ".sym");
  const out = {};
  if (!existsSync(f)) return out;
  for (const ln of readFileSync(f, "utf8").split("\n")) {
    const [name, hex] = ln.trim().split(/\s+/);
    if (name && hex) out[name] = parseInt(hex, 16);
  }
  return out;
}

/** The channel map the program carries (rig.s MAP: voices, gate mode, pitch and gate channels). */
export function readMap(cpu, sym) {
  const base = sym.MAP ?? 0x1100;
  const voices = Math.max(1, Math.min(8, cpu.rh(base)));
  const gmode = cpu.rh(base + 2);
  const pch = [], gch = [];
  for (let v = 0; v < voices; v++) {
    pch.push(cpu.rh(base + 4 + 2 * v) & 0xf); // a D/A command byte: the channel in the low bits
    const g = cpu.rh(base + 20 + 2 * v);
    gch.push(gmode ? g & 0xf : (g & 0xff) << 8); // a D/A channel, or the latch mask (WDR writes the high byte)
  }
  return { voices, gmode, pch, gch };
}

const hex4 = (v) => v.toString(16).toUpperCase().padStart(4, "0");
const r4 = (x) => Math.round(x * 10000) / 10000;
const bitsOf = (v) => Array.from({ length: 16 }, (_, b) => (v >> (15 - b)) & 1);

export class FakeEngine {
  constructor(opts = {}) {
    // voices: 8 is the eight-voice image (latch-8 map); the default is the floor's four
    const imagePath = opts.image || (opts.voices === 8 ? DEFAULT_IMAGE.replace(/rig\.img\.json$/, "rig8.img.json") : DEFAULT_IMAGE);
    if (!existsSync(imagePath)) {
      throw new Error(`fake engine: ${imagePath} is missing. Run \`make program\` first.`);
    }
    this.imageDoc = JSON.parse(readFileSync(imagePath, "utf8"));
    // One interval-clock tick per emulated millisecond at the estimated instruction rate.
    this.cpu = loadImage(this.imageDoc, { instrPerTick: Math.round(INSTR_PER_S / 1000) });
    this.sym = readSymbols(imagePath);
    this.map = readMap(this.cpu, this.sym);
    this.loopAddr = this.cpu.entry; // replaced below by the first branch target if found
    this.instrAddrs = new Set();
    this.disasm = opts.disasm || disassemble(this.imageDoc);
    for (const a of Object.keys(this.disasm)) this.instrAddrs.add(parseInt(a, 16));
    this.loopAddr = opts.loopAddr ?? this.findLoop();
    // Presets for this image's channel map only: as many voices, and gates where it has them.
    const content = opts.content || DEFAULT_CONTENT;
    const fits = (d) => d.voices.count === this.map.voices && String(d.voices.gate || "").startsWith("gate.") === !this.map.gmode;
    this.presets = Object.fromEntries(Object.entries(opts.presets || loadPresets(content)).filter(([, d]) => fits(d)));
    const order = presetOrder(content).filter((x) => this.presets[x]);
    this.defaultPreset = opts.defaultPreset || order[0] || Object.keys(this.presets)[0] || null;
    this.clock = opts.clock || "real";
    this.strict = opts.strict !== false;
    this.log = [];
    this.invalid = [];
    this.clients = new Set();
    this.accepting = true;
    this.overrides = {};
    this.script = null;
    this.health = { audio_ok: true, midi_present: true };
    this.stages = { computer: true, program: true, synth: true, output: true };
    this.faults = [];
    // Staff (KP-07 to KP-09). The fake's PIN is a test value, not the station's: rigd keeps the
    // real one hashed on /data, never in the repo.
    this.staffPin = opts.staffPin || process.env.SX_FAKE_STAFF_PIN || FAKE_STAFF_PIN;
    this.staffTries = STAFF_TRIES;
    this.staffLockUntil = 0;
    this.settings = { idle_timeout_s: 90, reduced_motion: false, review_mode: false, attract_sound: false, ...(opts.settings || {}) };
    this.staffCfg = { ceiling_dba: 72, ceiling_max_dba: 78, quiet_hours: { from: "12:00", to: "14:00", dba: 66 }, muted: false };
    this.staffLog = []; // what staff did, for tests: [type, args]
    this.restartTicks = 0;
    this.underruns = 0;
    this.reviveAtTick = null;
    this.protocolVersion = opts.protocolVersion || 1;
    this.statesToDrop = 0;
    this.reset(true);
  }

  /** Put a preset's modules and cables on the wall (null: an empty wall over no modules). */
  loadPatch(slug) {
    const doc = slug ? this.presets[slug] : null;
    this.base = doc || { schema: "seastones.patch/1", slug: "empty", voices: { count: this.map.voices }, modules: [], cables: [] };
    this.layout = layoutOf(this.base, REGISTRY);
    this.jackIds = new Set(jacksOf(this.layout).map((j) => j.id));
    this.jackKind = new Map(jacksOf(this.layout).map((j) => [j.id, j.kind]));
    this.cables = this.base.wall ? this.base.wall.map((c) => ({ ...c })) : cablesOf(this.base, this.layout);
    this.preset = doc ? slug : null;
    // The patch says what the 7/16 plays with it (sxpatch `program`): rigd sets the switch
    // register to match. Switches 4-7 transpose (8-15 mean -8 to -1), 8-11 pick the
    // routine, 12-15 its variant (rig.s).
    const pr = this.base.program || {};
    const routine = { play: 0, rhythm: 1, steps: 2, arpeggio: 3 }[pr.routine || "play"] ?? 0;
    this.cpu.sr = (((pr.transpose || 0) & 0xf) << 8) | (routine << 4) | ((pr.variant || 0) & 0xf);
  }

  /** The scan loop's top: the target of the program's first unconditional branch. */
  findLoop() {
    const mem = this.cpu.mem;
    for (let a = this.cpu.entry; a < 0x1000; a += 2) {
      if (mem[a] === 0x43 && (mem[a + 1] & 0xf0) === 0) return (mem[a + 2] << 8) | mem[a + 3];
    }
    return this.cpu.entry;
  }

  reset(first = false) {
    // HOME restores 0 dB (the staff ceiling) and unmuted (AUDIO-3, as rigd)
    this.volume = { db: 0, muted: false };
    this.cpu.reset();
    this.speed = "run";
    this.halted = false;
    this.acc = 0;
    this.touchBits = 0n;
    this.midiBits = 0n;
    this.heldSince = new Map(); // bit -> ms when it went down
    this.heldIgnored = new Set(); // bits past 60 s, masked until released
    this.loadPatch(this.defaultPreset);
    this.hist = [];
    this.laps = [];
    this.stepsPending = 0;
    if (first) {
      this.seq = 0;
      this.tickNo = 0;
      this.nowMs = 0;
      this.frames = 0;
      this.cycles = 0;
      this.phase = 0;
      this.env = 0;
      this.lastClientMs = 0;
      this.touchClearAt = null;
    }
  }

  // ---------------------------------------------------------------- server

  async start(port = 0) {
    const { server, port: p } = await createServer({
      port,
      accept: () => this.accepting,
      onConnection: (conn) => this.connected(conn),
    });
    this.server = server;
    this.port = p;
    this.url = `ws://127.0.0.1:${p}`;
    if (this.clock === "real") this.timer = setInterval(() => this.tick(), 1000 / TICK_HZ);
    return this;
  }

  async stop() {
    clearInterval(this.timer);
    for (const c of this.clients) c.kill();
    this.clients.clear();
    if (this.server) await new Promise((r) => this.server.close(() => r()));
  }

  connected(conn) {
    this.clients.add(conn);
    this.touchClearAt = null;
    conn.handler = (text) => this.receive(conn, text);
    conn.closer = () => {
      this.clients.delete(conn);
      if (!this.clients.size) this.touchClearAt = this.nowMs + TOUCH_CLEAR_MS;
    };
    conn.staff = false;
    this.send(conn, this.helloMsg());
    this.send(conn, this.settingsMsg());
    this.send(conn, this.patchMsg());
    this.send(conn, this.heartbeatMsg());
    this.send(conn, this.stateMsg(this.lastTick || this.compute(0)));
  }

  send(conn, msg) {
    // A rigd from another protocol version (a mismatch test): every message says so.
    if (this.protocolVersion !== 1) { conn.send(JSON.stringify({ ...msg, v: this.protocolVersion })); return; }
    if (this.strict) {
      const errs = validate("server", msg);
      if (errs.length) throw new Error(`fake engine sent an invalid ${msg.t}: ${errs.join("; ")}`);
    }
    conn.send(JSON.stringify(msg));
  }

  broadcast(msg) {
    for (const c of this.clients) this.send(c, msg);
  }

  receive(conn, text) {
    let msg;
    try { msg = JSON.parse(text); } catch { msg = null; }
    this.log.push({ tick: this.tickNo, text });
    const errs = msg ? validate("client", msg) : ["not JSON"];
    if (errs.length) {
      this.invalid.push({ text, errs });
      if (msg && Number.isInteger(msg.id) && msg.id > 0) this.send(conn, { v: 1, t: "nack", id: msg.id, code: "bad_args" });
      return;
    }
    this.lastClientMs = this.nowMs;
    const ok = () => this.send(conn, { v: 1, t: "ack", id: msg.id });
    const no = (code) => this.send(conn, { v: 1, t: "nack", id: msg.id, code });
    switch (msg.t) {
      case "keys.touch":
        this.touchBits = BigInt("0x" + msg.bits);
        return;
      case "machine.speed":
        this.speed = msg.position;
        this.acc = 0;
        return ok();
      case "machine.step":
        if (this.speed !== "step") return no("busy");
        this.stepsPending += 1;
        return ok();
      // the visitor volume, dB below the staff ceiling, and the visitor's own mute (AUDIO-3,
      // KP-06; rigd's audio.volume and audio.mute, reported back in state.volume)
      case "audio.volume":
        this.volume = { ...this.volume, db: msg.db };
        return ok();
      case "audio.mute":
        this.volume = { ...this.volume, muted: msg.on };
        ok();
        return this.broadcast(this.heartbeatMsg());
      case "machine.home":
        this.reset();
        this.broadcast(this.heartbeatMsg());
        this.broadcast(this.patchMsg());
        return ok();
      case "patch.connect": {
        if (!this.jackIds.has(msg.from) || !this.jackIds.has(msg.to) || msg.from === msg.to) return no("bad_args");
        // as rigd refuses (one cable per engine input): output to input only, either way round,
        // and never a second cable into an input that already has one
        const isOut = (j) => this.jackKind.get(j) !== "in";
        if (isOut(msg.from) === isOut(msg.to)) return no("bad_args");
        const [from, to] = isOut(msg.from) ? [msg.from, msg.to] : [msg.to, msg.from];
        const dup = this.cables.some((c) => c.from === from && c.to === to);
        if (!dup && this.cables.some((c) => c.to === to || c.from === to)) return no("bad_args");
        if (!dup) this.cables.push({ from, to });
        this.preset = null;
        ok();
        return this.broadcast(this.patchMsg());
      }
      case "patch.disconnect": {
        const i = this.cables.findIndex((c) => (c.from === msg.from && c.to === msg.to) || (c.from === msg.to && c.to === msg.from));
        if (i < 0) return no("bad_args");
        this.cables.splice(i, 1);
        this.preset = null;
        ok();
        return this.broadcast(this.patchMsg());
      }
      case "patch.load":
        if (!this.presets[msg.slug]) return no("bad_args");
        this.loadPatch(msg.slug);
        ok();
        return this.broadcast(this.patchMsg());
      default:
        if (msg.t.startsWith("staff.")) return this.staff(conn, msg, ok, no);
        return no("unknown");
    }
  }

  /** The staff commands (KP-07 to KP-09, CT-07). Every one but staff.auth needs a session. */
  staff(conn, msg, ok, no) {
    const reply = (extra = {}) => this.send(conn, this.staffMsg(conn, extra));
    if (msg.t === "staff.auth") {
      if (this.nowMs < this.staffLockUntil) { no("not_staff"); return reply(); }
      if (msg.pin !== this.staffPin) {
        this.staffTries -= 1;
        if (this.staffTries <= 0) { this.staffLockUntil = this.nowMs + STAFF_LOCKOUT_MS; this.staffTries = STAFF_TRIES; }
        no("not_staff");
        return reply();
      }
      this.staffTries = STAFF_TRIES;
      conn.staff = true;
      ok();
      return reply();
    }
    if (!conn.staff) return no("not_staff");
    this.staffLog.push([msg.t, { ...msg, v: undefined, t: undefined, id: undefined }]);
    const settingsChanged = () => this.broadcast(this.settingsMsg());
    switch (msg.t) {
      case "staff.close":
        conn.staff = false;
        ok();
        return reply();
      case "staff.ceiling":
        this.staffCfg.ceiling_dba = Math.min(msg.dba, this.staffCfg.ceiling_max_dba);
        ok();
        return reply();
      case "staff.quiet_hours":
        this.staffCfg.quiet_hours = { from: msg.from, to: msg.to, dba: Math.min(msg.dba, this.staffCfg.ceiling_dba) };
        ok();
        return reply();
      case "staff.mute":
        this.staffCfg.muted = msg.on;
        ok();
        reply();
        return this.broadcast(this.heartbeatMsg());
      case "staff.test_tone":
        ok(); // rigd would play its tone through the limiter; the fake makes no sound
        return reply();
      case "staff.idle_timeout":
        this.settings.idle_timeout_s = msg.s;
        ok();
        return settingsChanged();
      case "staff.attract_sound":
        this.settings.attract_sound = msg.on;
        ok();
        return settingsChanged();
      case "staff.reduced_motion":
        this.settings.reduced_motion = msg.on;
        ok();
        return settingsChanged();
      case "staff.review_mode":
        this.settings.review_mode = msg.on;
        ok();
        return settingsChanged();
      case "staff.save_preset": {
        const slug = `staff-${String(Object.keys(this.presets).filter((k) => k.startsWith("staff-")).length + 1).padStart(2, "0")}`;
        // the live wall over its base patch's modules (rigd writes the engine-format pair)
        this.presets[slug] = { ...this.base, slug, wall: this.cables.map((c) => ({ ...c })) };
        ok();
        return reply({ saved: slug });
      }
      case "staff.restart":
        ok();
        if (msg.what === "computer") {
          // reload the image: the program stage drops for a second, then the loop runs again
          this.cpu.reset();
          this.restartTicks = TICK_HZ;
          this.setStages({ program: false });
        } else {
          // the whole stack: every socket drops, rigd is back two seconds later
          this.reviveAtTick = this.tickNo + 2 * TICK_HZ;
          this.kill();
        }
        return undefined;
      default:
        return no("unknown");
    }
  }

  settingsMsg() {
    return { v: 1, t: "settings", ...this.settings };
  }

  staffMsg(conn, extra = {}) {
    const lock = Math.min(STAFF_LOCKOUT_MS / 1000, Math.max(0, Math.ceil(Math.round(this.staffLockUntil - this.nowMs) / 1000)));
    const m = { v: 1, t: "staff", authed: !!conn.staff, tries_left: this.staffTries, lockout_s: lock };
    if (conn.staff) m.settings = { ...this.staffCfg, quiet_hours: { ...this.staffCfg.quiet_hours } };
    return { ...m, ...extra };
  }

  // ---------------------------------------------------------------- control API (tests)

  /** Client messages as received. `dedupe` folds the 4 Hz keys.touch refresh repeats. */
  recorded({ dedupe = false } = {}) {
    const out = [];
    for (const { text } of this.log) {
      if (dedupe && out.length && out[out.length - 1] === text && text.includes('"keys.touch"')) continue;
      out.push(text);
    }
    return out;
  }
  messages(type) { return this.recorded().map((t) => JSON.parse(t)).filter((m) => !type || m.t === type); }
  clearRecorded() { this.log = []; this.invalid = []; }

  /** HALT: the CPU stops; state keeps flowing, unchanged (PLAY-3). */
  freeze(on = true) { this.halted = on; }
  /** The physical keyboard (MIDI source), bit k = key k. */
  midiKeys(bits) { this.midiBits = BigInt(bits); }
  /** Fields merged over every computed state until cleared (scripted states). */
  override(partial) { this.overrides = { ...this.overrides, ...partial }; }
  clearOverrides() { this.overrides = {}; }
  /** A list of state overrides, one per tick; `loop` repeats it. */
  play(frames, { loop = false } = {}) { this.script = { frames, loop, i: 0 }; }
  setHealth(h) { this.health = { ...this.health, ...h }; this.broadcast(this.heartbeatMsg()); }
  /** Late audio callbacks (KIOSK-5): `n` more; a storm raises audio_underruns (staff only). */
  underrun(n = 1) { this.underruns += n; if (n >= 3) this.fault("audio_underruns", `audio_underruns · ${this.underruns} late callbacks`); else this.broadcast(this.heartbeatMsg()); }
  /** The USB-MIDI keyboard unplugged (rigd: midi_absent raised) and plugged back in. */
  unplugKeyboard() { this.health.midi_present = false; this.fault("midi_absent"); }
  replugKeyboard() { this.health.midi_present = true; this.clearFault("midi_absent"); }
  setStages(s) { this.stages = { ...this.stages, ...s }; this.broadcast(this.heartbeatMsg()); }
  fault(code, staffLine = code.replace(/_/g, " ")) {
    if (!this.faults.includes(code)) this.faults.push(code);
    this.broadcast({ v: 1, t: "fault", code, staff_line: staffLine, since: this.frames });
    this.broadcast(this.heartbeatMsg());
  }
  clearFault(code) {
    this.faults = this.faults.filter((f) => f !== code);
    this.broadcast({ v: 1, t: "fault", code, staff_line: code.replace(/_/g, " "), since: this.frames, cleared: true });
    this.broadcast(this.heartbeatMsg());
  }
  /** The next `n` state snapshots are computed (seq moves on) but never sent: a gap. */
  dropStates(n) { this.statesToDrop = n; }
  /** Send every client a snapshot older than the last one (a reordered message). */
  sendStale(fields = {}) {
    const st = this.stateMsg(this.lastTick || this.compute(0));
    this.seq -= 1; // stateMsg took a number; this snapshot pretends to be from the past
    this.broadcast({ ...st, ...fields, seq: Math.max(0, st.seq - 5) });
  }
  /** A network blip: every socket drops, rigd keeps running and accepts the reconnect. */
  blip() { for (const c of [...this.clients]) c.kill(); }
  /** rigd killed: every socket drops with no close frame and nothing answers. */
  kill() { this.accepting = false; for (const c of [...this.clients]) c.kill(); }
  /** rigd restarted by systemd. */
  revive() { this.accepting = true; this.reset(true); }
  /** Manual clock: run `ms` of ticks. */
  advance(ms) { const n = Math.round((ms * TICK_HZ) / 1000); for (let i = 0; i < n; i++) this.tick(); }

  // ---------------------------------------------------------------- the machine

  keyBits() {
    const now = this.nowMs;
    let bits = (this.touchBits | this.midiBits) & ((1n << 64n) - 1n);
    for (let k = 0; k < 64; k++) {
      const m = 1n << BigInt(k);
      if (bits & m) {
        if (!this.heldSince.has(k)) this.heldSince.set(k, now);
        else if (now - this.heldSince.get(k) > HELD_KEY_MS) this.heldIgnored.add(k);
      } else {
        this.heldSince.delete(k);
        this.heldIgnored.delete(k);
      }
      if (this.heldIgnored.has(k)) bits &= ~m;
    }
    return bits;
  }

  /** Run one frame's worth of instructions and return the raw numbers for `state`. */
  compute(n) {
    const cpu = this.cpu;
    const addrSum = new Float64Array(16), dataSum = new Float64Array(16);
    const hist = new Map();
    let laps = 0, executed = 0;
    for (let i = 0; i < n; i++) {
      const pc = cpu.pc, w = cpu.word(pc);
      // Count an instruction only once it has executed: an opcode the interpreter does
      // not know stops here, and its lamps must not push a duty fraction above 1.
      if (!cpu.step()) break;
      for (let b = 0; b < 16; b++) {
        addrSum[b] += (pc >> (15 - b)) & 1;
        dataSum[b] += (w >> (15 - b)) & 1;
      }
      hist.set(pc, (hist.get(pc) || 0) + 1);
      if (pc === this.loopAddr) laps += 1;
      executed += 1;
    }
    return { executed, addrSum, dataSum, hist, laps };
  }

  tick() {
    this.tickNo += 1;
    this.nowMs = (this.tickNo * 1000) / TICK_HZ;
    if (this.touchClearAt !== null && this.nowMs >= this.touchClearAt) { this.touchBits = 0n; this.touchClearAt = null; }
    if (this.reviveAtTick !== null && this.tickNo >= this.reviveAtTick) { this.reviveAtTick = null; this.revive(); }
    if (this.restartTicks > 0 && --this.restartTicks === 0) this.setStages({ program: true });
    this.muted = this.staffCfg.muted || this.volume.muted || (!this.clients.size && this.nowMs - this.lastClientMs > UI_ABSENT_MUTE_MS);
    this.cpu.setKeys(this.keyBits());

    let n = 0;
    const sp = SPEEDS.find((s) => s.id === this.speed);
    if (!this.halted && !this.cpu.fault) {
      if (this.speed === "step") { n = this.stepsPending; this.stepsPending = 0; }
      else { this.acc += (INSTR_PER_S * sp.ratio) / TICK_HZ; n = Math.floor(this.acc); this.acc -= n; }
    } else this.stepsPending = 0;
    const res = this.compute(n);
    if (this.cpu.fault && !this.faults.includes("program_stalled")) this.fault("program_stalled", `program_stalled · unknown opcode at ${hex4(this.cpu.fault.pc)}`);
    this.frames += FRAMES_PER_TICK;
    this.cycles += res.executed * CYCLES_PER_INSTR;
    // The heat band shows where the last 250 ms of running went; a frame that ran nothing
    // (halted, STEP between touches) leaves it as it was rather than fading it out.
    if (res.executed > 0) {
      this.hist.push(res.hist);
      if (this.hist.length > HIST_TICKS) this.hist.shift();
    }
    this.laps.push(res.laps);
    if (this.laps.length > TICK_HZ) this.laps.shift();
    this.lastTick = res;

    if (this.clients.size) {
      const st = this.stateMsg(res);
      if (this.statesToDrop > 0) this.statesToDrop -= 1;
      else this.broadcast(st);
      if (this.tickNo % 2 === 0) this.broadcast(this.scopeMsg());
      if (this.tickNo % TICK_HZ === 0) this.broadcast(this.heartbeatMsg());
    }
  }

  // ---------------------------------------------------------------- messages

  helloMsg() {
    return {
      v: 1,
      t: "hello",
      engine_build: "fake-engine (tests/web/fake-engine, VS-28)",
      image_sha256: this.imageDoc.sha256,
      listing_id: this.imageDoc.sha256,
      capabilities: {
        speeds: SPEEDS.map((s) => ({ ...s })),
        voices: this.map.voices,
        dac: { word_bits: 12, range_v: 10.24 },
        channel_map: this.voices > 4 ? "eight-voice" : "default",
        jacks: jacksOf(this.layout).map((j) => j.id),
      },
      disasm: this.disasm,
    };
  }

  patchMsg() {
    return {
      v: 1,
      t: "patch",
      cables: this.cables.map((c) => ({ from: c.from, to: c.to })),
      reaches_out: reachesOut(this.cables, this.layout),
      layout: this.layout,
      preset: this.preset,
    };
  }

  heartbeatMsg() {
    const audio = this.health.audio_ok && !this.faults.includes("audio_device_missing");
    return {
      v: 1,
      t: "heartbeat",
      engine_alive: !this.faults.includes("program_stalled") && !this.faults.includes("engine_load_failed"),
      audio_ok: audio,
      midi_present: this.health.midi_present,
      faults: [...this.faults],
      muted: !!this.muted || this.staffCfg.muted || this.volume.muted,
      lat_p95: 18.5,
      underruns: this.underruns,
      stages: {
        computer: this.stages.computer && !this.faults.includes("engine_load_failed"),
        program: this.stages.program && !this.faults.some((f) => ["program_stalled", "image_missing", "image_hash_mismatch"].includes(f)),
        synth: this.stages.synth && !this.faults.includes("dsp_fault"),
        output: this.stages.output && audio,
      },
    };
  }

  stateMsg(res) {
    const cpu = this.cpu;
    const exact = this.halted || this.speed === "crawl" || this.speed === "step" || res.executed === 0;
    const lamps = exact
      ? { addr: bitsOf(cpu.pc), data: bitsOf(cpu.word()), exact: true }
      : {
          addr: Array.from(res.addrSum, (s) => r4(s / res.executed)),
          data: Array.from(res.dataSum, (s) => r4(s / res.executed)),
          exact: false,
        };
    const total = new Map();
    let all = 0;
    for (const h of this.hist) for (const [a, c] of h) { total.set(a, (total.get(a) || 0) + c); all += c; }
    const pcHist = {};
    for (const a of [...total.keys()].sort((x, y) => x - y)) pcHist[hex4(a)] = r4(total.get(a) / all);
    const lapsPerS = this.laps.reduce((s, x) => s + x, 0) * (TICK_HZ / Math.max(1, this.laps.length));
    let state = {
      v: 1,
      t: "state",
      seq: ++this.seq,
      frames: this.frames,
      cycles: this.cycles,
      pc: cpu.pc,
      psw: cpu.psw,
      r: [...cpu.r],
      cc: cpu.cc,
      dr: 0,
      sr: cpu.sr,
      keys_raw: [...cpu.keysRows],
      keys_seen: [...cpu.keysSeen],
      dac: [...cpu.dac],
      gates: cpu.gates,
      // The mono program's one voice: gate line 0 and the note it last sent (R6).
      watch: { voices: this.voiceNotes() },
      pc_hist: pcHist,
      lamps,
      speed: this.speed,
      halted: this.halted,
      waiting: false,
      muted: !!this.muted || this.staffCfg.muted,
      faults: [...this.faults],
      scan_hz: Math.round(lapsPerS),
      volume: { ...this.volume },
    };
    if (this.script) {
      const s = this.script;
      if (s.i < s.frames.length) state = { ...state, ...s.frames[s.i++] };
      if (s.i >= s.frames.length) { if (s.loop) s.i = 0; else this.script = null; }
    }
    return { ...state, ...this.overrides };
  }

  /**
   * Each voice as an observer of the machine sees it, through the channel map in the
   * program's own memory: its gate (a D/A channel above 2.5 V, or a gate-latch line) and the
   * note whose pitch-table number its pitch channel holds.
   */
  voiceStates() {
    const cpu = this.cpu, m = this.map;
    const out = [];
    for (let v = 0; v < m.voices; v++) {
      const gate = m.gmode ? cpu.dac[m.gch[v]] >= 0x4000 : (cpu.gates & m.gch[v]) !== 0;
      out.push({ gate, pch: m.pch[v], code: cpu.dac[m.pch[v]] });
    }
    return out;
  }

  voiceNotes() {
    return this.voiceStates().map((v) => (v.gate ? this.noteOf(v.code) : null));
  }

  /** The note (MIDI numbering) whose pitch-table entry is this D/A code, or null. */
  noteOf(code) {
    if (!this.pitchIndex) {
      this.pitchIndex = new Map();
      const base = this.sym.PITCH ?? 0x1000;
      for (let n = 127; n >= 0; n--) this.pitchIndex.set(this.cpu.rh(base + 2 * n) & this.cpu.dacMask, n);
    }
    const n = this.pitchIndex.get(code & this.cpu.dacMask);
    return n === undefined ? null : n;
  }

  scopeMsg() {
    // A picture of the patch, not sound: gate 0 with D/A 0's pitch through an envelope,
    // and nothing at all when no path reaches the speaker or the engine is muted.
    if (this.halted && this.lastScope) return { ...this.lastScope, seq: this.seq };
    const sounding = this.voiceStates().find((v) => v.gate);
    const on = !!sounding && reachesOut(this.cables, this.layout) && !this.muted;
    this.env = on ? Math.min(1, this.env + 0.25) : this.env * 0.6;
    if (this.env < 0.002) this.env = 0;
    const code = (sounding ? this.cpu.dac[sounding.pch] : this.cpu.dac[this.map.pch[0]]) >> 4;
    const volts = (code * 10.24) / 4096;
    const cycles = 2 + volts * 1.2; // cycles across the 512 points, rising with pitch
    this.phase = (this.phase + 0.137) % 1;
    const pts = new Array(512);
    for (let i = 0; i < 512; i++) {
      const x = ((i / 512) * cycles + this.phase) % 1;
      const saw = 2 * x - 1;
      const soft = saw * 0.75 + Math.sin(2 * Math.PI * x) * 0.25;
      pts[i] = r4(Math.max(-1, Math.min(1, soft * 0.8 * this.env)));
    }
    this.lastScope = { v: 1, t: "scope", seq: this.seq, points: pts };
    return this.lastScope;
  }
}
