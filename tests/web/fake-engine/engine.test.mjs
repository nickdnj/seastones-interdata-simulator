// engine.test.mjs: the fake engine's own acceptance tests (VS-28; UI-05, UI-34, ENG-10).
//
//   node --test tests/web/fake-engine/engine.test.mjs
//
// Needs build/program/rig.img.json (`make program`).
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { FakeEngine, SPEEDS, reachesOut, DEFAULT_IMAGE } from "./engine.mjs";
import { validate, check, SCHEMA, clientTypes } from "./schema.mjs";

/** A scripted client: connect, run a script of [tick, message] pairs, collect everything.
 * The socket and the server are always closed, so a throw fails the test instead of
 * leaving the event loop alive (which is how a broken interpreter used to hang the run). */
async function scriptedRun(script, ticks = 240, opts = {}) {
  const eng = new FakeEngine({ clock: "manual", ...opts });
  await eng.start(0);
  const ws = new WebSocket(eng.url);
  const got = [];
  try {
    ws.onmessage = (e) => got.push(e.data);
    await withTimeout(new Promise((r) => (ws.onopen = r)), 5000, "websocket open");
    const flush = () => new Promise((r) => setTimeout(r, 15));
    await flush();
    let i = 0;
    for (let t = 1; t <= ticks; t++) {
      while (i < script.length && script[i][0] === t) { ws.send(JSON.stringify(script[i][1])); i++; }
      if (i > 0 && script[i - 1][0] === t) await flush();
      eng.advance(1000 / 60);
    }
    await flush();
  } finally {
    ws.close();
    await eng.stop();
  }
  return { server: got, client: eng.recorded(), invalid: eng.invalid, engine: eng };
}

function withTimeout(p, ms, what) {
  let t;
  return Promise.race([
    p.finally(() => clearTimeout(t)),
    new Promise((_, rej) => { t = setTimeout(() => rej(new Error(`timed out: ${what}`)), ms); }),
  ]);
}

/** Symbols of the assembled program (build/program/rig.sym: `NAME HEX` per line). */
function symbols() {
  const out = {};
  for (const ln of readFileSync(DEFAULT_IMAGE.replace(/\.img\.json$/, ".sym"), "utf8").split("\n")) {
    const [name, hex] = ln.trim().split(/\s+/);
    if (name && hex) out[name] = parseInt(hex, 16);
  }
  return out;
}

/** The shipped image with one word replaced (a planted opcode the interpreter lacks). */
function plantedImage(addr, word) {
  const doc = JSON.parse(readFileSync(DEFAULT_IMAGE, "utf8"));
  for (const seg of doc.segments) {
    const a = parseInt(seg.addr, 16);
    seg.words = seg.words.map((w, i) => (a + 2 * i === addr ? word : w));
  }
  const dir = mkdtempSync(path.join(tmpdir(), "sx-fake-"));
  const file = path.join(dir, "planted.img.json");
  writeFileSync(file, JSON.stringify(doc));
  return file;
}

const SCRIPT = [
  [5, { v: 1, t: "keys.touch", bits: "0000000000001000" }],
  [30, { v: 1, t: "machine.speed", id: 1, position: "div300" }],
  [60, { v: 1, t: "keys.touch", bits: "0000000000000000" }],
  [80, { v: 1, t: "machine.speed", id: 2, position: "step" }],
  [90, { v: 1, t: "machine.step", id: 3 }],
  [100, { v: 1, t: "patch.disconnect", id: 4, from: "busl.out", to: "out.l" }],
  [120, { v: 1, t: "patch.load", id: 5, slug: "sweep" }],
  [150, { v: 1, t: "machine.home", id: 6 }],
];

test("a scripted run is byte-identical across two runs, server and client side", async () => {
  const a = await scriptedRun(SCRIPT);
  const b = await scriptedRun(SCRIPT);
  assert.equal(a.client.length, SCRIPT.length);
  assert.deepEqual(a.client, b.client);
  assert.equal(a.server.length, b.server.length);
  assert.deepEqual(a.server, b.server);
  assert.deepEqual(a.invalid, []);
});

test("every message the fake sends validates against the protocol schema", async () => {
  const { server } = await scriptedRun(SCRIPT);
  const types = new Set();
  for (const text of server) {
    const m = JSON.parse(text);
    types.add(m.t);
    assert.deepEqual(validate("server", m), [], `${m.t}`);
  }
  for (const t of ["hello", "state", "scope", "heartbeat", "patch", "ack"]) assert.ok(types.has(t), t);
});

test("an opcode the interpreter lacks stops it with program_stalled, never a throw or a hang", async () => {
  const probe = new FakeEngine({ clock: "manual" });
  const image = plantedImage(probe.loopAddr, "E100"); // X'E1': outside the program's subset
  const { server, engine } = await scriptedRun(SCRIPT.slice(0, 2), 60, { image });
  assert.ok(engine.faults.includes("program_stalled"));
  assert.equal(engine.cpu.fault.code, "unknown_opcode");
  assert.equal(engine.cpu.fault.pc, probe.loopAddr);
  const msgs = server.map((t) => JSON.parse(t));
  for (const m of msgs) assert.deepEqual(validate("server", m), [], m.t);
  const f = msgs.find((m) => m.t === "fault");
  assert.equal(f.code, "program_stalled");
  assert.match(f.staff_line, new RegExp(probe.loopAddr.toString(16).toUpperCase().padStart(4, "0")));
  assert.equal(msgs.filter((m) => m.t === "heartbeat").at(-1).engine_alive, false);
});

test("the ADR-009 scan, polyphonic: more key changes than K at once, more keys than voices, none lost", () => {
  const sym = symbols();
  const eng = new FakeEngine({ clock: "manual" });
  assert.equal(eng.loopAddr, sym.LOOP, "findLoop found the scan loop");
  assert.equal(eng.helloMsg().capabilities.voices, 4, "the floor map has four voices");
  eng.advance(100);
  // Six keys at once: K = 3 a pass, so two passes. After a frame the program knows all six,
  // and its four voices play four of them (each new key past four takes the oldest voice).
  const keys = [1, 2, 5, 9, 17, 33];
  eng.touchBits = keys.reduce((b, k) => b | (1n << BigInt(k)), 0n);
  eng.advance(1000 / 60);
  const s = eng.stateMsg(eng.lastTick);
  const rows = [0x64, 0x40, 0x40, 0x00, 0x40];
  assert.deepEqual(s.keys_seen.slice(0, 5), rows);
  assert.deepEqual([...eng.cpu.mem.slice(sym.HELD, sym.HELD + 5)], rows, "HELD has all six");
  const notes = s.watch.voices;
  assert.equal(notes.length, 4);
  assert.ok(notes.every((n) => n !== null && keys.includes(n - 48)), `voices ${notes}`);
  assert.equal(new Set(notes).size, 4, "four different notes");
  // Release them all: every gate drops, and HELD is empty again.
  eng.touchBits = 0n;
  eng.advance(1000 / 60);
  const off = eng.stateMsg(eng.lastTick);
  assert.deepEqual(off.watch.voices, [null, null, null, null]);
  assert.deepEqual([...eng.cpu.mem.slice(sym.HELD, sym.HELD + 5)], [0, 0, 0, 0, 0]);
});

test("the eight-voice image: gates on the latch, line 0 is the MSB (Interdata numbering)", () => {
  const eng = new FakeEngine({ clock: "manual", image: DEFAULT_IMAGE.replace(/rig\.img\.json$/, "rig8.img.json") });
  assert.equal(eng.helloMsg().capabilities.voices, 8);
  eng.advance(100);
  eng.touchBits = 1n << 12n;
  eng.advance(1000 / 60);
  const s = eng.stateMsg(eng.lastTick);
  assert.equal(s.gates & 0x8000, 0x8000);
  assert.deepEqual(s.watch.voices, [60, null, null, null, null, null, null, null]);
});

test("the schema rejects drift: missing fields, wrong types, unknown keys", () => {
  assert.notDeepEqual(validate("server", { v: 1, t: "state", seq: 1 }), []);
  assert.notDeepEqual(validate("client", { v: 1, t: "keys.touch", bits: "12" }), []);
  assert.notDeepEqual(validate("client", { v: 1, t: "machine.speed", id: 1, position: "turbo" }), []);
  assert.notDeepEqual(validate("client", { v: 1, t: "keys.touch", bits: "0000000000000000", extra: 1 }), []);
  assert.deepEqual(check({ $ref: "jack" }, "v1.pitch"), []);
  assert.notDeepEqual(check({ $ref: "jack" }, "v1"), []);
});

test("the protocol gives the page no way to write memory (CODE-4)", () => {
  // Staff commands are PIN-gated settings and actions (ARCHITECTURE 4.4); none of them, and
  // no visitor message, deposits, writes the switch register or memory, or plays a passage.
  for (const t of clientTypes()) assert.ok(!/deposit|\bdep|mem|\.sr\b|switch|passage/i.test(t), t);
  for (const t of clientTypes()) {
    const props = Object.keys(SCHEMA.client[t].properties);
    assert.ok(!props.some((p) => /addr|word|mem|data|sr/i.test(p)), `${t}: ${props}`);
  }
  assert.ok(!("machine.sr" in SCHEMA.client));
});

test("staff: a wrong PIN is refused, five wrong tries lock for 30 s, the right PIN opens a session", async () => {
  const eng = new FakeEngine({ clock: "manual" });
  const sent = [];
  const conn = { send: (t) => sent.push(JSON.parse(t)) };
  eng.connected({ ...conn, kill() {} });
  const c = [...eng.clients][0];
  const say = (m) => { sent.length = 0; eng.receive(c, JSON.stringify({ v: 1, ...m })); return sent.slice(); };
  // nothing works before a session
  assert.equal(say({ t: "staff.mute", id: 1, on: true })[0].code, "not_staff");
  for (let i = 1; i <= 4; i++) {
    const r = say({ t: "staff.auth", id: 10 + i, pin: "0000" });
    assert.equal(r[0].code, "not_staff");
    assert.equal(r[1].tries_left, 5 - i);
    assert.equal(r[1].authed, false);
    assert.equal(r[1].settings, undefined, "no settings before a session");
  }
  let r = say({ t: "staff.auth", id: 20, pin: "0000" });
  assert.equal(r[1].lockout_s, 30);
  r = say({ t: "staff.auth", id: 21, pin: eng.staffPin });
  assert.equal(r[0].code, "not_staff", "the right PIN is refused during the lockout");
  eng.advance(30500);
  r = say({ t: "staff.auth", id: 22, pin: eng.staffPin });
  assert.equal(r[0].t, "ack");
  assert.equal(r[1].authed, true);
  assert.equal(r[1].settings.ceiling_dba, 72);
  for (const m of [...r]) assert.deepEqual(validate("server", m), [], m.t);
  // a session's settings and actions
  r = say({ t: "staff.ceiling", id: 23, dba: 85 });
  assert.equal(r[1].settings.ceiling_dba, r[1].settings.ceiling_max_dba, "clamped to the hardware maximum");
  r = say({ t: "staff.review_mode", id: 24, on: true });
  assert.deepEqual(r.map((m) => m.t), ["ack", "settings"]);
  assert.equal(r[1].review_mode, true);
  r = say({ t: "staff.mute", id: 25, on: true });
  assert.equal(r.find((m) => m.t === "heartbeat").muted, true);
  r = say({ t: "staff.save_preset", id: 26 });
  assert.match(r[1].saved, /^staff-\d+$/);
  assert.ok(eng.presets[r[1].saved]);
  r = say({ t: "staff.close", id: 27 });
  assert.equal(r[1].authed, false);
  assert.equal(say({ t: "staff.mute", id: 28, on: false })[0].code, "not_staff");
});

test("frozen engine: key presses change keys_raw only (PLAY-3)", async () => {
  const eng = new FakeEngine({ clock: "manual" });
  eng.advance(500);
  eng.freeze(true);
  eng.advance(100);
  const before = eng.stateMsg(eng.lastTick);
  eng.touchBits = 0x1f00n;
  eng.midiKeys(0x3n);
  eng.advance(1000);
  const after = eng.stateMsg(eng.lastTick);
  for (const k of ["pc", "r", "keys_seen", "dac", "gates", "watch", "lamps", "pc_hist"]) {
    assert.deepEqual(after[k], before[k], k);
  }
  assert.notDeepEqual(after.keys_raw, before.keys_raw);
});

test("a key reaches keys_seen, the D/A and gate 0 at RUN, and late when slowed", async () => {
  const eng = new FakeEngine({ clock: "manual" });
  eng.advance(200);
  eng.touchBits = 1n << 12n; // C4
  eng.advance(1000 / 60);
  let s = eng.stateMsg(eng.lastTick);
  assert.equal(s.keys_seen[1], 0x08);
  assert.deepEqual(s.watch.voices, [60, null, null, null]);
  assert.notEqual(s.dac[0], 0, "voice 1's pitch on D/A 0");
  assert.ok(s.dac[4] >= 0x4000, "voice 1's gate on D/A 4, above 2.5 V");
  // CRAWL: about 12 instructions a second, so one frame is not enough for the note.
  eng.receive({ send() {} }, JSON.stringify({ v: 1, t: "machine.home", id: 1 }));
  eng.speed = "crawl";
  eng.touchBits = 1n << 5n;
  eng.advance(1000 / 60);
  s = eng.stateMsg(eng.lastTick);
  assert.deepEqual(s.watch.voices, [null, null, null, null]);
  assert.equal(s.lamps.exact, true);
});

test("lamp fractions at RUN are duty cycles; exact at CRAWL and STEP", () => {
  const eng = new FakeEngine({ clock: "manual" });
  eng.advance(300);
  const run = eng.stateMsg(eng.lastTick);
  assert.equal(run.lamps.exact, false);
  assert.ok(run.lamps.addr.some((f) => f > 0 && f < 1), "some address bit is partly lit at RUN");
  assert.ok(run.scan_hz > 1000, `scan rate ${run.scan_hz}`);
  eng.speed = "step";
  eng.stepsPending = 1;
  eng.advance(1000 / 60);
  const st = eng.stateMsg(eng.lastTick);
  assert.equal(st.lamps.exact, true);
  assert.ok(st.lamps.addr.every((f) => f === 0 || f === 1));
  const pc = st.lamps.addr.reduce((v, b) => (v << 1) | b, 0);
  assert.equal(pc, st.pc);
});

test("STEP executes exactly one instruction per machine.step", () => {
  const eng = new FakeEngine({ clock: "manual" });
  eng.advance(200);
  eng.speed = "step";
  const n0 = eng.cpu.instructions;
  for (let i = 0; i < 7; i++) {
    eng.receive({ send() {} }, JSON.stringify({ v: 1, t: "machine.step", id: i + 1 }));
    eng.advance(1000 / 60);
  }
  eng.advance(500);
  assert.equal(eng.cpu.instructions - n0, 7);
});

test("held-key rule: a key down more than 60 s is released until let go (PLAY-8)", () => {
  const eng = new FakeEngine({ clock: "manual" });
  eng.midiKeys(1n << 12n);
  eng.advance(59000);
  // C4 on any voice (a key pressed again gets the voice that has rested longest)
  const v1 = () => (eng.stateMsg(eng.lastTick).watch.voices.includes(60) ? 60 : null);
  assert.equal(v1(), 60);
  eng.advance(2000);
  assert.equal(v1(), null);
  eng.midiKeys(0n);
  eng.advance(100);
  eng.midiKeys(1n << 12n);
  eng.advance(100);
  assert.equal(v1(), 60);
});

test("patch reachability on the engine-format wall: the default patch sounds, a cut one does not (PATCH-4)", () => {
  const eng = new FakeEngine({ clock: "manual" });
  assert.equal(eng.preset, "stadium-drone", "kiosk.conf preset_order's first");
  const L = eng.layout;
  assert.ok(reachesOut(eng.cables, L));
  assert.ok(!reachesOut([], L));
  // both buses cut from the output module: silent
  assert.ok(!reachesOut(eng.cables.filter((c) => !c.to.startsWith("out.")), L));
  // only the left bus: still sounds
  assert.ok(reachesOut(eng.cables.filter((c) => c.to !== "out.r"), L));
  // a voice with no gate cable is silent even if its output reaches the speaker
  assert.ok(!reachesOut(eng.cables.filter((c) => !c.to.endsWith(".gate")), L));
  // the engine format's voices block and wildcard cables became wall cables
  const has = (a, b) => eng.cables.some((c) => c.from === a && c.to === b);
  assert.ok(has("dac.0", "v1.pitch") && has("dac.4", "v1.gate") && has("v1.out", "mix0.in1") && has("v2.out", "mix1.in1"));
  assert.ok(has("lfo.sine", "v3.flt-cutoff"));
  for (const c of eng.cables) assert.ok(eng.jackIds.has(c.from) && eng.jackIds.has(c.to), `${c.from} ${c.to}`);
});

test("every engine preset for the floor map loads, sounds, and pairs the program it names (PATCH-5)", () => {
  const eng = new FakeEngine({ clock: "manual" });
  for (const slug of Object.keys(eng.presets)) {
    eng.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.load", id: 1, slug }));
    assert.equal(eng.preset, slug);
    assert.ok(reachesOut(eng.cables, eng.layout), `${slug} reaches the speaker`);
    assert.deepEqual(validate("server", eng.patchMsg()), [], slug);
  }
  eng.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.load", id: 2, slug: "computer-rhythm" }));
  assert.equal((eng.cpu.sr >> 4) & 0xf, 1, "computer-rhythm runs the rhythm routine");
  eng.receive({ send() {} }, JSON.stringify({ v: 1, t: "patch.load", id: 3, slug: "eight-voices" }));
  assert.equal(eng.preset, "computer-rhythm", "a preset for another map is refused");
});


test("speeds: six detents, RUN first, STEP last, every ratio marked uncalibrated", () => {
  assert.deepEqual(SPEEDS.map((s) => s.id), ["run", "div30", "div300", "div3000", "crawl", "step"]);
  assert.ok(SPEEDS.every((s) => s.calibrated === false));
});
