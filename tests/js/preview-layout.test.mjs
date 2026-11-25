import assert from "node:assert/strict";
import { test } from "node:test";

const { layoutPreview, structureOfChain, structureOfGraph } = await import("../../openartifact/static/js/components/preview-layout.js");

const node = (id, kind = "code", y = 0) => ({ id, kind, name: id, y });
const edge = (a, b, port = "pass") => ({ source_id: a, source_port: port, target_id: b, target_port: "in" });
const isTool = (kind) => kind.endsWith("_tool");

test("a chain of nodes is a row of columns in the order the flow goes, whatever the editor coordinates are", () => {
  const detail = { nodes: [node("out", "output", 10), node("code", "code", 300), node("trigger", "trigger", 50)], edges: [edge("trigger", "code", "out"), edge("code", "out")] };
  const { columns, links } = structureOfGraph(detail, isTool);
  assert.deepEqual(columns.map((c) => c.map((n) => n.id)), [["trigger"], ["code"], ["out"]]);
  assert.deepEqual(links.map((l) => [l.from, l.to]), [["trigger", "code"], ["code", "out"]]);
});

test("a branch puts its nodes in one column, one below the other, and a failing port is a failing link", () => {
  const detail = {
    nodes: [node("t", "trigger"), node("if", "if", 5), node("a", "code", 1), node("b", "code", 2)],
    edges: [edge("t", "if", "out"), edge("if", "a", "true"), edge("if", "b", "else")],
  };
  const { columns, links } = structureOfGraph(detail, isTool);
  assert.deepEqual(columns.map((c) => c.map((n) => n.id)), [["t"], ["if"], ["a", "b"]]);
  assert.equal(links.find((l) => l.to === "b").failing, true);
  assert.equal(links.find((l) => l.to === "a").failing, false);
});

test("a tool hangs in the column of its agent with a dashed link and is not part of the flow", () => {
  const detail = { nodes: [node("t", "trigger"), node("agent", "agent"), node("hub", "github_tool")], edges: [edge("t", "agent", "out"), { source_id: "hub", source_port: "tool", target_id: "agent", target_port: "tools" }] };
  const { columns, links } = structureOfGraph(detail, isTool);
  assert.deepEqual(columns.map((c) => c.map((n) => n.id)), [["t"], ["agent", "hub"]]);
  assert.equal(columns[1][1].tool, true);
  assert.deepEqual(links.at(-1), { from: "agent", to: "hub", dashed: true });
});

test("a loop does not run away", () => {
  const detail = { nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] };
  const { columns } = structureOfGraph(detail, isTool);
  assert.ok(columns.length <= 2);
});

test("a pipeline is the trigger, a column per stage with its actions, and the end", () => {
  const structure = structureOfChain([
    { id: "s1", kind: "stage", name: "Plan", actions: [{ id: "a1", name: "Draft" }, { id: "a2", name: "Check" }] },
    { id: "p", kind: "pipeline", name: "Other" },
  ]);
  assert.deepEqual(structure.columns.map((c) => c.map((n) => n.kind)), [["trigger"], ["action", "action"], ["pipeline"], ["complete"]]);
  assert.equal(structure.columns[1][0].name, "Plan: Draft");
  assert.equal(structure.links.length, 3);
});

test("a row that fits is horizontal at full size and a node of the widest column is the height", () => {
  const structure = { columns: [[{ id: "a" }], [{ id: "b" }, { id: "c" }]], links: [] };
  const picture = layoutPreview(structure, { available: 400 });
  assert.equal(picture.orientation, "horizontal");
  assert.equal(picture.scale, 1);
  assert.deepEqual(picture.nodes.map((n) => [n.id, n.x, n.y]), [["a", 0, 28], ["b", 56, 0], ["c", 56, 56]]);
  assert.equal(picture.height, 92);
});

test("a row that would shrink too far is turned: the columns stand up, the first on top", () => {
  const columns = Array.from({ length: 8 }, (_, i) => [{ id: `n${i}` }]);
  const picture = layoutPreview({ columns, links: [] }, { available: 200, minScale: 0.6 });
  assert.equal(picture.orientation, "vertical");
  assert.equal(picture.scale, 1);
  assert.deepEqual(picture.nodes.slice(0, 2).map((n) => [n.x, n.y]), [[0, 0], [0, 56]]);
  assert.equal(picture.width, 36);
});

test("a row that shrinks only a little stays horizontal and smaller", () => {
  const columns = Array.from({ length: 5 }, (_, i) => [{ id: `n${i}` }]);
  const picture = layoutPreview({ columns, links: [] }, { available: 200 });
  assert.equal(picture.orientation, "horizontal");
  assert.ok(picture.scale < 1 && picture.scale >= 0.6);
});

test("one column is never turned", () => {
  const picture = layoutPreview({ columns: [[{ id: "a" }]], links: [] }, { available: 10 });
  assert.equal(picture.orientation, "horizontal");
});
