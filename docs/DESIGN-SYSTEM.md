# The 1974 Seastones Rig: Visual Design Direction

**Version:** 0.1 · **Date:** 2026-10-31 · **Status:** Draft for Nick's review (the DES-1 gate)
**Author:** Nick D. with the UX Design agent
**Reads with:** `docs/UX.md` (behaviour, copy, accessibility), `docs/PRD.md` v0.1 (DES-1 to DES-5),
`docs/ux/index.html` (the mockups; open it in a browser)
**Sibling reference:** the museum's Model 4 kiosk (a separate project)

Everything here was prototyped in the HTML mockups before it was written down. If this file and a
mockup disagree, the mockup is the evidence and this file needs fixing.

---

## 1. The idea in one paragraph

**A machine room at dusk, lit by its own lamps.** The Model 4 kiosk is the daylight Interdata: cream
panel, red enclosure, paper. The Seastones Rig is the same family at night, the way the machine would
have looked in a stadium soundcheck: a near-black violet room, a low sunset smear along the bottom, a
sea of ripples, and every bit of information carried by something that glows. The computer's lamps are
the brightest, warmest things on the screen. The synthesizer is cool brushed metal with coloured cable.
The lettering is heavy, warm and slightly hand-cut, like a 1970s concert poster. Nothing is chrome,
nothing is neon, nothing is a stock icon.

The name is the clue to the picture. **Seastones** gives us two original motifs that need nothing from
anyone else's artwork:

- **The wave line**: a sine ribbon in amber, rose and violet. It is the logo's base, the footer of the
  attract screen, the ripple field behind the title and the faint contour lines behind every screen.
- **The stones**: smooth pebbles on the wave. There are **sixteen** of them on the attract screen, one
  for each D/A channel, and the computer's scan walks along them like a hand along a keyboard. The
  motif says "sixteen wires" before anyone reads a word.

### 1.1 What we take, and what we leave alone

| Influence | What we take | What we do not take |
|---|---|---|
| **Interdata front panels** (and our Model 4 kiosk) | The cream panel face, the red enclosure, tracked caps labels, round lamps in groups of four with a hex digit under each group, knob legends. Same lamp amber as the Model 4 kiosk. | Interdata logo artwork. The nameplate is plain tracked text. |
| **E-mu modular** and other 1970s modulars | Brushed dark panels, silkscreened caps labels, big round jacks with a numbered ring, a thin coloured band per module type, plug-and-cable patching with a believable droop. | E-mu logos, colour schemes or reproduced panel layouts (RIGHTS-5). Our module names are generic (VOICE, FILTER, ECHO). |
| **Dead-era concert posters** | Heavy slab lettering with a triple offset shadow, a hand-cut wobble, warm sunset gradients, concentric ripples, ticket-stub framing (the Roosevelt Stadium screen). | No skulls, roses, bears, lightning bolts, Steal Your Face, no psychedelic lettering that spells anything Dead-branded, no band names set as a logo. "Grateful Dead" appears only as plain words in copy and the disclosure (RIGHTS-4). |
| **Our own drawings** | Everything in the rig, the stones, the stadium, the core-memory plane, the 7/16 panel. | Nothing traced or closely copied from Ned Lagin's photographs (RIGHTS-3). The 7/16 panel layout is marked *inferred* until a bitsavers figure is found (R7). |

Not synthwave. No grids receding to a sun, no magenta/cyan neon pair. Our palette is warm
(amber, ember, rose) against a violet night with one cool accent (teal) reserved for signals inside
the synthesizer.

---

## 2. Colour

Dark only. A kiosk is always in the same lighting, so there is no light mode and no theme switch.

### 2.1 Tokens

| Token | Hex | Role | Contrast (against) |
|---|---|---|---|
| `--night` | `#100C16` | Stage background, deepest | : |
| `--night-2` | `#1C1424` | Cards, key wells | : |
| `--dusk` | `#2B1B33` | Raised panels, code block headers | : |
| `--dusk-2` | `#3A2442` | Highest surface, modals | : |
| `--cream` | `#F6EBD0` | Primary text, white keys' warm white | 16.3:1 on night |
| `--muted` | `#B9AEC6` | Secondary text, captions | 9.1:1 on night, 8.5:1 on night-2, 7.6:1 on dusk |
| `--amber` | `#F2A83B` | **The computer.** Lamps, current instruction, primary action, active tab | 9.6:1 on night |
| `--amber-hot` | `#FFE2A0` | Lamp core, pressed key highlight | decorative |
| `--ember` | `#E4572E` | Poster shadow, module band, output | decorative |
| `--rose` | `#F07FA3` | Gate signals, fault kicker, poster rule | 7.6:1 on night |
| `--violet` | `#7B5BB0` | Poster depth, tone-CV cables, filter band | decorative |
| `--teal` | `#4FC3B5` | **Signal inside the synthesizer.** Audio cables, selected chip, "done" | 9.0:1 on night |
| `--red` | `#B83A24` | Interdata enclosure (Model 4 kiosk red), panel pointers | decorative |
| `--red-deep` | `#8E2716` | HOME button fill, large hex digits on the panel face | 7.8:1 cream on it; 6.3:1 on panel face (large text only) |
| `--panel-face` | `#E4DCCB` | The 7/16 panel face (Model 4 kiosk value) | : |
| `--ink` | `#1C1A17` | Text on cream and on amber | 12.7:1 on panel face, 9.2:1 on amber |
| `--ink-muted` | `#3E3A32` | Secondary text on panel face | 8.3:1 on panel face |
| `--brushed` / `--brushed-2` | `#23262B` / `#30343A` | Module plates | : |
| `--silver` | `#D5D8DC` | Module labels | 10.6:1 on brushed |
| `--silver-dim` | `#B5BAC1` | Knob legends | 7.8:1 on brushed |
| `--lamp-off` | `#3A352D` | Unlit lamp | decorative |
| `--walnut` | `#4A2E1C` / `#6B4326` | Reserved for the Phase 2 enclosure and the cabinet photo-free illustration | : |

All contrast figures were computed (WCAG relative luminance), not eyeballed. Body text is at
least 7:1 everywhere (NFR-10). `--red-deep` on the panel face is 6.3:1, so it is used only for
large text (the 34 px hex digits and the 24 px bold panel legends).

### 2.2 Colour means something

| Colour | Always means | Never used for |
|---|---|---|
| **Amber** | The computer is doing it (lamps, the current instruction, the scan), or "press this" (primary buttons, active tab) | Decoration |
| **Teal** | A signal inside the synthesizer; a thing is done or selected | Computer activity |
| **Rose** | A gate (note on/off) signal; something needs a moment (fault kicker) | Errors that blame the visitor |
| **Violet** | Tone and modulation voltages | Anything interactive |
| **Red-deep** | Leave: HOME, and the Interdata enclosure | Warnings (there are no red warnings on the floor) |

**Colour is never the only carrier** (NFR-10). The three D/A groups are also separated by position and
labelled PITCH / GATE / TONE. Active tabs are also filled and have a lit lamp. Selected presets also
change shape (a filled pill). Cables carry their colour but every jack has a text label.

### 2.3 Atmosphere (the stage behind everything)

Built from four layers, back to front. Every layer is a pre-rendered asset in the build (an SVG or
PNG), not a live filter, so it costs nothing at 50 fps:

1. **Sky**: vertical gradient `#0C0912` → `#1A1124` (55%) → `#3A1F38` (85%) → `#5A2A3A`.
2. **Dusk glow**: radial `#F2A83B` at 30% opacity rising from the bottom centre, fading through ember.
3. **Wave contours**: 14 sine ribbons from y=520 down, alternating amber, rose, violet, 5% to 22% opacity.
   On the attract screen they swell to a ripple field of 14 concentric circles around the title.
4. **Grain**: fractal noise at 5% opacity. In the build this is a tiled 256 px PNG, because a live SVG
   filter over a 1080p stage is the wrong cost.

---

## 3. Typography

The Model 4 kiosk already bundles Oswald, IBM Plex Sans and JetBrains Mono and names a Rockwell-style
slab in its stack. We reuse that set, so one fonts folder serves the whole museum.

| Role | Production font (bundled, OFL) | Mockup stack (system) | Used for |
|---|---|---|---|
| **Display** | Roboto Slab ExtraBold 800 | Rockwell, Rockwell Std, Bevan, Roboto Slab, Georgia | The title, story headlines, block titles, big numerals ("10 s") |
| **Label** | Oswald 600/700, caps, tracked +0.08 to +0.2em | Avenir Next Condensed, Oswald, Arial Narrow | Panel legends, tabs, buttons, chips, section kickers |
| **Body** | IBM Plex Sans 400/600 | IBM Plex Sans, Avenir Next, Helvetica Neue | Story copy, captions, hints |
| **Mono** | JetBrains Mono 500/700 | JetBrains Mono, SF Mono, Menlo | The code listing, registers, staff diagnostics |

If the museum later licenses Rockwell itself, swap the display role only. Nothing else changes.

### 3.1 Scale (1080p stage; physical size on the 24″ panel at 0.277 mm/px)

| Style | px | em height | Use |
|---|---|---|---|
| Poster title | 212 | 58.7 mm | SEASTONES on the attract screen (SVG, three-layer) |
| Display XL | 92 | 25.5 mm | "Still playing?" |
| Display L | 76 to 80 | 21 to 22 mm | Fault headline |
| Display M | 46 to 56 | 13 to 15 mm | Story and block titles, tagline |
| **Body** | **32** | **8.9 mm** | Story copy, block notes. Never smaller for reading copy |
| UI | 28 to 30 | 8 mm | Tab labels, button labels, hex digits (34) |
| Caption | 24 to 26 | 7 mm | Station captions, hints, readout lines |
| **Legend (floor)** | **22** | **6.1 mm, cap height 4.3 mm** | Panel legends, jack labels, key names, footer. Nothing below this, anywhere |

Cap height at 22 px is 4.3 mm, just above the 4.19 mm the Model 4 kiosk derived for a 600 mm
reading distance (0.4° of arc). Reading copy is at 32 px (cap height 6.5 mm).
**This is a change to PRD NFR-11, which says "body ≥ 32 px" without allowing for the dense rig
screens. See UX §13.**

### 3.2 The poster lettering recipe

The title is the one place we do something unusual. It is SVG text, converted to outlines in the
build, so it never depends on a font being present.

1. Heavy slab caps, letter-spacing +6 px.
2. **Three layers:** violet `#4A3070` offset (10, 10); ember `#E4572E` offset (5, 5); the face on top.
3. Face fill is a vertical gradient `#FFF4DE` → `#F6EBD0` → `#F2A83B` (a warm lit-from-above ramp), with a
   2 px dark-violet outline.
4. A 2 px cream hairline at 55% opacity, offset (−3, −3), as a catch-light on the top-left edges.
5. Whole group through `feTurbulence` (base frequency 0.011 × 0.02, 2 octaves) into `feDisplacementMap`
   at scale 9, for a hand-cut wobble. In the build, bake the displaced result to an SVG path so it is
   free at runtime.
6. Above it, "THE 1974" in Oswald at 26 px tracking in amber. Below it, "RIG" flanked by two rose rules.

---

## 4. Drawing style for the rig

One style for the computer, the synthesizer, the keyboard and the story illustrations:

- **Flat shapes, one soft highlight, one hard shadow.** Every object has a single elliptical
  highlight (white at 35 to 60%) up and to the left, and a hard offset shadow below (the "0 6px 0"
  buttons and keys). No gradients except to suggest a lit metal or ceramic surface.
- **Real hardware proportions.** Lamps are 34 px discs (9.4 mm). Jacks are 50 px outer ring, 28 px hole.
  Knobs are 56 to 64 px with a red pointer. Panel corner radius 10 px, screws in the corners.
- **Silkscreen legends** in Oswald caps, in `--silver` on brushed plates and `--ink` on the panel face.
- **Stones** are ellipses with a radial gradient `#F1E6CF` → `#9D8D74` → `#4E4234`, a white highlight
  ellipse, and a darker rim. When scanned they take on a screen-blended amber bloom.
- **Cables** are three strokes: a dark offset shadow at 35% (7 px down), the coloured body (10 px,
  round caps), a thin white catch-light at 38%. Plugs are a dark disc with a coloured ring and centre.

### 4.1 The 7/16 front panel

Cream face (`--panel-face`) inside a red enclosure with a lighter inner edge (the Model 4 kiosk
treatment), a grey header strip with the nameplate in tracked caps, two rows of 16 lamps grouped in
fours with a hex digit under each group, and a large speed knob with its legends printed around it.
The layout is **inferred** from the Model 4 and from general 1970s Interdata practice and is labelled
"Panel drawn from Interdata documentation" on the glass. It must be redrawn from a bitsavers
figure before DES-1 sign-off (PRD R7). Everything about the lamps and knob behaviour is independent of
that redraw.

### 4.2 Lamps

A lamp is two layers: a dark unlit disc, and a lit layer whose **opacity is the lamp's brightness**.
Brightness is not on/off. It is the fraction of recent instructions during which that bit was set
(UX §6.3). At full speed a lamp that is set half the time glows at half brightness, exactly as a real
front-panel lamp does. This one rule is what makes the panel honest, and it also means nothing on
screen ever strobes (NFR-10): brightness is smoothed over 80 ms and updated at 30 Hz.

Lit lamp: radial `#FFFBE8` → `#FFE2A0` (35%) → `#F2A83B` (75%) with a 16 px, 4 px-spread amber glow.

---

## 5. Components

Every component is shown in the mockups. Sizes are on the 1920×1080 stage. The floor minimum for
any touch target is **54 px (15 mm)**; our smallest interactive element is 72 px (19.9 mm).

| Component | Size | States | Notes |
|---|---|---|---|
| **Dock tab** | 280 × 108, radius 18 | rest · pressed (drops 3 px) · active (amber fill, lit lamp, glow) | Icon 46 px + label 28 px caps + 22 px caption. Five tabs, then spacer, then HOME |
| **HOME** | ~190 × 108, red-deep | rest · pressed | Always the right-most item. Never moves |
| **FULL SPEED** | ~260 × 108, amber | appears only when speed ≠ RUN | Sits between the tabs and HOME |
| **Button (large / small)** | 108 / 72 high, radius 18 / 14 | rest · pressed · disabled (45%) | Amber = primary, dark = secondary |
| **Chip (preset)** | 72 high, pill | rest · selected (teal fill, dark text) | Nowrap, caps, 26 px |
| **Detent button** | 72 × 82 min | rest · selected (amber) | One per speed position. Same labels as the knob legends |
| **Knob** | 150 (play), 300 incl. legends (panel) | detent positions, 50° apart | Drag horizontally or tap. Spring snap, 300 ms |
| **Station card** | 380 high, radius 22 | rest · pressed | The five-stage chain on Play. Tapping opens the layer that explains it |
| **White key / black key** | 82 × 190 (on Play) / 54 × 62% | rest · down (amber, drops 4 px, glow) | Mirrors the physical 37-key keyboard exactly: C3 to C6 |
| **Jack** | 50 ring, 68 touch | rest · occupied · being dragged to | 44 px magnetic snap |
| **Cable** | 10 stroke | rest · lifted (plug 1.15×, shadow deeper) · removing | Droop `sag = 34 + 0.13 × distance` |
| **Lamp** | 26 to 36 | brightness 0..1 | UX §6.3 |
| **Card** | radius 22, `--night-2` gradient, 2 px border `#3F3050` | rest · "current" (amber border) | Disclosure card has a dashed amber border |
| **Seal** | 88 px | static | "A RECREATION · IN THE SPIRIT OF", rotating text on a circle, our stones inside |
| **Footer line** | 40 high | static | The disclosure one-liner and the "About this recreation" link, on every layer |

---

## 6. Motion tokens

Motion explains the machine; it never decorates it (DES-2). Full principles are in UX §7.

| Token | Value | Use |
|---|---|---|
| `--t-press` | 120 ms, ease-out | Button press, key down |
| `--t-snap` | 300 ms, `cubic-bezier(.3,1.4,.5,1)` | Knob detent, plug snap |
| `--t-layer` | 280 ms, ease-in-out | Switching layer: content slides 24 px and fades; the dock never moves |
| `--t-scroll` | 250 ms, ease-out | Code listing follows the current instruction |
| `--t-fade` | 400 ms | Veil, hint, toasts |
| `--lamp-smooth` | 80 ms low-pass, 30 Hz update | Lamp brightness |
| `--cable-settle` | 220 ms damped spring | Cable after a plug lands |
| Scan sweep | 3.2 s per pass | Attract: the glow moving along the stones |
| Max flash rate | none above 3 Hz anywhere; no area flash | NFR-10 |

`prefers-reduced-motion` is honoured, and the staff screen has an override. Reduced motion removes:
the scan sweep (replaced by a static glow on one stone), the ripple drift, spring overshoot, layer slides
(replaced by a 120 ms cross-fade), and the CTA pulse. It keeps everything that carries meaning: lamps,
meters, the scope, cables.

---

## 7. Review checklist: "is it beautiful?"

PRD DES-1 asks for a visual review by Nick, DES-2 for smooth motion, DES-3 for a listening gate, DES-4
for a floor test and M8 for all of them signed. "Beautiful" has to be a thing someone can fail. This
list is the visual half of the gate. It is run **on the station itself**, at floor brightness, with the
real speakers on, by Nick plus at least one design-literate and one synth-literate reviewer.
Each item is pass/fail with a stated test. A fail is fixed or explicitly deferred in writing by Nick.

**Identity and distinctiveness (DES-1)**

| ID | Test | Pass when |
|---|---|---|
| B-01 | **The poster test.** Show a 3-second still of the attract screen to three people who have not seen it, then ask them to describe it | At least two say something about waves, stones, sunset or a poster, and none says "looks like a default dashboard" |
| B-02 | **The squint test.** Squint at each of the seven screens (attract, play, computer, code, patch, story, fault) | One thing glows brightest (lamps, the current instruction, the scan), and it is the right thing |
| B-03 | **The stock test.** Check every icon, button and illustration against a stock library | Zero stock icons or default component-library controls on the floor. Every icon is in the drawing style of §4 |
| B-04 | **The wall test.** Put all seven screens side by side | They are clearly one family: same dock, same footer, same palette roles, same type roles |
| B-05 | **The rights test.** Review all artwork against §1.1 | No band artwork or lettering; no E-mu, ARP, Buchla or Interdata logos; no traced Lagin photograph |

**Composition and craft (DES-1)**

| ID | Test | Pass when |
|---|---|---|
| B-06 | **Alignment.** Overlay a 12-column grid on a capture of each screen | All cards, tabs and keys sit on the grid; no 1 to 2 px drifts |
| B-07 | **Clipping and overlap.** Capture every state of every screen (including 6 speed positions and the no-sound hint) | No clipped text, no text over cables or other text that makes it unreadable, no overflow of a card |
| B-08 | **Legibility from distance.** Stand 600 mm from the screen | All reading copy, the lamps' hex digits and every dock label are readable without leaning in; nothing is below 22 px |
| B-09 | **Contrast.** Run a contrast checker on captures | All body text ≥ 7:1; large text ≥ 4.5:1 (UX §12 lists the exceptions, each with a number) |
| B-10 | **Material.** Zoom a capture to 200% | Highlights, shadows and edges are consistent (§4); no banding in the sky gradient (grain present) |
| B-11 | **Empty and loading states.** Capture attract, no-cables patch, fault, starting | Each looks designed, not broken |

**Light and motion (DES-2)**

| ID | Test | Pass when |
|---|---|---|
| B-12 | **Frame rate.** Record with the browser's performance overlay while 8 voices play and the speed knob moves | ≥ 50 fps on layers 1 to 4; lamps update ≥ 30 Hz (NFR-9) |
| B-13 | **No strobe.** Record the stage at 240 fps (phone slow-motion) in RUN with 8 keys held | No area brightens and darkens more than 3 times a second |
| B-14 | **Meaning.** Watch a 60-second screen recording with the sound off | A viewer can say when keys were pressed, when voices were stolen, and when the speed was changed, from the screen alone |
| B-15 | **Reduced motion.** Turn it on from the staff screen | §6 list removed; everything meaningful still moves |
| B-16 | **Touch response.** High-speed capture of a press | Visible feedback ≤ 100 ms (NFR-9) |

**Honesty and story (DES-1, M9)**

| ID | Test | Pass when |
|---|---|---|
| B-17 | **The screenshot test.** Take 20 random frames from a 10-minute screen recording | Every frame shows the disclosure footer; none implies Lagin's involvement |
| B-18 | **The drawing test.** Ask: "Which parts of this screen did we make up?" | The visitor copy and labels say so wherever a layout or a number is ours (channel map, panel drawn from documentation, our program) |
| B-19 | **The hypothesis test (when Layer 6 is on).** Look at every frame during a Seastones passage | The "Our best guess" ribbon is on every frame |

**Sound and picture together (DES-3)**

| ID | Test | Pass when |
|---|---|---|
| B-20 | **The listening gate.** Default patch, every preset, at floor volume, on the station speakers, with the screen in view | Nick and one synth-literate reviewer both sign: "it sounds as good as it looks". No raw saw, no test tone, no clicks |
| B-21 | **Sync.** Press a key while watching the key, lamp and scope | The key lights, the matrix lamp, the voice slot and the scope respond together; to the eye no layer lags another |
| B-22 | **The slow-down moment.** Run the speed demo with a naive tester | They say, in their own words, that the computer is "thinking", "slow" or "taking its time", and they can find the way back to full speed unprompted |

**Floor test (DES-4)**

| ID | Test | Pass when |
|---|---|---|
| B-23 | **Glare and brightness.** In the museum's real lighting | Screen is readable without a hand shading it; the dark key wells are still visible; lamps still read as lit |
| B-24 | **Open-day observation.** One open day with a docent | No visitor needs instructions to make sound; the docent logs every confusion; each is fixed or deferred |

Record the result of each run in `docs/ux/review-log.md` (date, reviewers, item, pass or fail, note).
M8 is met when every item passes or carries a signed deferral.

---

## 8. Production notes

- **Assets are authored as SVG** (stones, wave contours, jacks, knobs, module plates, panel, story
  illustrations) and rendered at build time to the stage size. Live SVG filters (the title wobble,
  the grain) are baked.
- **One stage, one scale.** The stage is authored at 1920 × 1080 and scaled to the screen with one
  transform, as in the mockups. The 15.6″ mirror (DES-5) uses the same stage; only the touch-target
  floor is re-checked (UX §9).
- **No external requests.** All fonts and assets are local (KIOSK-6).
- **Colour tokens and type roles live in one file** (`src/web/tokens.css` suggested), so a retheme
  is a one-file change.
- **The mockups are not the build.** They use a plain browser synth for sound and a scripted stand-in
  for the emulator. They are the visual contract, not the code to ship.
