// shell.js: the frame every screen shares (PM-00; UX 4, DESIGN-SYSTEM 5).
//
// Header (always says "simulated", with live SPEED and SCAN), dock (five layers, FULL
// SPEED when the computer is slowed, HOME) and the disclosure footer. All three are drawn
// here, outside every layer's container, so no layer can render without them (STORY-3).

import { el } from "./blocks.js";
import { S, M } from "./strings.js";
import { tap } from "./touch.js";

export const LAYERS = ["play", "computer", "code", "patch", "story"];

const ICONS = {
  play: '<rect x="4" y="12" width="40" height="26" rx="4" fill="none" stroke="currentColor" stroke-width="3"/><path d="M14 12v26M24 12v26M34 12v26" stroke="currentColor" stroke-width="3"/><rect x="11" y="12" width="6" height="15" fill="currentColor"/><rect x="21" y="12" width="6" height="15" fill="currentColor"/><rect x="31" y="12" width="6" height="15" fill="currentColor"/>',
  computer: '<rect x="3" y="10" width="42" height="28" rx="4" fill="none" stroke="currentColor" stroke-width="3"/><g fill="currentColor"><circle cx="12" cy="20" r="3"/><circle cx="21" cy="20" r="3"/><circle cx="30" cy="20" r="3"/><circle cx="39" cy="20" r="3" opacity=".35"/><circle cx="12" cy="30" r="3" opacity=".35"/><circle cx="21" cy="30" r="3"/><circle cx="30" cy="30" r="3" opacity=".35"/><circle cx="39" cy="30" r="3"/></g>',
  code: '<path d="M17 12 5 24l12 12M31 12l12 12-12 12" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><path d="M27 8 21 40" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>',
  patch: '<circle cx="9" cy="12" r="5" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="39" cy="14" r="5" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="12" cy="38" r="5" fill="currentColor"/><path d="M9 17c0 24 22 22 30-3" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>',
  story: '<path d="M4 36q10-8 20 0t20 0" fill="none" stroke="currentColor" stroke-width="3"/><ellipse cx="17" cy="28" rx="9" ry="6" fill="currentColor"/><ellipse cx="31" cy="30" rx="6" ry="4" fill="currentColor" opacity=".7"/><path d="M8 12h32M8 18h22" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>',
};
const MARK = '<path d="M0 36q9.5-9 19 0t19 0 19 0 19 0" fill="none" stroke="#F2A83B" stroke-width="3.5" stroke-linecap="round"/><path d="M0 44q9.5-9 19 0t19 0 19 0 19 0" fill="none" stroke="#E4572E" stroke-width="2.5" opacity=".8"/><ellipse cx="20" cy="24" rx="12" ry="8" fill="#F6EBD0"/><ellipse cx="44" cy="27" rx="9" ry="6" fill="#F07FA3"/><ellipse cx="60" cy="29" rx="6" ry="4" fill="#7B5BB0"/><ellipse cx="17" cy="21" rx="4" ry="2" fill="#fff" opacity=".6"/>';

const parts = {};
let toastTimer = null;

export function build({ onLayer, onHome, onFullSpeed, onAbout }) {
  const header = document.getElementById("header");
  header.textContent = "";
  const mark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  mark.setAttribute("class", "mark");
  mark.setAttribute("viewBox", "0 0 76 48");
  mark.setAttribute("aria-hidden", "true");
  mark.innerHTML = MARK;
  header.appendChild(mark);
  const brand = el("div", "brand", S("frame", "brand"));
  brand.appendChild(el("small", null, S("frame", "brand-sub")));
  header.appendChild(brand);
  const status = el("div", "status");
  const sim = el("span", "sim");
  sim.appendChild(el("i"));
  sim.appendChild(document.createTextNode(S("frame", "simulated")));
  status.appendChild(sim);
  parts.speedWrap = el("span", "speedro");
  parts.speedWrap.append(`${S("frame", "speed")} `);
  parts.speed = el("b", null, "·");
  parts.speed.id = "hdr-speed";
  parts.speedWrap.appendChild(parts.speed);
  status.appendChild(parts.speedWrap);
  const scan = el("span");
  scan.append(`${S("frame", "scan")} `);
  parts.scan = el("b", null, "·");
  parts.scan.id = "hdr-scan";
  scan.appendChild(parts.scan);
  const ps = el("span", null, S("frame", "per-second"));
  ps.style.textTransform = "none";
  scan.appendChild(ps);
  status.appendChild(scan);
  header.appendChild(status);

  const dock = document.getElementById("dock");
  dock.textContent = "";
  parts.tabs = {};
  for (const name of LAYERS) {
    const b = el("button", "tab");
    b.type = "button";
    b.dataset.layer = name;
    b.appendChild(el("span", "lamp"));
    const ic = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    ic.setAttribute("viewBox", "0 0 48 48");
    ic.setAttribute("aria-hidden", "true");
    ic.innerHTML = ICONS[name];
    b.appendChild(ic);
    const t = el("span", "t", S("frame", `dock-${name}`));
    t.appendChild(el("span", "c", M("frame", `dock-${name}`)));
    b.appendChild(t);
    tap(b, () => onLayer(name));
    dock.appendChild(b);
    parts.tabs[name] = b;
  }
  dock.appendChild(el("span", "spacer"));
  parts.full = el("button", "btn amber");
  parts.full.type = "button";
  parts.full.id = "fullspeed";
  parts.full.hidden = true;
  parts.full.textContent = `↺ ${S("frame", "full-speed")}`;
  tap(parts.full, () => onFullSpeed());
  dock.appendChild(parts.full);
  parts.home = el("button", "btn home");
  parts.home.type = "button";
  parts.home.id = "home";
  parts.home.innerHTML = '<svg width="38" height="38" viewBox="0 0 48 48" aria-hidden="true"><path d="M6 24 24 8l18 16M12 22v18h24V22" fill="none" stroke="currentColor" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  parts.home.append(S("frame", "home"));
  tap(parts.home, () => onHome());
  dock.appendChild(parts.home);

  const foot = document.getElementById("footer");
  foot.textContent = "";
  foot.appendChild(el("span", "line", S("frame", "footer")));
  const about = el("button", "about", S("frame", "footer-link"));
  about.type = "button";
  about.id = "about";
  tap(about, () => onAbout());
  foot.appendChild(about);
  foot.appendChild(el("span", "tag", S("frame", "footer-tag")));
  return { mark };
}

export function setLayer(name) {
  for (const [n, b] of Object.entries(parts.tabs || {})) {
    const on = n === name;
    b.classList.toggle("on", on);
    b.setAttribute("aria-current", on ? "page" : "false");
  }
}

/** Header SPEED is always the engine's speed (PLAY-11, UI-13); a dot when unknown. */
export function setSpeed(label, slowed) {
  if (!parts.speed) return;
  if (parts.speed.textContent !== label) parts.speed.textContent = label;
  parts.speedWrap.classList.toggle("slowed", !!slowed);
  parts.full.hidden = !slowed;
}

export function setScan(text) {
  if (parts.scan && parts.scan.textContent !== text) parts.scan.textContent = text;
}

export function setDockEnabled(on) {
  document.getElementById("dock").classList.toggle("disabled", !on);
}

export function toast(msg, ms = 2600) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), ms);
}

/** Live regions (A-29): polite for speed, preset, steal; assertive for faults. */
export function announce(msg, assertive = false) {
  const node = document.getElementById(assertive ? "live-assertive" : "live-polite");
  if (node.textContent !== msg) node.textContent = msg;
}
