import assert from "node:assert/strict";
import { test } from "node:test";

const { layoutScene, sceneOfGraph } = await import("../../openartifact/static/js/components/preview-layout.js");

const node = (id, kind = "code", y = 0, extra = {}) => ({ id, kind, name: id, x: 0, y, ...extra });
const edge = (a, b, port = "pass", to = "in") => ({ source_id: a, source_port: port, target_id: b, target_port: to });
const isTool = (kind) => kind.endsWith("_tool");

/** The owner's pipeline "Test: Code und HTTP": a trigger, three stages with three actions each (pass and error connections, retries
 * back to an earlier action), the end. Ids as in the database. */
function ownersPipeline() {
  const stage = (id, y) => node(id, "stage", y);
  const action = (id, stageId, y) => node(id, "action", y, { stage_id: stageId });
  const nodes = [
    node("trigger", "trigger", -23),
    node("complete", "complete", 297),
    stage("S2", -149), action("a1", "S2", 23), action("a2", "S2", 12), action("a3", "S2", 132),
    stage("S1", -163), action("b1", "S1", 23), action("b2", "S1", 12), action("b3", "S1", 165),
    stage("S3", 235), action("c1", "S3", 23), action("c2", "S3", 12), action("c3", "S3", 132),
  ];
  const edges = [
    edge("S2", "a1", "start"), edge("c1", "c2"), edge("S1", "S2", "end", "start"), edge("b3", "b1", "error"),
    edge("S2", "S3", "end", "start"), edge("c1", "c3", "error"), edge("b1", "b2"), edge("a2", "a1", "error"),
    edge("c2", "c3"), edge("c3", "c1", "error"), edge("a2", "a3"), edge("S3", "c1", "start"),
    edge("trigger", "S1", "out", "start"), edge("c3", "S3", "pass", "end"), edge("b1", "b3", "error"), edge("c2", "c1", "error"),
    edge("b2", "b1", "error"), edge("S3", "complete", "end"), edge("a3", "S2", "pass", "end"), edge("b2", "b3"),
    edge("b3", "S1", "pass", "end"), edge("a1", "a2"), edge("a1", "a3", "error"), edge("a3", "a1", "error"), edge("S1", "b1", "start"),
  ];
  return { nodes, edges };
}

const inside = (p, n) => p[0] > n.x + 1 && p[0] < n.x + n.width - 1 && p[1] > n.y + 1 && p[1] < n.y + n.height - 1;

function crossings(picture) {
  const found = [];
  for (const e of picture.edges) {
    for (const n of picture.nodes) {
      if (n.id === e.from || n.id === e.to) continue;
      if (e.points.some((p) => inside(p, n))) found.push(`${e.id} crosses ${n.id}`);
    }
  }
  return found;
}

test("the owner's pipeline: every connection is drawn once, the stages are frames around their three actions", () => {
  const detail = ownersPipeline();
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 2000 });
  assert.equal(picture.orientation, "horizontal");
  assert.equal(picture.edges.length, detail.edges.length, "all 25 connections");
  assert.equal(new Set(picture.edges.map((e) => e.id)).size, 25);
  assert.equal(picture.clusters.length, 3);
  for (const cluster of picture.clusters) {
    const held = picture.nodes.filter((n) => n.cluster === cluster.id);
    assert.equal(held.length, 3, `${cluster.id} holds its three actions`);
    for (const n of held) assert.ok(n.x >= cluster.x && n.y >= cluster.y && n.x + n.width <= cluster.x + cluster.width && n.y + n.height <= cluster.y + cluster.height, `${n.id} is inside the frame`);
  }
  // the stages follow each other as the connections say: S1, S2, S3, between the trigger and the end
  const frame = Object.fromEntries(picture.clusters.map((c) => [c.id, c]));
  const at = Object.fromEntries(picture.nodes.map((n) => [n.id, n]));
  assert.ok(at.trigger.x < frame.S1.x && frame.S1.x + frame.S1.width < frame.S2.x && frame.S2.x + frame.S2.width < frame.S3.x && frame.S3.x + frame.S3.width < at.complete.x);
  // inside a stage the actions follow their connections: 1, 2, 3 (the retries lead back)
  assert.ok(at.a1.x < at.a2.x && at.a2.x < at.a3.x);
  assert.ok(at.b1.x < at.b2.x && at.b2.x < at.b3.x);
});

test("errors are failures and passes are passes, the others are neither", () => {
  const picture = layoutScene(sceneOfGraph(ownersPipeline(), isTool), { available: 2000 });
  const byId = (from, to, role) => picture.edges.find((e) => e.from === from && e.to === to && (!role || e.role === role));
  assert.equal(byId("b1", "b3").failing, true);
  assert.equal(byId("b1", "b2").failing, false);
  assert.equal(byId("b1", "b2").passing, true);
  assert.equal(byId("trigger", "S1").failing, false);
  assert.equal(byId("trigger", "S1").passing, false);
  assert.equal(byId("S1", "S2").role, "flow");
  assert.equal(byId("S1", "b1").role, "entry");
  assert.equal(byId("b3", "S1").role, "exit");
});

test("no line of the owner's pipeline crosses a node it does not belong to, horizontal or turned", () => {
  for (const available of [2000, 900, 300]) {
    const picture = layoutScene(sceneOfGraph(ownersPipeline(), isTool), { available });
    assert.deepEqual(crossings(picture), [], `at ${available} px (${picture.orientation})`);
  }
});

test("a place too narrow for the row turns the whole picture, the frames stay", () => {
  const wide = layoutScene(sceneOfGraph(ownersPipeline(), isTool), { available: 2000 });
  const narrow = layoutScene(sceneOfGraph(ownersPipeline(), isTool), { available: 300 });
  assert.equal(narrow.orientation, "vertical");
  assert.equal(narrow.clusters.length, 3);
  assert.ok(narrow.width < wide.width && narrow.height > wide.height);
  const at = Object.fromEntries(narrow.nodes.map((n) => [n.id, n]));
  assert.ok(at.trigger.y < at.complete.y, "the first layer is on top");
});

test("a linear pipeline is the trigger, one frame and the end", () => {
  const detail = {
    nodes: [node("t", "trigger"), node("s", "stage"), node("a", "action", 0, { stage_id: "s" }), node("end", "complete")],
    edges: [edge("t", "s", "out", "start"), edge("s", "a", "start"), edge("a", "s", "pass", "end"), edge("s", "end", "end")],
  };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 600 });
  assert.equal(picture.edges.length, 4);
  assert.equal(picture.clusters.length, 1);
  assert.deepEqual(crossings(picture), []);
});

test("a branch puts its nodes in one layer, one below the other, ordered as the editor has them", () => {
  const detail = {
    nodes: [node("t", "trigger"), node("if", "if", 5), node("b", "code", 20), node("a", "code", 10), node("out", "output")],
    edges: [edge("t", "if", "out"), edge("if", "a", "true"), edge("if", "b", "else"), edge("a", "out"), edge("b", "out", "pass")],
  };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 600 });
  const at = Object.fromEntries(picture.nodes.map((n) => [n.id, n]));
  assert.equal(at.a.x, at.b.x);
  assert.ok(at.a.y < at.b.y, "the node the editor has higher is higher");
  assert.equal(picture.edges.find((e) => e.to === "b").failing, true);
  assert.deepEqual(crossings(picture), []);
});

test("a tool hangs below its agent with a dashed (tool) line and is not part of the flow", () => {
  const detail = {
    nodes: [node("t", "trigger"), node("agent", "agent"), node("hub", "github_tool", 100), node("out", "output")],
    edges: [edge("t", "agent", "out"), edge("agent", "out"), { source_id: "hub", source_port: "tool", target_id: "agent", target_port: "tools" }],
  };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 600 });
  const at = Object.fromEntries(picture.nodes.map((n) => [n.id, n]));
  assert.equal(at.hub.x, at.agent.x);
  assert.ok(at.hub.y > at.agent.y);
  assert.equal(picture.edges.filter((e) => e.tool).length, 1);
  assert.equal(picture.edges.length, 3);
  assert.deepEqual(crossings(picture), []);
});

test("a loop leads back below the nodes and does not run away", () => {
  const detail = { nodes: [node("a"), node("b"), node("c")], edges: [edge("a", "b"), edge("b", "c"), edge("c", "a", "error"), edge("b", "b", "error")] };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 600 });
  assert.equal(picture.edges.length, 4);
  const lowest = Math.max(...picture.nodes.map((n) => n.y + n.height));
  const back = picture.edges.find((e) => e.from === "c");
  assert.ok(Math.max(...back.points.map((p) => p[1])) > lowest, "the way back runs below the row");
  assert.deepEqual(crossings(picture), []);
});

test("a connection that skips a layer runs above the nodes of the layers it passes", () => {
  const detail = { nodes: [node("a"), node("b"), node("c")], edges: [edge("a", "b"), edge("b", "c"), edge("a", "c", "error")] };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 600 });
  assert.equal(picture.edges.length, 3);
  assert.deepEqual(crossings(picture), []);
});

test("a graph without nodes is an empty picture; a connection to a node that is not there is left out", () => {
  assert.equal(layoutScene(sceneOfGraph({ nodes: [], edges: [] }, isTool), { available: 100 }).width, 0);
  const detail = { nodes: [node("a")], edges: [edge("a", "ghost")] };
  assert.equal(layoutScene(sceneOfGraph(detail, isTool), { available: 100 }).edges.length, 0);
});

test("a row that fits stays horizontal at full size; one layer is never turned", () => {
  const detail = { nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const picture = layoutScene(sceneOfGraph(detail, isTool), { available: 400 });
  assert.equal(picture.orientation, "horizontal");
  assert.equal(picture.scale, 1);
  const one = layoutScene(sceneOfGraph({ nodes: [node("a")], edges: [] }, isTool), { available: 10 });
  assert.equal(one.orientation, "horizontal");
});
