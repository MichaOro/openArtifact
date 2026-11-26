import assert from "node:assert/strict";
import { test } from "node:test";

const { copyOf, pastePlan, uniqueName } = await import("../../openartifact/static/js/editor/clipboard.js");

const node = (id, kind, extra = {}) => ({ id, kind, name: kind, x: 0, y: 0, stage_id: null, config: {}, ...extra });
const edge = (id, source, target, extra = {}) => ({ id, source_id: source, source_port: "pass", source_slot: 0, target_id: target, target_port: "in", target_slot: 0, style: "curved", ...extra });

const NODES = [
  node("t", "trigger"),
  node("c1", "code", { name: "Fetch", x: 100, y: 50, config: { code: "echo 1" } }),
  node("c2", "code", { name: "Parse", x: 300, y: 50 }),
  node("o", "output"),
  node("s", "stage", { name: "Build", x: 40, y: 40, width: 400, height: 200 }),
  node("a1", "action", { name: "Compile", stage_id: "s", x: 20, y: 10, definition_id: "def-1" }),
];
const EDGES = [edge("e1", "t", "c1"), edge("e2", "c1", "c2"), edge("e3", "c2", "o")];

test("names of copies stay unique: copy, copy 2, copy 3", () => {
  assert.equal(uniqueName("Fetch", new Set(["Fetch"])), "Fetch copy");
  assert.equal(uniqueName("Fetch", new Set(["Fetch", "Fetch copy"])), "Fetch copy 2");
  assert.equal(uniqueName("Fetch copy", new Set(["Fetch", "Fetch copy"])), "Fetch copy 2", "a copy of a copy does not pile up words");
  assert.equal(uniqueName("Fetch", new Set(["Fetch", "Fetch copy", "Fetch copy 2"])), "Fetch copy 3");
});

test("a copy holds the chosen nodes and only the connections between them; fixed nodes are left out", () => {
  const copy = copyOf(NODES, EDGES, ["t", "c1", "c2", "o"], "action");
  assert.deepEqual(copy.nodes.map((n) => n.key), ["c1", "c2"]);
  assert.deepEqual(copy.edges.map((e) => [e.source, e.target]), [["c1", "c2"]]);
  assert.equal(copy.nodes[0].config.code, "echo 1");
  assert.equal(copyOf(NODES, EDGES, ["t", "o"], "action"), null, "nothing copyable");
});

test("copying a stage takes its actions along, with their place inside it", () => {
  const copy = copyOf(NODES, EDGES, ["s"], "pipeline");
  assert.deepEqual(copy.nodes.map((n) => n.key), ["s", "a1"]);
  assert.equal(copy.nodes[1].stage, "s");
  assert.equal(copy.nodes[1].definition_id, "def-1");
  assert.equal(copy.nodes[0].width, 400);
});

test("a copy does not alias the nodes it was made from", () => {
  const copy = copyOf(NODES, EDGES, ["c1"], "action");
  copy.nodes[0].config.code = "changed";
  assert.equal(NODES[1].config.code, "echo 1");
});

test("pasting plans top-level nodes before the actions inside them, with unique names and an offset", () => {
  const copy = copyOf(NODES, EDGES, ["a1", "s"], "pipeline");
  const plan = pastePlan(copy, { offset: 40, names: new Set(["Build", "Compile"]), stageFor: () => null });
  assert.deepEqual(plan.items.map((i) => i.key), ["s", "a1"]);
  assert.deepEqual(plan.items.map((i) => i.name), ["Build copy", "Compile copy"]);
  assert.deepEqual([plan.items[0].x, plan.items[0].y], [80, 80]); // the stage moves
  assert.deepEqual([plan.items[1].x, plan.items[1].y], [20, 10]); // an action keeps its place inside its stage
  assert.equal(plan.items[1].stage, "s");
});

test("a lone action goes to the stage the caller names; without one the paste is refused with the reason", () => {
  const copy = copyOf(NODES, EDGES, ["a1"], "pipeline");
  const ok = pastePlan(copy, { offset: 40, names: new Set(), stageFor: (old) => (old === "s" ? "s" : null) });
  assert.equal(ok.items[0].existingStage, "s");
  const refused = pastePlan(copy, { offset: 40, names: new Set(), stageFor: () => null });
  assert.match(refused.error, /stage/);
});

test("connections between pasted nodes follow them to their new keys", () => {
  const copy = copyOf(NODES, EDGES, ["c1", "c2"], "action");
  const plan = pastePlan(copy, { offset: 40, names: new Set(["Fetch", "Parse"]), stageFor: () => null });
  assert.deepEqual(plan.edges.map((e) => [e.source, e.target, e.source_port, e.target_port]), [["c1", "c2", "pass", "in"]]);
});

test("kinds this editor cannot add are skipped and said so", () => {
  const copy = copyOf(NODES, EDGES, ["c1", "s"], "pipeline");
  const plan = pastePlan(copy, { offset: 0, names: new Set(), stageFor: () => null, allowed: new Set(["stage", "action"]) });
  assert.deepEqual(plan.items.map((i) => i.key), ["s", "a1"]);
  assert.deepEqual(plan.skipped, ["code"]);
});

test("a tool copied without its agent remembers the agent", () => {
  const nodes = [node("ag", "agent"), node("tl", "http_tool", { name: "Call" })];
  const edges = [edge("e1", "tl", "ag", { source_port: "tool", target_port: "tools" })];
  assert.deepEqual(copyOf(nodes, edges, ["tl"], "action").attached, { tl: "ag" });
  assert.deepEqual(copyOf(nodes, edges, ["tl", "ag"], "action").attached, {}, "with its agent the connection is copied instead");
});

test("a paste turns the ids a copied node holds into the ids of the copies, and leaves other ids alone (ADR-082)", async () => {
  const { remapReferences, remappedConfig } = await import("../../openartifact/static/js/editor/clipboard.js");
  const old = "11111111-1111-4111-8111-111111111111";
  const other = "22222222-2222-4222-8222-222222222222";
  const fresh = "33333333-3333-4333-8333-333333333333";
  const ids = new Map([[old, fresh]]);
  assert.equal(remapReferences(`http://x/\${node:${old}.output}/\${node:${other}.output}`, ids), `http://x/\${node:${fresh}.output}/\${node:${other}.output}`);
  assert.deepEqual(remapReferences({ input_values: { who: `\${node:${old}.data.greeting}` }, list: [`\${node:${old}.output}`, 3, null] }, ids), { input_values: { who: `\${node:${fresh}.data.greeting}` }, list: [`\${node:${fresh}.output}`, 3, null] });
  assert.deepEqual(remappedConfig({ url: `\${node:${old}.output}`, timeout: 30 }, ids), { url: `\${node:${fresh}.output}` }, "only what changes");
  assert.equal(remappedConfig({ url: "plain" }, ids), null);
  assert.equal(remappedConfig(undefined, ids), null);
});
