// ws.mjs: the smallest WebSocket server the fake engine needs (RFC 6455, text frames).
//
// No dependency, so the fake engine runs with nothing but Node. It accepts unfragmented
// or fragmented text frames from the browser (always masked), answers pings, honours
// close, and sends unmasked text frames. Binary frames are refused with close code 1003.
import http from "node:http";
import crypto from "node:crypto";

const GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

class Conn {
  constructor(socket, onMessage, onClose) {
    this.socket = socket;
    this.buf = Buffer.alloc(0);
    this.parts = [];
    this.open = true;
    this.onMessage = onMessage;
    this.onClose = onClose;
    socket.on("data", (d) => this.feed(d));
    socket.on("close", () => this.closed());
    socket.on("error", () => this.closed());
  }

  feed(data) {
    this.buf = Buffer.concat([this.buf, data]);
    for (;;) {
      if (this.buf.length < 2) return;
      const b0 = this.buf[0], b1 = this.buf[1];
      const fin = (b0 & 0x80) !== 0, opcode = b0 & 0x0f, masked = (b1 & 0x80) !== 0;
      let len = b1 & 0x7f, off = 2;
      if (len === 126) {
        if (this.buf.length < 4) return;
        len = this.buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (this.buf.length < 10) return;
        len = Number(this.buf.readBigUInt64BE(2));
        off = 10;
      }
      const maskLen = masked ? 4 : 0;
      if (this.buf.length < off + maskLen + len) return;
      const mask = masked ? this.buf.subarray(off, off + 4) : null;
      const payload = Buffer.from(this.buf.subarray(off + maskLen, off + maskLen + len));
      if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];
      this.buf = this.buf.subarray(off + maskLen + len);
      if (opcode === 0x8) { this.close(1000); return; }
      if (opcode === 0x9) { this.frame(0xa, payload); continue; }
      if (opcode === 0xa) continue;
      if (opcode === 0x2) { this.close(1003); return; }
      if (opcode === 0x1 || opcode === 0x0) {
        this.parts.push(payload);
        if (fin) {
          const text = Buffer.concat(this.parts).toString("utf8");
          this.parts = [];
          this.onMessage(text);
        }
      }
    }
  }

  frame(opcode, payload) {
    if (!this.open) return;
    const n = payload.length;
    let head;
    if (n < 126) head = Buffer.from([0x80 | opcode, n]);
    else if (n < 65536) { head = Buffer.alloc(4); head[0] = 0x80 | opcode; head[1] = 126; head.writeUInt16BE(n, 2); }
    else { head = Buffer.alloc(10); head[0] = 0x80 | opcode; head[1] = 127; head.writeBigUInt64BE(BigInt(n), 2); }
    try { this.socket.write(Buffer.concat([head, payload])); } catch { this.closed(); }
  }

  send(text) { this.frame(0x1, Buffer.from(text, "utf8")); }

  close(code = 1000) {
    if (!this.open) return;
    const p = Buffer.alloc(2);
    p.writeUInt16BE(code, 0);
    this.frame(0x8, p);
    this.open = false;
    this.socket.end();
    this.closed();
  }

  /** Drop the TCP connection with no close frame, the way a killed rigd does. */
  kill() {
    this.open = false;
    this.socket.destroy();
    this.closed();
  }

  closed() {
    if (this.done) return;
    this.done = true;
    this.open = false;
    this.onClose();
  }
}

/**
 * Start a server. `accept()` decides whether an upgrade is accepted (a "dead" fake
 * engine refuses). `onConnection(conn)` must set `conn.onMessage` and `conn.onClose`.
 */
export function createServer({ host = "127.0.0.1", port = 0, accept = () => true, onConnection }) {
  const server = http.createServer((req, res) => {
    res.writeHead(426, { "content-type": "text/plain" });
    res.end("fake engine: WebSocket only\n");
  });
  server.on("upgrade", (req, socket) => {
    const key = req.headers["sec-websocket-key"];
    if (!key || !accept()) { socket.destroy(); return; }
    const acceptKey = crypto.createHash("sha1").update(key + GUID).digest("base64");
    socket.write(
      "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
        `Sec-WebSocket-Accept: ${acceptKey}\r\n\r\n`,
    );
    socket.setNoDelay(true);
    const conn = new Conn(socket, (t) => conn.handler && conn.handler(t), () => conn.closer && conn.closer());
    onConnection(conn);
  });
  return new Promise((resolve) => {
    server.listen(port, host, () => resolve({ server, port: server.address().port }));
  });
}
