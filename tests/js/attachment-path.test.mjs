import test from "node:test";
import assert from "node:assert/strict";
import { attachmentPath, edgePath } from "../../openartifact/static/js/editor/geometry.js";
import { EDGE_KINDS } from "../../openartifact/static/js/editor/edge-kinds.js";

// A pure geometry check of the one rule every tool kind shares: the line from the tool's port (top of the tool) to the agent's port (bottom of
// the agent) never runs through either card, wherever the tool sits.

/** Sample the points of an SVG path made of M, L, Q and C commands. */
function sample(d) {
  const tokens = d.match(/[MLQC]|-?\d+(?:\.\d+)?/g);
  const points = [];
  let i = 0;
  let cur = null;
  const num = () => Number(tokens[i++]);
  while (i < tokens.length) {
    const cmd = tokens[i++];
    if (cmd === "M" || cmd === "L") {
      const next = { x: num(), y: num() };
      if (cmd === "L" && cur) for (let k = 0; k <= 20; k += 1) points.push({ x: cur.x + ((next.x - cur.x) * k) / 20, y: cur.y + ((next.y - cur.y) * k) / 20 });
      cur = next;
      points.push(cur);
    } else if (cmd === "Q") {
      const c = { x: num(), y: num() };
      const e = { x: num(), y: num() };
      for (let k = 0; k <= 20; k += 1) {
        const t = k / 20;
        points.push({ x: (1 - t) ** 2 * cur.x + 2 * (1 - t) * t * c.x + t * t * e.x, y: (1 - t) ** 2 * cur.y + 2 * (1 - t) * t * c.y + t * t * e.y });
      }
      cur = e;
    } else {
      const c1 = { x: num(), y: num() };
      const c2 = { x: num(), y: num() };
      const e = { x: num(), y: num() };
      for (let k = 0; k <= 50; k += 1) {
        const t = k / 50;
        const u = 1 - t;
        points.push({ x: u ** 3 * cur.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * e.x, y: u ** 3 * cur.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * e.y });
      }
      cur = e;
    }
  }
  return points;
}

const inside = (p, b) => p.x > b.x + 1 && p.x < b.x + b.width - 1 && p.y > b.y + 1 && p.y < b.y + b.height - 1;
const agent = { x: 400, y: 300, width: 250, height: 84 };
const tool = (x, y) => ({ x, y, width: 180, height: 52 });
const portsOf = (a, t) => ({ from: { x: t.x + t.width / 2, y: t.y }, to: { x: a.x + a.width / 2, y: a.y + a.height } });

const PLACES = {
  below: tool(430, 504),
  "below, apart": tool(700, 520),
  above: tool(430, 160),
  "above, left": tool(150, 120),
  "left, same line": tool(120, 310),
  "right, same line": tool(720, 310),
  "left, lower than the agent's top": tool(150, 380),
  "overlapping x-range, just above": tool(450, 230),
};

for (const style of ["curved", "straight", "elbow"]) {
  for (const [place, t] of Object.entries(PLACES)) {
    test(`the attachment of a tool (${place}, ${style}) runs through neither card`, () => {
      const { from, to } = portsOf(agent, t);
      const d = attachmentPath(from, to, t, agent, { routed: true, style });
      const points = sample(d);
      assert.ok(points.length > 4, d);
      for (const p of points) {
        assert.equal(inside(p, agent), false, `${place}: a point of the line is inside the agent: ${JSON.stringify(p)} in ${d}`);
        assert.equal(inside(p, t), false, `${place}: a point of the line is inside the tool: ${JSON.stringify(p)} in ${d}`);
      }
      // it starts at the tool's port and ends at the agent's port
      assert.deepEqual(points[0], from);
      assert.ok(Math.abs(points.at(-1).x - to.x) < 0.01 && Math.abs(points.at(-1).y - to.y) < 0.01, "the line ends at the agent's port");
    });
  }
}

test("a tool below its agent keeps the short direct line (the curve up), a tool above takes the way round", () => {
  const below = portsOf(agent, tool(430, 504));
  assert.match(attachmentPath(below.from, below.to, tool(430, 504), agent), /^M [\d.]+ [\d.]+ C /);
  const above = portsOf(agent, tool(430, 160));
  const round = attachmentPath(above.from, above.to, tool(430, 160), agent);
  assert.doesNotMatch(round, / C /);
  assert.match(round, / L /);
});

test("while a connection is dragged (not routed) the direct line is kept, and edgePath with `attachment` uses the same function", () => {
  const t = tool(430, 160);
  const { from, to } = portsOf(agent, t);
  assert.equal(attachmentPath(from, to, t, agent, { routed: false }), edgePath(from, to, t, agent, { routed: false, kind: EDGE_KINDS.attachment }));
  assert.equal(attachmentPath(from, to, t, agent, { routed: true, style: "elbow" }), edgePath(from, to, t, agent, { kind: EDGE_KINDS.attachment, style: "elbow" }));
});
