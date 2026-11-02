// segments.mjs: the demo video's beats (tools/demo/README.md). Each segment is narration,
// then optionally music only; `act(ctx, ms)` performs the on-screen action and must finish
// within `ms` (narration plus gap). drive.mjs schedules them back to back and pads each to
// its slot, so picture, narration and the rig's own audio stay in sync.
//
// Narration facts come only from docs/PRD.md, docs/ARCHITECTURE.md and the Ned Lagin brief;
// nothing here plays or quotes a recording.

const hold = async (ctx, keys, ms) => { for (const k of keys) await ctx.down(k); await ctx.wait(ms); for (const k of keys) await ctx.up(k); };
// a phrase: [key, beats] with beat ms; "-" is a rest
async function phrase(ctx, notes, beat) {
  for (const [k, b] of notes) {
    if (k === "-") { await ctx.wait(b * beat); continue; }
    await ctx.down(k);
    await ctx.wait(b * beat * 0.9);
    await ctx.up(k);
    await ctx.wait(b * beat * 0.1);
  }
}

export const VOICE = "Samantha";
export const RATE = 175; // words a minute (Samantha keeps her own pace)

export const SEGMENTS = [
  {
    id: "attract",
    text: "This is the nineteen seventy-four Seastones Rig: a recreation in the spirit of the computer music rig Ned Lagin played with the Grateful Dead in nineteen seventy-four. An Interdata seven sixteen minicomputer, sixteen wires of digital to analog voltage, and a synthesizer. Everything on this screen comes from a simulated seven sixteen, running a real program.",
    gap: 0.8,
    act: async (ctx, ms) => { await ctx.wait(ms); },
  },
  {
    id: "honest",
    text: "One thing first. You will not hear any real Seastones recordings. There are none on this machine, they are copyrighted, and the project's rules keep recordings out of the exhibit and out of the code. Every sound in this video is our own synthesis, made live by the emulated computer.",
    gap: 0.6,
    act: async (ctx, ms) => { await ctx.wait(ms - 1500); await ctx.go("play"); await ctx.wait(1200); },
  },
  {
    id: "drone",
    text: "This is the Play screen, with the Stadium drone sound. When I press a key, the computer reads it, gives it a voice, and writes a number to a D to A converter. That number becomes the voltage that sets the pitch.",
    gap: 8,
    act: async (ctx, ms) => {
      await ctx.chip("stadium-drone");
      await ctx.wait(800);
      ctx.mark("first-key");
      await hold(ctx, ["z"], 3000);
      await hold(ctx, ["z", "b"], 3500);
      await hold(ctx, ["z", "b", "a"], 5000);
      await hold(ctx, ["x", "n", "s"], 4000);
      await hold(ctx, ["c", "b", "d"], 4000);
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "duet",
    text: "Now the Two-voice duet. A short melody, then chords. The program gives every key its own voice. It has four, so when I add a fifth note, the oldest one gives way. You can see it in the voice list.",
    gap: 9,
    act: async (ctx, ms) => {
      await ctx.chip("two-voice-duet");
      await ctx.wait(600);
      const q = 420;
      await phrase(ctx, [["a", 1], ["s", 1], ["d", 1], ["g", 2], ["d", 1], ["s", 1], ["a", 2]], q);
      await phrase(ctx, [["d", 1], ["g", 1], ["h", 1], ["k", 2], ["h", 1], ["g", 1], ["d", 2]], q);
      await phrase(ctx, [["g", 1], ["f", 1], ["d", 1], ["s", 1], ["a", 3], ["-", 1]], q);
      await hold(ctx, ["a", "d", "g"], 2600);
      // four voices held, then a fifth key: the oldest gives way
      for (const k of ["z", "c", "b", "a"]) { await ctx.down(k); await ctx.wait(500); }
      await ctx.wait(1200);
      await ctx.down("d");
      await ctx.wait(2500);
      for (const k of ["z", "c", "b", "a", "d"]) await ctx.up(k);
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "bell",
    text: "Bell. A short, bright strike that rings out.",
    gap: 9,
    act: async (ctx, ms) => {
      await ctx.chip("bell");
      await ctx.wait(500);
      await phrase(ctx, [["k", 2], ["g", 2], ["d", 2], ["a", 2], ["h", 1], ["g", 1], ["k", 4]], 380);
      await hold(ctx, ["a", "d", "g", "k"], 2500);
      await phrase(ctx, [["d", 1], ["g", 1], ["k", 2], ["l", 2], ["k", 3]], 380);
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "sweep",
    text: "Sweep. The filter opens and closes on its own: a low frequency oscillator moves every voice's cutoff.",
    gap: 9,
    act: async (ctx, ms) => {
      await ctx.chip("sweep");
      await ctx.wait(500);
      await hold(ctx, ["z", "b"], 7000);
      await hold(ctx, ["x", "n"], 6000);
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "rhythm",
    text: "Now Computer rhythm, where the seven sixteen plays by itself. I hold one key, and the program steps through a sixteen step pattern from it, with accents that open the filter. Ned Lagin's own notes mention a computer rhythm output. Ours is an original routine, written in that spirit, not a copy of his.",
    gap: 8,
    act: async (ctx, ms) => {
      await ctx.chip("computer-rhythm");
      await ctx.wait(800);
      await ctx.down("a");
      await ctx.wait(Math.min(15000, ms / 2));
      await ctx.up("a");
      await ctx.down("g");
      await ctx.waitUntil(ms - 300);
      await ctx.up("g");
    },
  },
  {
    id: "arpeggio",
    text: "And an arpeggio. It is still a draft, so it only appears in staff review mode. Hold a chord, and the computer plays its notes one at a time, round and round.",
    gap: 8,
    act: async (ctx, ms) => {
      await ctx.review(true);
      await ctx.wait(400);
      await ctx.chip("arpeggio");
      await ctx.wait(700);
      await ctx.down("a"); await ctx.down("d"); await ctx.down("g");
      await ctx.wait(Math.min(12000, ms / 2));
      await ctx.up("a"); await ctx.up("d"); await ctx.up("g");
      await ctx.down("s"); await ctx.down("h"); await ctx.down("k");
      await ctx.waitUntil(ms - 400);
      await ctx.up("s"); await ctx.up("h"); await ctx.up("k");
      await ctx.review(false);
    },
  },
  {
    id: "computer",
    text: "This is the Computer layer: the seven sixteen's front panel. The address and data lamps show what the processor is doing right now. At full speed they shimmer. Turn the speed down, and you can watch the program's scan loop go round, slower and slower, until it steps one instruction at a time.",
    gap: 3,
    act: async (ctx, ms) => {
      await ctx.chip("stadium-drone");
      await ctx.go("computer");
      // a chord while the lamps shimmer at full speed, and again at 1/3000, where the
      // program is slow enough that the notes arrive late
      await hold(ctx, ["z", "b", "a"], 4000);
      await ctx.speed("div3000");
      await ctx.wait(300);
      await hold(ctx, ["c", "g"], 4200);
      await ctx.wait(500);
      await ctx.speed("crawl");
      await ctx.wait(4000);
      await ctx.speed("step");
      for (let i = 0; i < 12 && ctx.left(ms) > 900; i++) { await ctx.tap("#step-computer"); await ctx.wait(600); }
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "code",
    text: "The Code layer shows the program itself: the real listing of what the emulated machine is running, with a plain English note for each part. In single step, the highlight follows the processor's program counter, line by line.",
    gap: 2,
    act: async (ctx, ms) => {
      await ctx.go("code");
      await ctx.wait(1200);
      while (ctx.left(ms) > 2600) { await ctx.tap("#step-code"); await ctx.wait(800); }
      await ctx.speed("run");
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "patch",
    text: "And the Patch wall. These cables are the synthesizer's real patch. Pull the two cables into the output, and the sound dies: nothing reaches the speaker. Put it back, and it plays again. Change the sound, and the wall rebuilds around the new patch.",
    gap: 5,
    act: async (ctx, ms) => {
      await ctx.go("patch");
      await ctx.wait(1500);
      await ctx.down("a"); await ctx.down("g");
      await ctx.wait(3000);
      await ctx.pull("out.l");
      await ctx.pull("out.r");
      await ctx.wait(2500);
      await ctx.up("a"); await ctx.up("g");
      await ctx.wait(300);
      await ctx.down("d"); await ctx.wait(1800); await ctx.up("d");
      await ctx.tap("#putback-patch");
      await ctx.wait(1500);
      await ctx.down("a"); await ctx.down("g");
      await ctx.wait(3000);
      await ctx.up("a"); await ctx.up("g");
      await ctx.chip("sweep", "#layer-patch");
      await ctx.wait(1500);
      await hold(ctx, ["z", "b"], Math.max(1000, ctx.left(ms) - 1200));
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "similar",
    text: "How close is this to what Ned Lagin built? From the public record: most sources name an Interdata seven sixteen, with magnetic core memory. By Lagin's own account, sixteen channels of D to A conversion voltage controlled an E-mu modular synthesizer, and the keyboard was scanned by software. A Datel data acquisition system sat in the rack, and photos from the August sixth, nineteen seventy-four soundcheck at Roosevelt Stadium, on Nedbase, show an Interdata nameplate. Our program really is a seven sixteen program. It runs on a seven sixteen processor taken from the SIMH simulator, checked instruction by instruction against the stock simulator. Every sound starts with that program writing a word to the converter, and a key reaches the sound in about twenty milliseconds.",
    gap: 1,
    act: async (ctx, ms) => {
      await ctx.go("story");
      // a soft bed of the Sweep sound under the history (the keyboard still plays in Story)
      await ctx.down("z"); await ctx.down("b");
      const n = 6;
      for (let i = 0; i < n; i++) { await ctx.tap(`#layer-story .dot >> nth=${i}`); await ctx.wait(Math.max(1500, (ms - 1500) / n - 300)); }
      await ctx.up("z"); await ctx.up("b");
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "differs",
    text: "And how it differs. We do not have Lagin's code, his channel map, his keyboard interface, or his converter's word format. All of that is our design, and the machine's timing is an estimate. Our synthesizer is a software model, not analog E-mu hardware, so there is no drift and no analog noise. We use four voices by default; we don't know how many Ned drove. His rig was a live performance instrument that also processed Garcia and Lesh. Ours is a toy, and a teaching piece. One lead remembers a Model seventy or seventy-four, while the public record says seven sixteen; that is still open. Ned's notes say the computer's outputs were sometimes missing from the PA mix, so any reconstruction from recordings would only be a hypothesis. And nothing here uses Ned's photos, words or recordings.",
    gap: 1,
    act: async (ctx, ms) => {
      await ctx.tap("#about");
      await ctx.down("x"); await ctx.down("n");
      await ctx.wait(Math.max(2000, ms - 1500));
      await ctx.up("x"); await ctx.up("n");
      await ctx.tap("#about-close");
      await ctx.waitUntil(ms);
    },
  },
  {
    id: "close",
    text: "What's next: listening to the sounds and tuning them, connecting real hardware, a review by the museum, advice from counsel, and asking for permissions before anything goes further. Thanks for watching.",
    gap: 5,
    act: async (ctx, ms) => {
      await ctx.go("play");
      await ctx.chip("stadium-drone");
      await ctx.wait(600);
      await hold(ctx, ["z", "b", "a"], 6000);
      await hold(ctx, ["c", "b", "g"], 5000);
      await hold(ctx, ["z", "b", "a"], Math.max(1500, ctx.left(ms) - 3500));
      await ctx.tap("#home");
      await ctx.waitUntil(ms);
    },
  },
];
