// Multi-touch through the Chrome DevTools protocol (UI-23): real touch points, held as long
// as the test wants, so several on-screen keys can be down at once.
export async function touchSession(page) {
  const cdp = await page.context().newCDPSession(page);
  let points = [];
  const send = (type) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: points.map((p) => ({ x: p.x, y: p.y, id: p.id, radiusX: 4, radiusY: 4, force: 1 })) });
  return {
    /** Put fingers down at element centres (or {x,y}); returns their ids. */
    async down(targets) {
      const add = [];
      for (const t of targets) {
        const box = t.x !== undefined ? t : await t.boundingBox();
        const x = t.x !== undefined ? t.x : box.x + box.width / 2;
        const y = t.y !== undefined ? t.y : box.y + box.height * 0.75;
        const id = (points.reduce((m, p) => Math.max(m, p.id), 0) || 0) + 1 + add.length;
        add.push({ x, y, id });
      }
      points = points.concat(add);
      await send("touchStart");
      return add.map((p) => p.id);
    },
    async move(id, x, y) {
      points = points.map((p) => (p.id === id ? { ...p, x, y } : p));
      await send("touchMove");
    },
    async up(ids) {
      // CDP compares each event with the previous one: a touchMove that leaves a point out
      // releases it; touchEnd (no points) releases the rest.
      const gone = points.filter((p) => !ids || ids.includes(p.id));
      points = points.filter((p) => ids && !ids.includes(p.id));
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: gone.map((p) => ({ x: p.x, y: p.y, id: p.id })) });
    },
    async cancel() {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchCancel", touchPoints: [] });
      points = [];
    },
  };
}
