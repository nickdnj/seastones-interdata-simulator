// rig.js: the WebSocket client to rigd, protocol v1 (VS-15; ARCHITECTURE 4.6, KIOSK-2).
//
// One connection, reconnect with backoff, a heartbeat deadline, ack correlation. It holds
// the latest `hello`, `state`, `scope`, `heartbeat` and `patch` and hands them to whoever
// listens. When the link is down it forgets them: no screen may show a stale value as if
// it were live (KIOSK-4, UI-34). Every message the page can send is built in protocol.js.

const listeners = new Map(); // type -> Set(fn)
export const live = {
  connected: false,
  everConnected: false,
  hello: null,
  state: null,
  scope: null,
  heartbeat: null,
  patch: null,
  settings: null, // the staff settings the page follows (extension, KP-08)
  staff: null, // this connection's staff session, when one was asked for (KP-07)
  faults: new Map(), // code -> {staff_line, since}
  lastMessageAt: 0,
  mismatch: null, // the protocol version rigd speaks, when it is not ours (v1)
  gaps: 0, // state messages missed (seq jumps), for the staff screen
};
export const PROTOCOL_VERSION = 1;

let ws = null;
let url = null;
let backoff = 250;
let deadlineMs = 3000;
let watchdog = null;
let silentTicks = 0;
let retryTimer = null;
let nextId = 1;
const pending = new Map(); // id -> {resolve, timer}

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}
function emit(type, payload) {
  for (const fn of listeners.get(type) || []) fn(payload);
}

/** Start talking to rigd. `deadline` is the heartbeat deadline in ms (UX: 3 s). */
export function connect(rigUrl, { deadline = 3000 } = {}) {
  url = rigUrl;
  deadlineMs = deadline;
  open();
}

function open() {
  clearTimeout(retryTimer);
  try {
    ws = new WebSocket(url);
  } catch {
    scheduleRetry();
    return;
  }
  ws.onopen = () => {
    backoff = 250;
    live.connected = true;
    live.everConnected = true;
    live.lastMessageAt = performance.now();
    armWatchdog();
    emit("status", true);
  };
  ws.onmessage = (ev) => {
    live.lastMessageAt = performance.now();
    armWatchdog();
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (!msg) return;
    // A rigd that speaks another protocol version is a fault with a name, not a silent wait:
    // its hello says so, and nothing it sends is drawn (KIOSK-4).
    if (msg.t === "hello" && msg.v !== PROTOCOL_VERSION) {
      live.mismatch = msg.v;
      live.hello = live.state = live.scope = live.heartbeat = live.patch = null;
      emit("mismatch", msg.v);
      return;
    }
    if (msg.v !== PROTOCOL_VERSION || live.mismatch !== null) return;
    receive(msg);
  };
  ws.onclose = () => down();
  ws.onerror = () => { /* onclose follows */ };
}

function receive(msg) {
  switch (msg.t) {
    case "hello": live.hello = msg; break;
    case "state":
      // Snapshots are levels, so a gap loses nothing: draw the newest. One that arrives
      // after a newer one is stale and is never drawn (a lamp must not step back in time).
      if (live.state && msg.seq <= live.state.seq) return;
      if (live.state && msg.seq > live.state.seq + 1) live.gaps += msg.seq - live.state.seq - 1;
      live.state = msg;
      break;
    case "scope": live.scope = msg; break;
    case "heartbeat": live.heartbeat = msg; break;
    case "patch": live.patch = msg; break;
    case "settings": live.settings = msg; break;
    case "staff": live.staff = msg; break;
    case "fault":
      if (msg.cleared) live.faults.delete(msg.code);
      else live.faults.set(msg.code, { staff_line: msg.staff_line, since: msg.since });
      break;
    case "ack":
    case "nack": {
      const p = pending.get(msg.id);
      if (p) {
        clearTimeout(p.timer);
        pending.delete(msg.id);
        p.resolve(msg.t === "ack" ? { ok: true } : { ok: false, code: msg.code });
      }
      break;
    }
    default:
      return;
  }
  emit(msg.t, msg);
}

// The heartbeat deadline counts whole silent seconds rather than trusting one long timer, so
// a jump of the page clock (a test clock, a suspended tab) cannot fake a dead link.
function armWatchdog() {
  silentTicks = 0;
  if (watchdog) return;
  watchdog = setInterval(() => {
    if (++silentTicks < Math.max(1, Math.round(deadlineMs / 1000))) return;
    // No message, not even a heartbeat, inside the deadline: treat the link as dead.
    if (ws) { try { ws.close(); } catch { /* already closing */ } }
    down();
  }, 1000);
}

function down() {
  clearInterval(watchdog);
  watchdog = null;
  const was = live.connected;
  live.connected = false;
  live.mismatch = null;
  live.hello = live.state = live.scope = live.heartbeat = live.patch = live.staff = null;
  live.faults.clear();
  for (const [, p] of pending) { clearTimeout(p.timer); p.resolve({ ok: false, code: "disconnected" }); }
  pending.clear();
  if (ws) { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; ws = null; }
  if (was) emit("status", false);
  scheduleRetry();
}

function scheduleRetry() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(open, backoff);
  backoff = Math.min(backoff * 2, 4000);
}

/** Send a message with no reply (keys.touch). False if the link is down. */
export function post(msg) {
  if (!ws || ws.readyState !== 1) return false;
  ws.send(JSON.stringify({ v: 1, ...msg }));
  return true;
}

/** Send a command and wait for its ack or nack (2 s at most). */
export function command(msg) {
  return new Promise((resolve) => {
    if (!ws || ws.readyState !== 1) { resolve({ ok: false, code: "disconnected" }); return; }
    const id = nextId++;
    const timer = setTimeout(() => { pending.delete(id); resolve({ ok: false, code: "timeout" }); }, 2000);
    pending.set(id, { resolve, timer });
    ws.send(JSON.stringify({ v: 1, ...msg, id }));
  });
}

/** The speed detents as the engine reports them (the calibration record, PR-03). */
export function speeds() {
  return (live.hello && live.hello.capabilities.speeds) || [];
}
