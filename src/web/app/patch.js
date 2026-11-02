// patch.js: layer 4, Patch (PM-10, PM-11, PM-13, PM-15; PATCH-1, PATCH-4, PATCH-5, NFR-10).
//
// Cables are drawn on a canvas over our module wall, with the droop UX 6.1 asks for:
// control points sag by 34 + 0.13 x distance, so a cable never looks like a wire. The
// cables shown are the engine's (the `patch` message); a drag shows the loose end under
// the finger and asks the engine on release. Every drag has a tap alternative (PM-11,
// WCAG 2.5.7): tap a jack, then another, to join them; tap a plug, then "Remove cable".
// Each pointer owns one cable; if two pointers grab the same jack the first wins.
//
// The silence hint (PATCH-4): when the engine says nothing reaches the speaker, the hint
// appears at the next key press (the station must be told, not guess, UX 5.5).

import { el } from "./blocks.js";
import { S } from "./strings.js";
import * as content from "./content.js";
import * as rig from "./rig.js";
import * as protocol from "./protocol.js";
import { Keyboard } from "./keyboard.js";
import { chips, putItBack } from "./play.js";
import { onActivity, tap } from "./touch.js";
import { layout, wallSvg, labelsSvg, cableColour, railTable, W, H } from "./patchwall.js";

const GRAB_R = 34;
const SNAP_R = 44;
const TAP_MOVE = 12;
const BUBBLE_MS = 3000;
// The slim keys share their row with the help text; 22 white keys stay above the 54 px floor.
const PATCH_KB_W = 1290;

export function droopPath(a, b) {
  const d = Math.hypot(a.x - b.x, a.y - b.y);
  const sag = 34 + d * 0.13;
  return [a.x, a.y + sag, b.x, b.y + sag];
}

export function mount(section, ctx) {
  section.textContent = "";
  // The wall is the loaded patch's own graph (PM-12, wallmodel.js): the engine sends its
  // layout with every patch, and the wall is rebuilt in place when that layout changes (a
  // preset with other modules, the eight-voice map). Controls and keys stay as they are.
  let channelMap = content.rigTable("channel-map");
  let lay = layout(channelMap, null);
  let byId = new Map(lay.jacks.map((j) => [j.id, j]));
  let hits = new Map();
  let layoutKey = null;
  const wall = el("div", "wall");
  wall.id = "wall";
  wall.style.height = `${H}px`;
  const cv = el("canvas");
  cv.width = W;
  cv.height = H;
  cv.style.pointerEvents = "none";
  const cx = cv.getContext("2d");
  section.appendChild(wall);

  const buildWall = (desc) => {
    channelMap = content.rigTable(railTable(desc ? desc.map : ""));
    lay = layout(channelMap, desc);
    byId = new Map(lay.jacks.map((j) => [j.id, j]));
    wall.innerHTML = wallSvg(lay);
    wall.appendChild(cv);
    wall.insertAdjacentHTML("beforeend", labelsSvg(lay, { railTitle: S("patch", "rail-title").toUpperCase(), railSub: S("patch", "rail-sub") }));
    hits = new Map();
    for (const j of lay.jacks) {
      const h = el("div", "jackhit");
      h.style.left = `${j.x}px`;
      h.style.top = `${j.y}px`;
      h.dataset.jack = j.id;
      h.setAttribute("role", "button");
      h.setAttribute("aria-label", `Jack ${j.label}`);
      h.tabIndex = 0;
      h.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        const id = j.id;
        if (selected && selected !== id) { const a = selected; select(null); join(a, id); }
        else if (cablesAt(id).length) showBubble(id);
        else select(id);
      });
      wall.appendChild(h);
      hits.set(j.id, h);
    }
    // a rebuilt wall forgets half-made gestures on jacks that may be gone
    selected = null;
    drags.clear();
    bubble.hidden = true;
    dirty = true;
  };

  const hint = el("div", "hint", S("patch", "nothing-reaches"));
  hint.id = "silence-hint";
  hint.hidden = true;
  section.appendChild(hint);
  const bubble = el("button", "bubble", `✕ ${S("patch", "remove-cable")}`);
  bubble.type = "button";
  bubble.id = "remove-bubble";
  bubble.hidden = true;
  section.appendChild(bubble);

  // The help sits beside the slim keys, clear of the wall: on the wall's bottom edge it ran
  // over the lowest row of jack labels.
  const help = el("div", "patch-help", S("patch", "help"));
  help.id = "patch-help";
  section.appendChild(help);
  const controls = el("div", "patch-controls");
  controls.style.top = "652px";
  // the short label: five presets and PUT IT BACK share this row with it
  controls.appendChild(el("span", "lbl", S("patch", "sounds")));
  const strip = chips(controls);
  strip.row.style.cssText = "width:auto;margin-top:0";
  controls.appendChild(el("span", "spacer"));
  const pib = el("button", "btn amber sm", S("play", "put-it-back"));
  pib.type = "button";
  pib.id = "putback-patch";
  tap(pib, () => putItBack(ctx.toast));
  controls.appendChild(pib);
  section.appendChild(controls);
  const kbBox = el("div");
  kbBox.style.cssText = "position:absolute;left:48px;top:732px";
  new Keyboard(kbBox, { width: PATCH_KB_W, height: 80, slim: true });
  section.appendChild(kbBox);

  // ------------------------------------------------------------ state
  const drags = new Map(); // pointerId -> drag
  let selected = null; // tap alternative: the first jack tapped
  let bubbleFor = null;
  let bubbleTimer = null;
  let silentSince = null;
  let keySince = 0;
  let lastKeysRaw = null;
  let dirty = true;

  const cables = () => (rig.live.patch ? rig.live.patch.cables : []);
  const cablesAt = (id) => cables().filter((c) => c.from === id || c.to === id);
  const toWall = (e) => {
    const r = wall.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };
  const nearest = (p, max) => {
    let best = null, bd = max;
    for (const j of lay.jacks) {
      const d = Math.hypot(j.x - p.x, j.y - p.y);
      if (d < bd) { bd = d; best = j; }
    }
    return best;
  };
  const grabbed = (id) => [...drags.values()].some((d) => d.jack === id);

  const select = (id) => {
    if (selected && hits.get(selected)) hits.get(selected).classList.remove("sel");
    selected = hits.has(id) ? id : null;
    if (selected) hits.get(selected).classList.add("sel");
  };
  const showBubble = (id) => {
    const j = byId.get(id);
    if (!j) return;
    bubbleFor = id;
    bubble.style.left = `${48 + j.x - 110}px`;
    bubble.style.top = `${8 + j.y - 120}px`;
    bubble.hidden = false;
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => { bubble.hidden = true; bubbleFor = null; }, BUBBLE_MS);
  };
  bubble.addEventListener("click", async () => {
    const id = bubbleFor;
    bubble.hidden = true;
    bubbleFor = null;
    const c = cablesAt(id).pop();
    if (c) { await protocol.disconnect(c.from, c.to); ctx.toast(S("patch", "pulled-out")); }
  });

  const join = async (a, b) => {
    if (!a || !b || a === b) return false;
    const res = await protocol.connect(a, b);
    ctx.toast(res.ok ? S("patch", "joined") : S("patch", "refused"));
    return res.ok;
  };

  // ------------------------------------------------------------ pointer handling
  wall.addEventListener("pointerdown", (e) => {
    if (e.cancelable) e.preventDefault();
    const p = toWall(e);
    const j = nearest(p, GRAB_R);
    if (!j || grabbed(j.id)) return;
    try { wall.setPointerCapture(e.pointerId); } catch { /* best effort */ }
    const plugged = cablesAt(j.id);
    const cable = plugged.length ? plugged[plugged.length - 1] : null;
    drags.set(e.pointerId, {
      jack: j.id,
      cable,
      other: cable ? (cable.from === j.id ? cable.to : cable.from) : j.id,
      start: p,
      at: p,
      moved: false,
    });
    bubble.hidden = true;
    dirty = true;
  });
  wall.addEventListener("pointermove", (e) => {
    const d = drags.get(e.pointerId);
    if (!d) return;
    d.at = toWall(e);
    if (Math.hypot(d.at.x - d.start.x, d.at.y - d.start.y) > TAP_MOVE) d.moved = true;
    dirty = true;
  });
  const end = async (e, cancelled) => {
    const d = drags.get(e.pointerId);
    if (!d) return;
    drags.delete(e.pointerId);
    dirty = true;
    if (cancelled) return;
    if (!d.moved) {
      // a tap: the tap alternative for every drag (PM-11)
      if (selected && selected !== d.jack) { const a = selected; select(null); await join(a, d.jack); return; }
      if (selected === d.jack) { select(null); return; }
      if (d.cable) { showBubble(d.jack); return; }
      select(d.jack);
      ctx.toast(S("patch", "pick-second"));
      return;
    }
    select(null);
    const target = nearest(d.at, SNAP_R);
    if (d.cable) {
      if (target && target.id !== d.other && target.id !== d.jack) {
        const off = await protocol.disconnect(d.cable.from, d.cable.to);
        // a refused move puts the cable back where it was: "did not take" must not also
        // mean "and your cable is gone" (QA-ADV-01)
        if (!(await join(d.other, target.id)) && off.ok) await protocol.connect(d.cable.from, d.cable.to);
      } else if (!target || target.id !== d.jack) {
        await protocol.disconnect(d.cable.from, d.cable.to);
        ctx.toast(S("patch", "pulled-out"));
      }
    } else if (target && target.id !== d.jack) {
      await join(d.jack, target.id);
    }
  };
  wall.addEventListener("pointerup", (e) => end(e, false));
  wall.addEventListener("pointercancel", (e) => end(e, true));
  wall.addEventListener("lostpointercapture", (e) => { if (drags.has(e.pointerId)) end(e, true); });
  onActivity((kind) => { if (kind === "key") keySince = performance.now(); });

  // ------------------------------------------------------------ drawing
  const drawCable = (a, b, colour, lifted) => {
    const [c1x, c1y, c2x, c2y] = droopPath(a, b);
    const stroke = (w, col, alpha, dx, dy) => {
      cx.globalAlpha = alpha;
      cx.strokeStyle = col;
      cx.lineWidth = w;
      cx.lineCap = "round";
      cx.beginPath();
      cx.moveTo(a.x + dx, a.y + dy);
      cx.bezierCurveTo(c1x + dx, c1y + dy, c2x + dx, c2y + dy, b.x + dx, b.y + dy);
      cx.stroke();
    };
    stroke(13, "#000", lifted ? 0.45 : 0.35, 0, lifted ? 11 : 7);
    stroke(10, colour, 1, 0, 0);
    stroke(2.5, "#fff", 0.38, -2, -2);
    cx.globalAlpha = 1;
    for (const [p, s] of [[a, 1], [b, lifted ? 1.15 : 1]]) {
      cx.fillStyle = "#17181c";
      cx.strokeStyle = colour;
      cx.lineWidth = 5;
      cx.beginPath();
      cx.arc(p.x, p.y, 19 * s, 0, Math.PI * 2);
      cx.fill();
      cx.stroke();
      cx.globalAlpha = 0.9;
      cx.fillStyle = colour;
      cx.beginPath();
      cx.arc(p.x, p.y, 8 * s, 0, Math.PI * 2);
      cx.fill();
      cx.globalAlpha = 1;
    }
  };

  let lastPatch = null;
  const draw = () => {
    cx.clearRect(0, 0, W, H);
    const live = cables();
    const lifted = new Set([...drags.values()].filter((d) => d.cable).map((d) => d.cable));
    for (const c of live) {
      if (lifted.has(c)) continue;
      const a = byId.get(c.from), b = byId.get(c.to);
      if (a && b) drawCable(a, b, cableColour(c.from, c.to, channelMap), false);
    }
    for (const d of drags.values()) {
      const fixed = byId.get(d.other);
      if (!fixed) continue;
      let end = d.at;
      const aim = d.moved ? nearest(d.at, SNAP_R) : null;
      if (aim && aim.id !== d.other) {
        end = { x: d.at.x + (aim.x - d.at.x) * 0.3, y: d.at.y + (aim.y - d.at.y) * 0.3 };
        cx.globalAlpha = 0.85;
        cx.strokeStyle = "#4FC3B5";
        cx.lineWidth = 6;
        cx.beginPath();
        cx.arc(aim.x, aim.y, 31, 0, Math.PI * 2);
        cx.stroke();
        cx.globalAlpha = 1;
      }
      if (!d.moved && !d.cable) continue;
      drawCable(fixed, end, cableColour(d.other, aim ? aim.id : null, channelMap), true);
      cx.globalAlpha = 0.35;
      cx.strokeStyle = "#F6EBD0";
      cx.lineWidth = 3;
      cx.beginPath();
      cx.arc(d.at.x, d.at.y, 27, 0, Math.PI * 2);
      cx.stroke();
      cx.globalAlpha = 1;
    }
  };

  return {
    voices: () => (lay.plates.filter((p) => /^v\d+$/.test(p.id))).length,
    paint(state) {
      if (rig.live.patch !== lastPatch) {
        lastPatch = rig.live.patch;
        const key = lastPatch ? JSON.stringify(lastPatch.layout) : null;
        if (key !== layoutKey) { layoutKey = key; buildWall(lastPatch ? lastPatch.layout : null); }
        dirty = true;
      }
      if (dirty) { draw(); dirty = false; }
      strip.paint();
      // the silence hint: shown after a key press while nothing reaches the speaker
      const p = rig.live.patch;
      const silent = !!p && !p.reaches_out;
      if (silent && silentSince === null) silentSince = performance.now();
      if (!silent) silentSince = null;
      if (state) {
        const raw = state.keys_raw.join(",");
        if (lastKeysRaw !== null && raw !== lastKeysRaw && state.keys_raw.some((r) => r)) keySince = performance.now();
        lastKeysRaw = raw;
      }
      const show = silent && keySince > silentSince;
      if (hint.hidden === show) hint.hidden = !show;
    },
    reset() { select(null); drags.clear(); bubble.hidden = true; dirty = true; },
  };
}
