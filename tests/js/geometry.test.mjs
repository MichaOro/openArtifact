import assert from "node:assert/strict";
import { before, test } from "node:test";
import { loadTypes } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { loadNodeTypes } = await import(`${JS}node-types.js`);
const g = await import(`${JS}geometry.js`);

before(() => loadTypes(loadNodeTypes));

const stage = { id: "s", kind: "stage", name: "Build", x: 100, y: 40, width: 400, height: 300 };
const action = (id, x, fields = {}) => ({ id, kind: "action", name: "Action", stage_id: "s", x, y: 48, ...fields });
const nodesOf = (...list) => new Map(list.map((n) => [n.id, n]));

test("constants", () => {
  assert.deepEqual([g.PAD, g.ACTION_GAP, g.TOP_LEVEL_GAP, g.STAGE_MIN], [24, 64, 96, { width: 320, height: 220 }]);
  assert.deepEqual(g.EDGE_STYLES, { curved: "Curved", straight: "Straight", elbow: "Elbow" });
});

test("displayName and sizeOf follow the kind", () => {
  assert.equal(g.displayName(action("a", 0, { definition_name: "Deploy" })), "Deploy");
  assert.deepEqual(g.sizeOf(stage), { width: 400, height: 300 });
});

test("a node of a stage is placed relative to the stage body, below its header", () => {
  const a = action("a", 24);
  const nodes = nodesOf(stage, a);
  assert.deepEqual(g.originOf(stage, nodes), { x: 100, y: 40 });
  assert.deepEqual(g.originOf(a, nodes), { x: 124, y: 40 + 44 + 48 });
  assert.deepEqual(g.boxOf(a, nodes), { x: 124, y: 132, width: 190, height: 68 });
});

test("portPoint adds the local position to the origin; a stage port honours its slot", () => {
  const a = action("a", 24, { definition_fail_enabled: true });
  const nodes = nodesOf(stage, a);
  assert.deepEqual(g.portPoint(a, "in", nodes), { x: 124, y: 132 + 34 });
  const [top, middle, bottom] = [0, 1, 2].map((slot) => g.portPoint(stage, "end", nodes, slot).y - 40);
  assert.ok(Math.abs(middle - (top + bottom) / 2) < 1e-9, "the middle point is halfway between the top and the bottom one");
  assert.deepEqual(g.portPoint(stage, "start", nodes, 0).x, 100);
  assert.deepEqual(g.portPoint(stage, "end", nodes, 0).x, 500);
});

test("the attachment points of a stage follow the stage's height, not its actions", () => {
  const level = (x, y, message) => assert.ok(Math.abs(x - y) < 1e-9, `${message}: ${x} against ${y}`);
  const heights = (nodes, side = "start") => [0, 1, 2].map((slot) => g.portPoint(stage, side, nodes, slot).y);
  const a = action("a", 24, { definition_fail_enabled: true });
  const low = action("b", 300, { y: 160, definition_fail_enabled: true });
  assert.deepEqual(heights(nodesOf(stage)), heights(nodesOf(stage, a)), "an action changes nothing");
  assert.deepEqual(heights(nodesOf(stage, a, low)), heights(nodesOf(stage)), "nor do two, one far below the other");
  assert.deepEqual(heights(nodesOf(stage, a), "end"), heights(nodesOf(stage), "end"), "the same on the right");
  // the top point is level with the input of an action placed where a new action goes
  const first = action("n", 24, { y: g.nextActionPosition(stage, nodesOf(stage)).y, definition_fail_enabled: true });
  level(g.portPoint(stage, "start", nodesOf(stage, first), 0).y, g.portPoint(first, "in", nodesOf(stage, first)).y, "top = first row (input)");
  level(g.portPoint(stage, "end", nodesOf(stage, first), 0).y, g.portPoint(first, "pass", nodesOf(stage, first)).y, "top = first row (On Pass)");
  // the bottom point is level with the input of an action dragged as low as it goes without the stage growing
  const lowest = action("z", 24, { y: stage.height - 44 - g.PAD - 68, definition_fail_enabled: true });
  const lowestNodes = nodesOf(stage, lowest);
  assert.equal(g.fitStage(stage, g.actionsOf(stage, lowestNodes)).height, stage.height, "the stage does not grow for it");
  level(g.portPoint(stage, "start", lowestNodes, 2).y, g.portPoint(lowest, "in", lowestNodes).y, "bottom = lowest action (input)");
  level(g.portPoint(stage, "end", lowestNodes, 2).y, g.portPoint(lowest, "pass", lowestNodes).y, "bottom = lowest action (On Pass)");
  level(heights(lowestNodes)[1], (heights(lowestNodes)[0] + heights(lowestNodes)[2]) / 2, "the middle one is halfway");
});

test("the top point is level with an action at the very top: where the drag stops, the highest row", () => {
  const level = (x, y, message) => assert.ok(Math.abs(x - y) < 1e-9, `${message}: ${x} against ${y}`);
  // an action dragged far above the stage is stopped by clampInStage: its input is then level with the top point
  const dragged = action("d", 24, { ...g.clampInStage(24, -500), definition_fail_enabled: true });
  const nodes = nodesOf(stage, dragged);
  assert.equal(dragged.y, g.nextActionPosition(stage, nodesOf(stage)).y, "the highest row is where a new action goes");
  level(g.portPoint(stage, "start", nodes, 0).y, g.portPoint(dragged, "in", nodes).y, "top = the highest an action can sit (input)");
  level(g.portPoint(stage, "end", nodes, 0).y, g.portPoint(dragged, "pass", nodes).y, "top = the highest an action can sit (On Pass)");
  const [top, middle, bottom] = [0, 1, 2].map((slot) => g.portPoint(stage, "start", nodes, slot).y);
  level(middle, (top + bottom) / 2, "the middle one is halfway between the top and the bottom one");
  assert.ok(top < middle && middle < bottom, "in order");
  const smallest = { ...stage, height: g.STAGE_MIN.height };
  const [a, b, c] = [0, 1, 2].map((slot) => g.portPoint(smallest, "start", nodesOf(smallest), slot).y - smallest.y);
  assert.ok(a < b && b < c && c <= smallest.height - 8, `in order inside the edge at the smallest size: ${a}, ${b}, ${c}`);
});

test("the attachment points follow a resized stage at once", () => {
  const taller = { ...stage, height: 460 };
  const [top, , bottom] = [0, 1, 2].map((slot) => g.portPoint(stage, "start", nodesOf(stage), slot).y - stage.y);
  const [top2, , bottom2] = [0, 1, 2].map((slot) => g.portPoint(taller, "start", nodesOf(taller), slot).y - taller.y);
  assert.equal(top2, top, "the first row does not move");
  assert.equal(bottom2 - bottom, 160, "the bottom point moves with the bottom edge");
});

test("an attachment point never leaves its stage's edge", () => {
  const small = { ...stage, height: 100 };
  const [first, , last] = [0, 1, 2].map((slot) => g.portPoint(small, "start", nodesOf(small), slot).y - small.y);
  assert.ok(last <= small.height - 8, `the lowest point stays inside: ${last}`);
  assert.ok(first >= 22 && first <= last, `the first point stays below the header's middle and above the last: ${first}`);
});

test("an action's ports offer the heights of its stage's points to settle on", () => {
  const a = action("a", 24, { definition_fail_enabled: true, y: 100 });
  const nodes = nodesOf(stage, a);
  const pairs = g.slotPairs(a, nodes);
  assert.equal(pairs.length, 6, "three on the left for its input, three on the right for its On Pass");
  const own = g.portPoint(a, "in", nodes);
  const left = pairs.filter((pair) => pair.own === own.y);
  assert.deepEqual(left.map((pair) => pair.other), [0, 1, 2].map((slot) => g.portPoint(stage, "start", nodes, slot).y));
  assert.deepEqual(left.map((pair) => [pair.from, pair.to]), [0, 1, 2].map(() => [own.x, 100]), "the guide runs from the port to the stage's edge");
  const right = pairs.filter((pair) => pair.own === g.portPoint(a, "pass", nodes).y);
  assert.deepEqual(right.map((pair) => pair.other), [0, 1, 2].map((slot) => g.portPoint(stage, "end", nodes, slot).y));
  assert.deepEqual(g.slotPairs(stage, nodes), [], "a stage has no stage of its own");
  assert.deepEqual(g.slotPairs({ ...a, kind: "code" }, nodes).length > 0, true, "any node of a stage settles on its points");
});

test("minStageSize is what the actions need, however large the stage is", () => {
  assert.deepEqual(g.minStageSize([]), { width: 320, height: 220 });
  const far = { x: 400, y: 200, kind: "action", definition_fail_enabled: false };
  assert.deepEqual(g.minStageSize([far]), { width: 400 + 190 + 24, height: 44 + 200 + 68 + 24 });
  // fitStage keeps a larger stage; minStageSize is the floor a resize may go down to
  assert.deepEqual(g.fitStage({ width: 900, height: 700 }, [far]), { width: 900, height: 700 });
});

test("snapY: equally near candidates keep the order given (a connected point is listed first)", () => {
  assert.deepEqual(g.snapY([{ own: 100, other: 104, connected: true }, { own: 100, other: 96 }], 8), { delta: 4, y: 104 });
});

test("snapY pulls a node level with a connected port within the threshold and ignores the rest", () => {
  assert.deepEqual(g.snapY([{ own: 100, other: 105 }], 8), { delta: 5, y: 105 });
  assert.equal(g.snapY([{ own: 100, other: 109 }], 8), null, "outside the threshold");
  assert.deepEqual(g.snapY([{ own: 100, other: 107 }, { own: 100, other: 96 }], 8), { delta: -4, y: 96 }, "the nearest wins");
  assert.deepEqual(g.snapY([{ own: 100, other: 100 }], 8), { delta: 0, y: 100 }, "already level");
  assert.equal(g.snapY([], 8), null);
});

test("canConnect needs both ports to exist and be shown, then asks the kind", () => {
  const a = action("a", 24, { definition_fail_enabled: false });
  const b = action("b", 300);
  assert.equal(g.canConnect(a, "pass", b, "in"), true);
  assert.equal(g.canConnect(a, "nope", b, "in"), false, "no such output");
  assert.equal(g.canConnect(a, "out", b, "nope"), false, "no such input");
  assert.equal(g.canConnect(a, "error", b, "in"), false, "On Error is hidden without On Fail");
  assert.equal(g.canConnect(b, "pass", { ...a, stage_id: "x" }, "in"), false, "an action of another stage");
  assert.equal(g.canConnect({ ...a, definition_fail_enabled: true }, "error", b, "in"), true);
  const output = { id: "o", kind: "output", fail_enabled: false };
  const code = { id: "c", kind: "code" };
  assert.equal(g.canConnect(code, "fail", output, "fail"), false, "the Fail port is hidden");
  assert.equal(g.canConnect(code, "pass", output, "pass"), true);
  assert.equal(g.canConnect(code, "pass", { ...output, fail_enabled: true }, "fail"), true);
});

const box = (x, y, width = 100, height = 50) => ({ x, y, width, height });

test("edgePath: a forward connection is a cubic curve with a bounded reach", () => {
  const near = g.edgePath({ x: 0, y: 0 }, { x: 60, y: 20 }, box(-100, -25), box(60, -5));
  assert.equal(near, "M 0 0 C 48 0, 12 20, 60 20", "reach never below 48");
  const mid = g.edgePath({ x: 0, y: 0 }, { x: 200, y: 20 }, box(-100, -25), box(200, -5));
  assert.equal(mid, "M 0 0 C 100 0, 100 20, 200 20");
  const far = g.edgePath({ x: 0, y: 0 }, { x: 1000, y: 0 }, box(-100, -25), box(1000, -25));
  assert.equal(far, "M 0 0 C 220 0, 780 0, 1000 0", "reach never above 220");
});

test("edgePath: a short forward connection between level ports is drawn straight, not routed around the nodes", () => {
  const level = g.edgePath({ x: 0, y: 50 }, { x: 24, y: 50 }, box(-100, 20), box(24, 20));
  assert.doesNotMatch(level, /Q/, "no detour: nothing has to bend");
  assert.match(level, /^M 0 50 C /);
  const off = g.edgePath({ x: 0, y: 50 }, { x: 24, y: 80 }, box(-100, 20), box(24, 50));
  assert.match(off, /Q/, "ports at different heights with little room still go around");
  assert.match(g.edgePath({ x: 40, y: 50 }, { x: 10, y: 50 }, box(-60, 20), box(10, 20)), /Q/, "a connection that goes back is still routed");
});

test("edgePath: straight and elbow forward connections", () => {
  const from = { x: 0, y: 0 };
  const to = { x: 200, y: 100 };
  assert.equal(g.edgePath(from, to, box(-100, -25), box(200, 75), { style: "straight" }), "M 0 0 L 200 100");
  assert.equal(
    g.edgePath(from, to, box(-100, -25), box(200, 75), { style: "elbow" }),
    "M 0 0 L 88 0 Q 100 0 100 12 L 100 88 Q 100 100 112 100 L 200 100",
  );
});

test("edgePath: a backward or too tight connection runs below both nodes", () => {
  const from = { x: 300, y: 20 };
  const to = { x: 100, y: 120 };
  const below = Math.max(0 + 50, 100 + 50) + 28;
  const rounded = g.edgePath(from, to, box(200, 0), box(100, 100));
  assert.ok(rounded.startsWith("M 300 20 L 316 20 Q 328 20 328 32"), rounded);
  assert.ok(rounded.includes(`${below}`), "passes below the lower node");
  assert.ok(rounded.endsWith("L 100 120"));
  const sharp = g.edgePath(from, to, box(200, 0), box(100, 100), { style: "straight" });
  assert.equal(sharp, `M 300 20 L 328 20 Q 328 20 328 20 L 328 ${below} Q 328 ${below} 328 ${below} L 72 ${below} Q 72 ${below} 72 ${below} L 72 120 Q 72 120 72 120 L 100 120`);
  // 47 pixels of room is still too tight, 48 is enough (the ports are at different heights: level ports run straight, see below)
  assert.ok(g.edgePath({ x: 0, y: 0 }, { x: 47, y: 10 }, box(-100, -25), box(47, -25)).includes(" Q "));
  assert.ok(g.edgePath({ x: 0, y: 0 }, { x: 48, y: 10 }, box(-100, -25), box(48, -25)).includes(" C "));
  // routed: false keeps the plain curve even going backwards
  assert.match(g.edgePath(from, to, box(200, 0), box(100, 100), { routed: false }), /^M 300 20 C /);
});

test("edgePath: two coincident points do not divide by zero", () => {
  const path = g.edgePath({ x: 5, y: 5 }, { x: 5, y: 5 }, box(0, 0), box(0, 0));
  assert.ok(!path.includes("NaN"), path);
});

test("actionsOf lists the nodes of a stage only", () => {
  const nodes = nodesOf(stage, action("a", 24), action("b", 300), action("c", 0, { stage_id: "t" }), { id: "tr", kind: "trigger", x: 0, y: 0 });
  assert.deepEqual(g.actionsOf(stage, nodes).map((n) => n.id), ["a", "b"]);
});

test("a new stage or timer goes to the right of the main line; the other kinds are not on it", () => {
  const trigger = { id: "t", kind: "trigger", x: 40, y: 40 };
  const only = nodesOf(trigger);
  assert.deepEqual(g.nextTopLevelPosition(only, "stage"), { x: 40 + 160 + 96, y: 40 });
  assert.deepEqual(g.nextTopLevelPosition(only, "timer"), { x: 296, y: 172 });
  const more = nodesOf(trigger, stage, { id: "x", kind: "action", x: 5000, y: 0, stage_id: "s" });
  assert.deepEqual(g.nextTopLevelPosition(more, "stage"), { x: 500 + 96, y: 40 }, "an action in a stage is not on the line");
  assert.deepEqual(g.nextTopLevelPosition(new Map(), "stage"), { x: 156, y: 40 }, "an empty graph starts at 60 + gap");
});

test("a new action goes right of the last one of its stage, or at the padding", () => {
  assert.deepEqual(g.nextActionPosition(stage, nodesOf(stage)), { x: 24, y: 12 });
  const nodes = nodesOf(stage, action("a", 24), action("b", 300));
  assert.deepEqual(g.nextActionPosition(stage, nodes), { x: 300 + 190 + 64, y: 12 });
});

test("fitStage grows to hold the actions and never shrinks", () => {
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, []), { width: 320, height: 220 }, "the minimum");
  assert.deepEqual(g.fitStage({ width: 900, height: 700 }, []), { width: 900, height: 700 }, "the stage's own size wins when larger");
  const far = action("a", 400, { y: 200 });
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, [far]), { width: 400 + 190 + 24, height: 44 + 200 + 68 + 24 });
  const small = action("b", 0, { y: 0 });
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, [small]), { width: 320, height: 220 });
});

test("a connection pressed at an input is fed by an output that fits, and one pressed at an output feeds an input that fits", () => {
  const a = action("a", 24);
  const b = action("b", 300);
  const end = (node, port, direction) => ({ node, port, direction });
  // from the input of b, a's On Pass is a source that fits (the same rule as pressing a's On Pass and dropping on b's input)
  assert.equal(g.canConnectFrom(end(b, "in", "input"), end(a, "pass", "output")), true);
  assert.equal(g.canConnect(a, "pass", b, "in"), true);
  // the other way round and the end that does not exist for this role
  assert.equal(g.canConnectFrom(end(a, "pass", "output"), end(b, "in", "input")), true);
  assert.equal(g.canConnectFrom(end(b, "in", "input"), end(a, "in", "input")), false); // an input is no source
  assert.equal(g.canConnectFrom(end(a, "pass", "output"), end(b, "pass", "output")), false); // an output feeds no output
  // a stage's two-way point can be the source for an action's input pressed at the input
  assert.equal(g.canConnectFrom(end(a, "in", "input"), end(stage, "start", "both")), g.canConnect(stage, "start", a, "in"));
});
