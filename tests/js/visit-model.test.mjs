import assert from "node:assert/strict";
import { test } from "node:test";

const { FlowModel, nameOf, noteToolCall, toolState } = await import("../../openartifact/static/js/execution/visit-model.js");

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


// ── the tool nodes of an agent ───────────────────────────────────────

test("a tool node says green, red or working from what its calls came to, and nothing without a call", () => {
  assert.equal(toolState(null), null);
  assert.equal(toolState({ calls: 0, errors: 0, running: 0 }), null, "never asked: it keeps looking unused");
  assert.deepEqual(toolState({ calls: 9, errors: 0 }), { state: "pass", calls: 9, errors: 0 });
  assert.deepEqual(toolState({ calls: 9, errors: 1 }), { state: "fail", calls: 9, errors: 1 }, "one failed call is enough");
  assert.equal(toolState({ calls: 3, errors: 1, running: 1 }).state, "running", "a call in progress wins over what came before");
  assert.equal(toolState({ calls: 0, errors: 0, running: 1 }).state, "running");
});

test("events of calls are counted per tool node: started adds a running call, finished turns it into a call that went well or not", () => {
  const live = new Map();
  noteToolCall(live, { state: "started", tool_node_id: "t1" });
  assert.deepEqual(live.get("t1"), { running: 1, calls: 0, errors: 0 });
  noteToolCall(live, { state: "finished", tool_node_id: "t1", ok: true });
  noteToolCall(live, { state: "started", tool_node_id: "t1" });
  noteToolCall(live, { state: "finished", tool_node_id: "t1", ok: false });
  noteToolCall(live, { state: "started", tool_node_id: "t2" });
  assert.deepEqual(live.get("t1"), { running: 0, calls: 2, errors: 1 });
  assert.deepEqual(live.get("t2"), { running: 1, calls: 0, errors: 0 });
  noteToolCall(live, { state: "finished", tool_node_id: "t9", ok: true }); // a finish without a start never goes below zero
  assert.equal(live.get("t9").running, 0);
});

// An action "Ask" of the pipeline "Run": the agent node and three tool nodes below it (one used, one failed, one never asked).
const askGraph = {
  id: "d", kind: "action", name: "Ask",
  nodes: [
    { id: "trig", kind: "trigger", name: "Trigger" },
    { id: "ag", kind: "agent", name: "Agent" },
    { id: "gh", kind: "github_tool", name: "GitHub MCP" },
    { id: "http", kind: "http_tool", name: "Web" },
    { id: "idle", kind: "code_tool", name: "Unused" },
    { id: "out", kind: "output", name: "Output" },
  ],
};
const agentFlow = (data, outcome = "pass") => ({
  execution: { id: "e1", status: "done" },
  graphs: { p: { id: "p", kind: "pipeline", name: "Run", nodes: [{ id: "a1", kind: "action", name: "Action", definition_name: "Ask" }] }, d: askGraph },
  visits: [
    visit({ index: 0, nodes: ["a1"], edges: [] }),
    visit({ index: 1, parent: 0, graph_id: "d", entered_via: via("a1"), outcome, nodes: ["trig", "ag", "out"], first_seq: 1, last_seq: 3 }),
  ],
  steps: [{ seq: 2, node_id: "ag", kind: "agent", outcome, data }],
});

test("the tool nodes an agent used get their state from its step; the one it never asked stays not-run", () => {
  const model = new FlowModel(agentFlow({ tools: [{ node: "gh", name: "GitHub MCP", calls: 9, errors: 0 }, { node: "http", name: "Web", calls: 2, errors: 1 }] }));
  const { states } = model.describe(model.visit(1));
  assert.deepEqual(states.get("gh"), { state: "pass", calls: 9, errors: 0, passes: 0, tool: true });
  assert.deepEqual(states.get("http"), { state: "fail", calls: 2, errors: 1, passes: 0, tool: true });
  assert.equal(states.get("idle").state, "not-run");
  assert.equal(states.get("idle").tool, undefined);
});

test("a step of before (no summary) or one that names a node of no graph changes nothing", () => {
  for (const data of [undefined, {}, { tools: [{ node: "elsewhere", calls: 1, errors: 0 }] }]) {
    const model = new FlowModel(agentFlow(data));
    const { states } = model.describe(model.visit(1));
    assert.equal(states.get("gh").state, "not-run");
    assert.equal(states.has("elsewhere"), false);
  }
});

test("while the agent still runs the live calls decide, and a call in progress shows the node working", () => {
  const model = new FlowModel({ ...agentFlow(undefined, "running"), steps: [] });
  const live = new Map();
  noteToolCall(live, { state: "started", tool_node_id: "gh" });
  assert.equal(model.describe(model.visit(1), live).states.get("gh").state, "running");
  noteToolCall(live, { state: "finished", tool_node_id: "gh", ok: false });
  const done = model.describe(model.visit(1), live).states.get("gh");
  assert.deepEqual([done.state, done.calls, done.errors], ["fail", 1, 1]);
  assert.equal(model.describe(model.visit(1), live).states.get("idle").state, "not-run");
});

test("an agent asking a tool again (a loop) shows it working while the finished calls stay counted", () => {
  const model = new FlowModel(agentFlow({ tools: [{ node: "gh", name: "GitHub MCP", calls: 4, errors: 0 }] }));
  const live = new Map([["gh", { running: 1, calls: 0, errors: 0 }]]);
  const gh = model.describe(model.visit(1), live).states.get("gh");
  assert.deepEqual([gh.state, gh.calls], ["running", 4]);
  const quiet = model.describe(model.visit(1), new Map([["gh", { running: 0, calls: 7, errors: 3 }]])).states.get("gh");
  assert.deepEqual([quiet.state, quiet.calls, quiet.errors], ["pass", 4, 0], "what a finished step says wins over what was heard live");
});

// ── the rounds of a running agent (agent.turn and agent.tool_call) ──────

const { noteAgentTurn, noteAgentCall, liveSummary } = await import("../../openartifact/static/js/execution/visit-model.js");

test("the rounds grow from the events: a round, its calls, the tokens", () => {
  const live = new Map();
  const base = { agent_node_id: "a1" };
  noteAgentTurn(live, { ...base, turn: 1, state: "started" });
  assert.equal(live.get("a1").rounds[0].state, "running");
  noteAgentTurn(live, { ...base, turn: 1, state: "finished", text: "I look at the repo.", tokens: 120, total_tokens: 120, tool_calls: 2 });
  noteAgentCall(live, { ...base, turn: 1, state: "started", tool: "get_file", tool_node_name: "GitHub" });
  noteAgentCall(live, { ...base, turn: 1, state: "started", tool: "list_commits", tool_node_name: "GitHub" });
  assert.deepEqual(liveSummary(live.get("a1")), { rounds: 1, calls: 2, failed: 0, running: 2, tokens: 120 });
  noteAgentCall(live, { ...base, turn: 1, state: "finished", tool: "get_file", ok: true, duration_ms: 1500 });
  noteAgentCall(live, { ...base, turn: 1, state: "finished", tool: "list_commits", ok: false, duration_ms: 800 });
  noteAgentTurn(live, { ...base, turn: 2, state: "started" });
  const [one, two] = live.get("a1").rounds;
  assert.deepEqual(one.calls.map((c) => [c.tool, c.state, c.ms]), [["get_file", "ok", 1500], ["list_commits", "failed", 800]]);
  assert.equal(one.text, "I look at the repo.");
  assert.deepEqual([two.turn, two.state], [2, "running"]);
  assert.deepEqual(liveSummary(live.get("a1")), { rounds: 2, calls: 2, failed: 1, running: 0, tokens: 120 });
});

test("a failed request and the final answer are shown as such", () => {
  const live = new Map();
  noteAgentTurn(live, { agent_node_id: "a1", turn: 1, state: "started" });
  noteAgentTurn(live, { agent_node_id: "a1", turn: 1, state: "finished", error: "Timeout after 60 s" });
  noteAgentTurn(live, { agent_node_id: "a1", turn: 2, state: "started", wrap_up: "a failed request" });
  const [one, two] = live.get("a1").rounds;
  assert.deepEqual([one.state, one.error], ["failed", "Timeout after 60 s"]);
  assert.equal(two.wrapUp, "a failed request");
});

test("calls of an event without a round, and an agent nobody heard of, add nothing", () => {
  const live = new Map();
  noteAgentCall(live, { state: "started", tool: "x", tool_node_name: "T" });
  assert.equal(live.size, 0);
  assert.equal(liveSummary(undefined), null);
  assert.equal(liveSummary({ rounds: [], tokens: null }), null);
});

test("rounds come in order even when their events arrive late", () => {
  const live = new Map();
  noteAgentTurn(live, { agent_node_id: "a1", turn: 2, state: "started" });
  noteAgentTurn(live, { agent_node_id: "a1", turn: 1, state: "started" });
  assert.deepEqual(live.get("a1").rounds.map((r) => r.turn), [1, 2]);
});
