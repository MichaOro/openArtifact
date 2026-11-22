import assert from "node:assert/strict";
import { test } from "node:test";

const { FlowModel, nameOf } = await import("../../openartifact/static/js/execution/visit-model.js");

// A pipeline "Release" with one stage "Build" (id s1) holding two actions; the first action runs the
// definition "Compile" twice (a retry), the second one calls nothing. Visit 0 is the pipeline.
const pipeline = {
  id: "p", kind: "pipeline", name: "Release",
  nodes: [
    { id: "trig", kind: "trigger", name: "Trigger", stage_id: null },
    { id: "s1", kind: "stage", name: "Build", stage_id: null },
    { id: "a1", kind: "action", name: "Action", definition_name: "Compile", stage_id: "s1" },
    { id: "a2", kind: "action", name: "Action", definition_name: null, stage_id: "s1" },
    { id: "call", kind: "pipeline", name: "Call", stage_id: null },
    { id: "done", kind: "complete", name: "Complete", stage_id: null },
  ],
};
const compile = { id: "d", kind: "action", name: "Compile", nodes: [{ id: "n1", kind: "code", name: "build" }, { id: "n2", kind: "code", name: "lint" }, { id: "out", kind: "output", name: "Output" }] };
const inner = { id: "i", kind: "pipeline", name: "Inner", nodes: [{ id: "it", kind: "trigger", name: "Trigger" }] };

const visit = (fields) => ({ index: 0, parent: null, graph_id: "p", entered_via: null, outcome: "pass", nodes: [], edges: [], skipped_nodes: [], first_seq: null, last_seq: null, ...fields });
const via = (node_id) => ({ node_id });

function flow(overrides = {}) {
  return {
    execution: { id: "e1", status: "done" },
    graphs: { p: pipeline, d: compile, i: inner },
    visits: [
      visit({ index: 0, nodes: ["trig", "s1", "a1", "a1", "a2", "done"], edges: [{ id: "x1" }, { id: "x2" }, { id: "x3" }], skipped_nodes: [] }),
      visit({ index: 1, parent: 0, graph_id: "d", entered_via: via("a1"), outcome: "fail", nodes: ["n1", "out"], first_seq: 1, last_seq: 2 }),
      visit({ index: 2, parent: 0, graph_id: "d", entered_via: via("a1"), outcome: "pass", nodes: ["n1", "n2", "out"], first_seq: 3, last_seq: 5 }),
      visit({ index: 3, parent: 0, graph_id: "i", entered_via: via("call"), outcome: "pass", nodes: ["it"] }),
    ],
    steps: [
      { seq: 1, node_id: "n1", outcome: "fail" },
      { seq: 3, node_id: "n1", outcome: "pass" },
      { seq: 4, node_id: "n2", outcome: "pass" },
      { seq: 9, node_id: "n2", outcome: "pass" },
    ],
    ...overrides,
  };
}

test("nameOf prefers the linked definition's name", () => {
  assert.equal(nameOf({ name: "Action", definition_name: "Compile" }), "Compile");
  assert.equal(nameOf({ name: "Action", definition_name: null }), "Action");
  assert.equal(nameOf({ name: "Action" }), "Action");
});

test("the model exposes the execution, the root visit and the steps", () => {
  const model = new FlowModel(flow());
  assert.equal(model.execution.id, "e1");
  assert.equal(model.root.index, 0);
  assert.equal(model.steps.length, 4);
  assert.equal(new FlowModel(flow({ visits: [] })).root, null);
});

test("visit looks up by index, graph by the visit's graph", () => {
  const model = new FlowModel(flow());
  assert.equal(model.visit(2).outcome, "pass");
  assert.equal(model.visit(99), null);
  assert.equal(model.graph(model.visit(1)).name, "Compile");
});

test("children, and children entered via one node (a node that ran again has several)", () => {
  const model = new FlowModel(flow());
  const root = model.visit(0);
  assert.deepEqual(model.children(root).map((v) => v.index), [1, 2, 3]);
  assert.deepEqual(model.childrenVia(root, "a1").map((v) => v.index), [1, 2]);
  assert.deepEqual(model.childrenVia(root, "call").map((v) => v.index), [3]);
  assert.deepEqual(model.childrenVia(root, "zzz"), []);
  assert.deepEqual(model.children(model.visit(1)), []);
});

test("passes: every visit of the same node in the same parent; the root has only itself", () => {
  const model = new FlowModel(flow());
  assert.deepEqual(model.passes(model.visit(0)).map((v) => v.index), [0]);
  assert.deepEqual(model.passes(model.visit(2)).map((v) => v.index), [1, 2]);
  assert.deepEqual(model.passes(model.visit(3)).map((v) => v.index), [3]);
});

test("chain runs from the root down to the visit", () => {
  const model = new FlowModel(flow());
  assert.deepEqual(model.chain(model.visit(2)).map((v) => v.index), [0, 2]);
  assert.deepEqual(model.chain(model.visit(0)).map((v) => v.index), [0]);
  const nested = flow();
  nested.visits.push(visit({ index: 4, parent: 3, graph_id: "i", entered_via: via("it") }));
  assert.deepEqual(new FlowModel(nested).chain(nested.visits[4]).map((v) => v.index), [0, 3, 4]);
});

test("enteredFrom is the node of the parent graph, or null", () => {
  const model = new FlowModel(flow());
  assert.equal(model.enteredFrom(model.visit(1)).id, "a1");
  assert.equal(model.enteredFrom(model.visit(0)), null);
  const lost = flow();
  lost.visits[1].entered_via = via("gone");
  assert.equal(new FlowModel(lost).enteredFrom(lost.visits[1]), null, "the node was deleted since");
  const orphan = flow();
  orphan.visits[1].parent = 42;
  assert.equal(new FlowModel(orphan).enteredFrom(orphan.visits[1]), null, "the parent visit is unknown");
});

test("stageOf finds the stage of an action node only", () => {
  const model = new FlowModel(flow());
  assert.equal(model.stageOf(pipeline.nodes[2], pipeline).name, "Build");
  assert.equal(model.stageOf(pipeline.nodes[4], pipeline), null, "a called pipeline has no stage");
  assert.equal(model.stageOf(null, pipeline), null);
  assert.equal(model.stageOf({ stage_id: "gone" }, pipeline), null);
});

test("stepsOf: the steps inside an action visit, within its sequence window and its own nodes", () => {
  const model = new FlowModel(flow());
  assert.deepEqual(model.stepsOf(model.visit(1)).map((s) => s.seq), [1]);
  assert.deepEqual(model.stepsOf(model.visit(2)).map((s) => s.seq), [3, 4], "seq 9 is outside the window");
  assert.deepEqual(model.stepsOf(model.visit(0)), [], "a pipeline visit has none");
  assert.deepEqual(model.stepsOf(visit({ graph_id: "d", first_seq: null })), [], "nothing was recorded");
});

test("describe: states, entries and edge order of a pipeline visit", () => {
  const model = new FlowModel(flow());
  const { entries, states, edgeOrder } = model.describe(model.visit(0));
  assert.deepEqual(entries.map((e) => [e.position, e.id, e.state]), [
    [0, "trig", "pass"], [1, "s1", "pass"], [2, "a1", "pass"], [3, "a1", "pass"], [4, "a2", "pass"], [5, "done", "pass"],
  ]);  // both entries of the retried action show the outcome of its last pass
  // an action that was entered twice takes the outcome of its last visit
  assert.equal(states.get("a1").state, "pass");
  assert.equal(states.get("a1").passes, 2);
  assert.equal(states.get("call").state, "not-run");
  assert.deepEqual([...edgeOrder], [["x1", 1], ["x2", 2], ["x3", 3]]);
});

test("describe: an entry carries its step or its child visits and states carry the step", () => {
  const model = new FlowModel(flow());
  const { entries, states } = model.describe(model.visit(2));
  assert.deepEqual(entries.map((e) => [e.id, e.step?.seq ?? null]), [["n1", 3], ["n2", 4], ["out", null]]);
  assert.equal(states.get("n1").step.seq, 3);
  assert.equal(states.get("out").step, null);
  const root = model.describe(model.visit(0));
  assert.deepEqual(root.entries[2].children.map((v) => v.index), [1, 2]);
  assert.deepEqual(root.entries[3].children.map((v) => v.index), [1, 2], "both entries of a1 see all its passes");
});

test("describe: a visit that did not pass marks where it ended, and the stage holding it", () => {
  const stopped = flow();
  stopped.visits[0] = visit({ index: 0, nodes: ["trig", "s1", "a2"], outcome: "stopped" });
  stopped.visits = [stopped.visits[0]];
  const described = new FlowModel(stopped).describe(stopped.visits[0]);
  assert.deepEqual(described.entries.map((e) => e.state), ["pass", "stopped", "stopped"], "the stage s1 holds the last node a2");
  assert.equal(described.states.get("done").state, "not-run");

  const failed = flow();
  failed.visits[0] = visit({ index: 0, nodes: ["trig", "s1", "a2"], outcome: "fail" });
  failed.visits = [failed.visits[0]];
  assert.deepEqual(new FlowModel(failed).describe(failed.visits[0]).entries.map((e) => e.state), ["pass", "fail", "fail"]);

  const running = flow();
  running.visits[0] = visit({ index: 0, nodes: ["trig", "s1"], outcome: "running" });
  running.visits = [running.visits[0]];
  assert.deepEqual(new FlowModel(running).describe(running.visits[0]).entries.map((e) => e.state), ["pass", "running"], "the tail is a stage: it is its own holder");

  const unknown = flow();
  unknown.visits[0] = visit({ index: 0, nodes: ["trig", "ghost"], outcome: "stopped" });
  unknown.visits = [unknown.visits[0]];
  assert.deepEqual(new FlowModel(unknown).describe(unknown.visits[0]).entries.map((e) => [e.node?.id ?? null, e.state]), [["trig", "pass"], [null, "stopped"]], "a deleted node is still listed");
});

test("describe: an entry without a step takes the outcome of its last child visit", () => {
  const call = flow();
  call.visits[0] = visit({ index: 0, nodes: ["trig", "call"] });
  call.visits[3].outcome = "fail";
  const described = new FlowModel(call).describe(call.visits[0]);
  assert.equal(described.entries[1].state, "fail");
  assert.equal(described.states.get("call").passes, 1);
});

test("describe: skipped nodes are marked when nothing ran there", () => {
  const skipping = flow();
  skipping.visits[0] = visit({ index: 0, nodes: ["trig", "a2"], skipped_nodes: ["s1", "a1"] });
  const { states } = new FlowModel(skipping).describe(skipping.visits[0]);
  assert.equal(states.get("s1").state, "skipped");
  assert.equal(states.get("a1").state, "skipped");
  assert.equal(states.get("call").state, "not-run");
  assert.equal(states.get("a2").state, "pass");
});

test("describe: a step is used once, in order, when a node appears twice in the nodes list", () => {
  const twice = flow();
  twice.visits[2] = { ...twice.visits[2], nodes: ["n1", "n1", "out"], first_seq: 1, last_seq: 4 };
  twice.steps = [{ seq: 1, node_id: "n1", outcome: "fail" }, { seq: 2, node_id: "n1", outcome: "pass" }];
  const { entries } = new FlowModel(twice).describe(twice.visits[2]);
  assert.deepEqual(entries.map((e) => [e.step?.seq ?? null, e.state]), [[1, "fail"], [2, "pass"], [null, "pass"]]);
});

test("titleOf: the node and its stage for an action, the graph's name for the root", () => {
  const model = new FlowModel(flow());
  const action = model.titleOf(model.visit(1));
  assert.equal(action.name, "Compile");
  assert.equal(action.stage, "Build");
  assert.equal(action.graph.id, "d");
  const root = model.titleOf(model.visit(0));
  assert.deepEqual([root.name, root.stage], ["Release", null]);
  const called = model.titleOf(model.visit(3));
  assert.deepEqual([called.name, called.stage], ["Call", null]);
});
