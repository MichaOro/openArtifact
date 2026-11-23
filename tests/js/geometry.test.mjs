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
  assert.deepEqual(g.portPoint(stage, "end", nodes, 1), { x: 500, y: 40 + 150 });
  assert.deepEqual(g.portPoint(stage, "start", nodes, 0), { x: 100, y: 40 + 22 });
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
  // 47 pixels of room is still too tight, 48 is enough
  assert.ok(g.edgePath({ x: 0, y: 0 }, { x: 47, y: 0 }, box(-100, -25), box(47, -25)).includes(" Q "));
  assert.ok(g.edgePath({ x: 0, y: 0 }, { x: 48, y: 0 }, box(-100, -25), box(48, -25)).includes(" C "));
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
  assert.deepEqual(g.nextActionPosition(stage, nodesOf(stage)), { x: 24, y: 48 });
  const nodes = nodesOf(stage, action("a", 24), action("b", 300));
  assert.deepEqual(g.nextActionPosition(stage, nodes), { x: 300 + 190 + 64, y: 48 });
});

test("fitStage grows to hold the actions and never shrinks", () => {
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, []), { width: 320, height: 220 }, "the minimum");
  assert.deepEqual(g.fitStage({ width: 900, height: 700 }, []), { width: 900, height: 700 }, "the stage's own size wins when larger");
  const far = action("a", 400, { y: 200 });
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, [far]), { width: 400 + 190 + 24, height: 44 + 200 + 68 + 24 });
  const small = action("b", 0, { y: 0 });
  assert.deepEqual(g.fitStage({ width: 100, height: 100 }, [small]), { width: 320, height: 220 });
});
