// attract.js: layer 0, the attract screen (KP-01; PLAY-1, PLAY-2, UX 5.1, DESIGN-SYSTEM 3.2).
//
// Silent (A-4). Poster lettering, sixteen stones on the wave (one per D/A channel), the
// PLAY THE KEYS pill and a strip of real keys. Any touch anywhere, or any key, starts Play;
// a key also sounds at once, because the engine is always running the real scan loop and
// the touch bitmap is sent before the layer changes (UX 6.4).
//
// The stones' resting glow is the real address lamps' duty cycle (the computer looking for
// you); the 3.2 s sweep across them is decoration and goes with reduced motion. While the
// station is starting, the stones light four at a time as each stage really comes up and
// the pill reads WAKING UP.

import { el, esc } from "./blocks.js";
import { S } from "./strings.js";
import { Keyboard } from "./keyboard.js";
import { paint } from "./lamps.js";

const STONES = [[150, 745, 34], [257, 759, 42], [364, 762, 50], [471, 752, 38], [578, 737, 46], [685, 727, 34], [792, 731, 42], [899, 745, 50],
  [1006, 759, 38], [1113, 762, 46], [1220, 752, 34], [1327, 736, 42], [1434, 727, 50], [1541, 731, 38], [1648, 745, 46], [1755, 759, 34]];

function poster(words) {
  const t = esc(words.title.toUpperCase());
  const f = "font-family=\"Roboto Slab, Rockwell, Georgia, serif\" font-weight=\"800\"";
  return `<svg width="1500" height="470" viewBox="0 0 1500 470" aria-hidden="true" style="will-change:transform"><defs>` +
    `<filter id="wob" x="-5%" y="-10%" width="110%" height="130%"><feTurbulence type="fractalNoise" baseFrequency=".011 .02" numOctaves="2" seed="7" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="9"/></filter>` +
    `<linearGradient id="cf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF4DE"/><stop offset=".55" stop-color="#F6EBD0"/><stop offset="1" stop-color="#F2A83B"/></linearGradient></defs>` +
    `<g filter="url(#wob)"><text x="750" y="86" text-anchor="middle" font-family="Oswald, Arial Narrow, sans-serif" font-weight="700" font-size="54" letter-spacing="26" fill="#F2A83B">${esc(words.kicker.toUpperCase())}</text>` +
    `<text x="750" y="320" text-anchor="middle" ${f} font-size="212" letter-spacing="6" fill="#4a3070" transform="translate(10,10)">${t}</text>` +
    `<text x="750" y="320" text-anchor="middle" ${f} font-size="212" letter-spacing="6" fill="#E4572E" transform="translate(5,5)">${t}</text>` +
    `<text x="750" y="320" text-anchor="middle" ${f} font-size="212" letter-spacing="6" fill="url(#cf)" stroke="#2b1b33" stroke-width="2">${t}</text>` +
    `<text x="750" y="320" text-anchor="middle" ${f} font-size="212" letter-spacing="6" fill="none" stroke="#fff6d8" stroke-width="2" opacity=".55" transform="translate(-3,-3)">${t}</text>` +
    `<g transform="translate(750,412)"><path d="M-500 -16H-110M110 -16H500" stroke="#F07FA3" stroke-width="5"/><text text-anchor="middle" ${f} font-size="76" letter-spacing="30" fill="#F6EBD0">${esc(words.end.toUpperCase())}</text></g></g></svg>`;
}

function stonesSvg() {
  let h = `<svg viewBox="0 0 1920 1080" width="1920" height="1080" aria-hidden="true"><defs><radialGradient id="stn" cx=".38" cy=".32"><stop offset="0" stop-color="#f1e6cf"/><stop offset=".6" stop-color="#9d8d74"/><stop offset="1" stop-color="#4e4234"/></radialGradient></defs>`;
  const cols = ["#F2A83B", "#F07FA3", "#7B5BB0"];
  for (let i = 0; i < 14; i++) {
    h += `<circle cx="960" cy="450" r="${180 + i * 74}" fill="none" stroke="${cols[i % 3]}" stroke-width="${2 + (i % 2)}" opacity="${(0.34 - i * 0.022).toFixed(3)}"/>`;
  }
  const waves = [[790, 26, "#F2A83B", 4, 0.6], [812, 23, "#F07FA3", 3, 0.52], [834, 20, "#7B5BB0", 4, 0.44], [856, 17, "#4FC3B5", 3, 0.36], [878, 14, "#F2A83B", 4, 0.28]];
  for (const [y, a, c, w, o] of waves) {
    h += `<path d="M-40 ${y} q120 -${a} 240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0 t240 0" fill="none" stroke="${c}" stroke-width="${w}" opacity="${o}"/>`;
  }
  STONES.forEach(([x, y, rx], i) => {
    const ry = Math.round(rx * 0.62);
    h += `<g transform="translate(${x} ${y})"><ellipse class="lit" data-stone="${i}" rx="${rx + 18}" ry="${ry + 16}" fill="#F2A83B" style="opacity:var(--b,0);mix-blend-mode:screen;filter:blur(10px)"/>` +
      `<ellipse rx="${rx}" ry="${ry}" fill="url(#stn)" stroke="#0007" stroke-width="2"/><ellipse rx="${Math.round(rx * 0.4)}" ry="${Math.round(ry * 0.2)}" cx="${-Math.round(rx * 0.24)}" cy="${-Math.round(ry * 0.38)}" fill="#fff" opacity=".35"/>` +
      `<ellipse class="gl${i === 7 ? " rest" : ""}" rx="${rx + 14}" ry="${ry + 14}" fill="#F2A83B" style="mix-blend-mode:screen;filter:blur(8px);animation-delay:${(i * 0.2).toFixed(1)}s"/></g>`;
  });
  return h + "</svg>";
}

export function mount(section, { onWake }) {
  section.textContent = "";
  const att = el("div", "att sweep");
  att.innerHTML = stonesSvg();
  att.firstChild.classList.add("stones");
  const p = el("div", "poster");
  p.innerHTML = poster({ kicker: S("attract", "kicker"), title: S("attract", "title"), end: S("attract", "title-end") });
  att.appendChild(p);
  const lines = el("div", "lines");
  lines.appendChild(el("div", "tagline", S("attract", "tagline")));
  lines.appendChild(el("div", "sub", S("attract", "sub")));
  att.appendChild(lines);
  const pill = el("div", "pill");
  pill.id = "attract-pill";
  pill.style.top = "812px";
  pill.innerHTML = '<svg width="54" height="54" viewBox="0 0 48 48" aria-hidden="true"><rect x="4" y="12" width="40" height="26" rx="4" fill="none" stroke="currentColor" stroke-width="3.5"/><rect x="11" y="12" width="6" height="15" fill="currentColor"/><rect x="21" y="12" width="6" height="15" fill="currentColor"/><rect x="31" y="12" width="6" height="15" fill="currentColor"/></svg>';
  const pillText = el("span", null, S("attract", "pill"));
  pill.appendChild(pillText);
  att.appendChild(pill);
  const hint = el("div", "hint2", S("attract", "hint"));
  hint.style.top = "926px";
  att.appendChild(hint);
  section.appendChild(att);
  const kbBox = el("div");
  kbBox.style.cssText = "position:absolute;left:58px;top:896px";
  new Keyboard(kbBox, { width: 1804, height: 72, slim: true });
  section.appendChild(kbBox);
  section.addEventListener("pointerdown", () => onWake("touch"));
  const lit = [...att.querySelectorAll("[data-stone]")];

  return {
    paint(state, banks, ready, stages) {
      const want = ready ? S("attract", "pill") : S("attract", "pill-waking");
      if (pillText.textContent !== want) pillText.textContent = want;
      pill.classList.toggle("waking", !ready);
      att.classList.toggle("sweep", ready);
      if (!ready) {
        const up = stages ? ["computer", "program", "synth", "output"].filter((k) => stages[k]).length : 0;
        lit.forEach((s, i) => paint(s, i < up * 4 ? 0.8 : 0));
      } else {
        lit.forEach((s, i) => paint(s, state ? banks.addr.b[i] * 0.55 : 0));
      }
    },
  };
}
