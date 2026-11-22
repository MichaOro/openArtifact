import assert from "node:assert/strict";
import { afterEach, before, test } from "node:test";
import { loadTypes } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { loadNodeTypes } = await import(`${JS}node-types.js`);
const { GraphModel } = await import(`${JS}graph-model.js`);

before(() => loadTypes(loadNodeTypes));

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

/** Replace fetch; every call is recorded as [method, url, parsed body]. */
function stubFetch(answer = {}) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push([options.method ?? "GET", url, options.body === undefined ? undefined : JSON.parse(options.body)]);
    return { status: 200, ok: true, json: async () => (typeof answer === "function" ? answer(url) : answer) };
  };
  return calls;
}

const graph = {
  graph: { id: "g1", name: "Flow" },
  nodes: [
    { id: "t", kind: "trigger", x: 0, y: 0 },
    { id: "a", kind: "action", x: 0, y: 0, stage_id: "s", definition_fail_enabled: false },
    { id: "s", kind: "stage", x: 0, y: 0, width: 400, height: 300 },
    { id: "c1", kind: "complete", x: 0, y: 0 },
  ],
  edges: [
    { id: "e1", source_id: "t", source_port: "out", target_id: "s", target_port: "start" },
    { id: "e2", source_id: "a", source_port: "error", target_id: "c1", target_port: "in" },
    { id: "e3", source_id: "s", source_port: "end", target_id: "a", target_port: "error" },
    { id: "e4", source_id: "a", source_port: "out", target_id: "c1", target_port: "in" },
  ],
};

test("load replaces nodes and edges in the same Maps the canvas holds", async () => {
  stubFetch(graph);
  const model = new GraphModel("pipeline", "g1");
  const { nodes, edges } = model;
  model.nodes.set("stale", {});
  model.edges.set("stale", {});
  await model.load();
  assert.equal(model.nodes, nodes);
  assert.equal(model.edges, edges);
  assert.deepEqual([...model.nodes.keys()], ["t", "a", "s", "c1"]);
  assert.deepEqual([...model.edges.keys()], ["e1", "e2", "e3", "e4"]);
  assert.deepEqual(model.graph, { id: "g1", name: "Flow" });
});

test("isAction depends on the kind of graph", () => {
  assert.equal(new GraphModel("action", "x").isAction, true);
  assert.equal(new GraphModel("pipeline", "x").isAction, false);
});

test("count and isFixed: the last trigger, complete or output stays; stages and actions may go", async () => {
  stubFetch(graph);
  const model = new GraphModel("pipeline", "g1");
  await model.load();
  assert.equal(model.count("trigger"), 1);
  assert.equal(model.count("action"), 1);
  assert.equal(model.count("output"), 0);
  assert.equal(model.isFixed(model.nodes.get("t")), true);
  assert.equal(model.isFixed(model.nodes.get("c1")), true);
  assert.equal(model.isFixed(model.nodes.get("s")), false);
  model.nodes.set("t2", { id: "t2", kind: "trigger" });
  assert.equal(model.isFixed(model.nodes.get("t")), false, "a second trigger may be deleted");
});

test("dropHiddenEdges forgets edges at hidden ports, from either end, and keeps the others", async () => {
  stubFetch(graph);
  const model = new GraphModel("pipeline", "g1");
  await model.load();
  model.dropHiddenEdges(model.nodes.get("a"));
  assert.deepEqual([...model.edges.keys()], ["e1", "e4"], "e2 leaves the hidden error port, e3 arrives at it");
});

test("edgeFrom finds the one connection that leaves a port", async () => {
  stubFetch(graph);
  const model = new GraphModel("pipeline", "g1");
  await model.load();
  assert.equal(model.edgeFrom("a", "out").id, "e4");
  assert.equal(model.edgeFrom("a", "pass"), undefined);
  assert.equal(model.edgeFrom("missing", "out"), undefined);
});

test("saving calls go to the right resource of the kind, with the ids encoded", async () => {
  const calls = stubFetch({ ok: true });
  const pipeline = new GraphModel("pipeline", "p 1");
  await pipeline.rename("New");
  await pipeline.addNode({ kind: "timer" });
  await pipeline.updateNode("n/1", { x: 5 });
  await pipeline.deleteNode("n1");
  await pipeline.connect({ source_id: "a" });
  await pipeline.restyle("e1", "elbow");
  await pipeline.disconnect("e1");
  const action = new GraphModel("action", "d1");
  await action.rename("Other");
  assert.deepEqual(calls, [
    ["PATCH", "/api/pipelines/p%201", { name: "New" }],
    ["POST", "/api/pipelines/p%201/nodes", { kind: "timer" }],
    ["PATCH", "/api/pipelines/p%201/nodes/n%2F1", { x: 5 }],
    ["DELETE", "/api/pipelines/p%201/nodes/n1", undefined],
    ["POST", "/api/pipelines/p%201/edges", { source_id: "a" }],
    ["PATCH", "/api/pipelines/p%201/edges/e1", { style: "elbow" }],
    ["DELETE", "/api/pipelines/p%201/edges/e1", undefined],
    ["PATCH", "/api/actions/d1", { name: "Other" }],
  ]);
});

test("the listing and creating calls of editor/api.js", async () => {
  const calls = stubFetch([]);
  const api = await import(`${JS}api.js`);
  await api.listGraphs("action");
  await api.listGraphs("pipeline");
  await api.createGraph("action", "Deploy");
  await api.deleteGraph("pipeline", "p1");
  await api.loadGraph("action", "d1");
  assert.deepEqual(calls, [
    ["GET", "/api/actions", undefined],
    ["GET", "/api/pipelines", undefined],
    ["POST", "/api/actions", { name: "Deploy" }],
    ["DELETE", "/api/pipelines/p1", undefined],
    ["GET", "/api/actions/d1", undefined],
  ]);
});
