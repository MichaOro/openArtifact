/* The plan of a line released on the empty canvas (static/js/editor/connect-plan.js): which kinds the menu offers, which
 * port of the new node is connected, where the node lands, what the new connection replaces. Pure functions. */
import assert from "node:assert/strict";
import { before, test } from "node:test";
import { loadTypes } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { loadNodeTypes, addableIn, typeOf } = await import(`${JS}node-types.js`);
const geometry = await import(`${JS}geometry.js`);
const plan = await import(`${JS}connect-plan.js`);

before(() => loadTypes(loadNodeTypes));

const node = (id, kind, fields = {}) => ({ id, kind, name: id, x: 0, y: 0, config: {}, ...fields });
const nodesOf = (...list) => new Map(list.map((n) => [n.id, n]));
const kindsOf = (types) => types.map((t) => t.kind).sort();
const TOOLS = ["code_tool", "github_tool", "handover_tool", "http_tool", "mcp_tool", "postgres_tool", "sqlite_tool"];

test("from an agent's Tools port only tools are offered", () => {
  const agent = node("ag", "agent", { x: 100, y: 100 });
  const origin = { node: agent, port: "tools", direction: "input", slot: 0 };
  assert.deepEqual(kindsOf(plan.candidates(origin, addableIn("action"))), TOOLS);
});

test("from an output the nodes with a suitable input are offered, never a tool", () => {
  const code = node("c", "code");
  const origin = { node: code, port: "pass", direction: "output", slot: 0 };
  const offered = kindsOf(plan.candidates(origin, addableIn("action")));
  for (const kind of ["code", "http", "if", "agent", "set", "timer"]) assert.ok(offered.includes(kind), `${kind} can follow a node`);
  for (const kind of TOOLS) assert.ok(!offered.includes(kind), `${kind} cannot follow a node`);
});

test("from an input the nodes with a suitable output are offered", () => {
  const code = node("c", "code");
  const origin = { node: code, port: "in", direction: "input", slot: 0 };
  const offered = kindsOf(plan.candidates(origin, addableIn("action")));
  assert.ok(offered.includes("code") && offered.includes("timer") && offered.includes("if"));
  assert.ok(!offered.includes("mcp_tool"), "a tool feeds only an agent's Tools port");
});

test("nothing fits where no kind can connect: an empty list, not an error", () => {
  const timer = node("t", "timer");
  const origin = { node: timer, port: "in", direction: "input", slot: 0 };
  assert.deepEqual(plan.candidates(origin, []), []);
});

test("the new node takes its first suitable input, and its main output, never the error output", () => {
  const code = node("c", "code");
  const fromOutput = { node: code, port: "pass", direction: "output", slot: 0 };
  assert.equal(plan.choosePort(fromOutput, "code").name, "in");
  const fromInput = { node: code, port: "in", direction: "input", slot: 0 };
  assert.equal(plan.choosePort(fromInput, "code").name, "pass", "On Pass, though On Fail exists");
  assert.equal(plan.choosePort(fromInput, "if").name, "yes");
  assert.equal(plan.choosePort(fromInput, "timer").name, "out");
});

test("a tool dragged from the agent goes below it, as a tool added from the menu does", () => {
  const agent = node("ag", "agent", { x: 100, y: 100 });
  const nodes = nodesOf(agent);
  const origin = { node: agent, port: "tools", direction: "input", slot: 0 };
  const at = plan.placement({ origin, kind: "code_tool", release: { x: 900, y: 900 }, nodes, edges: new Map(), stage: null });
  const spot = geometry.nextToolPosition(nodes, new Map(), "ag");
  assert.deepEqual([at.x, at.y], [spot.x, spot.y]);
});

test("the new node lands with its connected port at the release point", () => {
  const code = node("c", "code", { x: 0, y: 0 });
  const nodes = nodesOf(code);
  const origin = { node: code, port: "pass", direction: "output", slot: 0 };
  const sample = plan.sampleOf("code");
  const local = typeOf("code").portLocal(sample, "in", 0, nodes);
  const release = { x: 500, y: 400 };
  const at = plan.placement({ origin, kind: "code", release, nodes, edges: new Map(), stage: null });
  assert.deepEqual([at.x + local.x, at.y + local.y], [500, 400]);
  assert.equal(at.stage_id, undefined);
});

test("dragged from an input the node lands to the left, its output at the release point", () => {
  const code = node("c", "code", { x: 600, y: 0 });
  const nodes = nodesOf(code);
  const origin = { node: code, port: "in", direction: "input", slot: 0 };
  const local = typeOf("code").portLocal(plan.sampleOf("code"), "pass", 0, nodes);
  const at = plan.placement({ origin, kind: "code", release: { x: 560, y: 300 }, nodes, edges: new Map(), stage: null });
  assert.deepEqual([at.x + local.x, at.y + local.y], [560, 300]);
});

test("close to the level of the dragged port the line is made straight", () => {
  const code = node("c", "code", { x: 0, y: 0 });
  const nodes = nodesOf(code);
  const origin = { node: code, port: "pass", direction: "output", slot: 0 };
  const level = geometry.portPoint(code, "pass", nodes, 0).y;
  const local = typeOf("code").portLocal(plan.sampleOf("code"), "in", 0, nodes);
  const near = plan.placement({ origin, kind: "code", release: { x: 500, y: level + plan.STRAIGHT_SNAP - 1 }, nodes, edges: new Map(), stage: null });
  assert.equal(near.y + local.y, level, "within the snap distance the new port is level with the dragged one");
  const far = plan.placement({ origin, kind: "code", release: { x: 500, y: level + plan.STRAIGHT_SNAP + 40 }, nodes, edges: new Map(), stage: null });
  assert.equal(far.y + local.y, level + plan.STRAIGHT_SNAP + 40, "farther away the node stays where it was released");
});

test("an action made inside a stage is placed relative to the stage and kept inside its inner border", () => {
  const stage = { id: "s", kind: "stage", name: "Stage", x: 100, y: 40, width: 600, height: 400 };
  const first = node("a", "action", { stage_id: "s", x: 56, y: 12 });
  const nodes = nodesOf(stage, first);
  const origin = { node: first, port: "pass", direction: "output", slot: 0 };
  const at = plan.placement({ origin, kind: "action", release: { x: 130, y: 60 }, nodes, edges: new Map(), stage });
  assert.equal(at.stage_id, "s");
  assert.ok(at.x >= geometry.STAGE_MARGIN, "not left of the inner border");
  assert.ok(at.y >= 12, "not above the highest row");
});

test("inside a stage only an action is offered, outside it the kinds of the main line", () => {
  const stage = { id: "s", kind: "stage", name: "Stage", x: 0, y: 0, width: 600, height: 400 };
  const first = node("a", "action", { stage_id: "s" });
  const origin = { node: first, port: "pass", direction: "output", slot: 0 };
  assert.deepEqual(plan.kindsFor("pipeline", stage, addableIn("pipeline")).map((t) => t.kind), ["action"]);
  assert.deepEqual(plan.kindsFor("pipeline", null, addableIn("pipeline")).map((t) => t.kind).sort(), ["pipeline", "stage"]);
  assert.deepEqual(kindsOf(plan.kindsFor("action", null, addableIn("action"))), kindsOf(addableIn("action")));
  const offered = plan.candidates(origin, plan.kindsFor("pipeline", stage, addableIn("pipeline")), stage);
  assert.deepEqual(offered.map((t) => t.kind), ["action"], "an action follows an action of its own stage");
  assert.equal(plan.choosePort(origin, "action", stage).name, "in");
});

test("the connection is stored from the output to the input, whichever end was dragged", () => {
  const code = node("c", "code");
  const fresh = node("n", "code");
  const fromOutput = { node: code, port: "pass", direction: "output", slot: 0 };
  assert.deepEqual(plan.connectionFor(fromOutput, fresh, "in"), { source_id: "c", source_port: "pass", target_id: "n", target_port: "in", source_slot: 0, target_slot: 0 });
  const fromInput = { node: code, port: "in", direction: "input", slot: 0 };
  assert.deepEqual(plan.connectionFor(fromInput, fresh, "pass"), { source_id: "n", source_port: "pass", target_id: "c", target_port: "in", source_slot: 0, target_slot: 0 });
  const stage = node("s", "stage");
  const slotted = { node: stage, port: "end", direction: "both", slot: 2 };
  assert.equal(plan.connectionFor(slotted, fresh, "in").source_slot, 2, "a stage's slot travels with its end");
});

test("a connection that leaves the dragged output is replaced, and says which node it let go", () => {
  const code = node("c", "code");
  const old = node("o", "http", { name: "Goal Gate" });
  const nodes = nodesOf(code, old);
  const edges = new Map([["e1", { id: "e1", source_id: "c", source_port: "pass", target_id: "o", target_port: "in" }]]);
  const origin = { node: code, port: "pass", direction: "output", slot: 0 };
  assert.deepEqual(plan.replacedEdges(origin, edges, nodes), [{ id: "e1", name: "Goal Gate" }]);
  const other = { node: code, port: "fail", direction: "output", slot: 0 };
  assert.deepEqual(plan.replacedEdges(other, edges, nodes), []);
  const input = { node: old, port: "in", direction: "input", slot: 0 };
  assert.deepEqual(plan.replacedEdges(input, edges, nodes), [], "an input may be fed by several nodes: they stay");
});
