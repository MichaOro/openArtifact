import assert from "node:assert/strict";
import { before, test } from "node:test";
import { loadTypes } from "./support.mjs";

const JS = new URL("../../openartifact/static/js/editor/", import.meta.url).href;
const { loadNodeTypes, typeOf } = await import(`${JS}node-types.js`);
const g = await import(`${JS}geometry.js`);
const { EDGE_KINDS } = await import(`${JS}edge-kinds.js`);

before(() => loadTypes(loadNodeTypes));

const agent = { id: "a", kind: "agent", name: "Ask", x: 100, y: 100, config: {} };
const tool = (kind, config = {}) => ({ id: `t-${kind}`, kind, name: "GitHub", x: 100, y: 300, config });
const output = { id: "o", kind: "output", name: "Output", x: 500, y: 100, fail_enabled: true };
const code = { id: "c", kind: "code", name: "Code", x: 0, y: 0, config: {} };

test("the Tools port of an agent sits at the middle of its bottom; its input stays on the left", () => {
  const type = typeOf(agent);
  const { width, height } = type.size(agent);
  assert.deepEqual(type.portLocal(agent, "tools"), { x: width / 2, y: height });
  assert.deepEqual(type.portLocal(agent, "in"), { x: 0, y: height / 2 }); // the only input on the left
  const tools = type.ports().find((p) => p.name === "tools");
  assert.deepEqual([tools.direction, tools.side], ["input", "bottom"]);
  assert.equal(type.ports().find((p) => p.name === "in").side, "left");
});

test("a tool node has one port, at the middle of its top", () => {
  for (const kind of ["mcp_tool", "http_tool", "code_tool"]) {
    const type = typeOf(kind);
    const node = tool(kind);
    assert.equal(type.tool, true);
    assert.deepEqual(type.ports().map((p) => [p.name, p.direction, p.side]), [["tool", "output", "top"]]);
    assert.deepEqual(type.portLocal(node, "tool"), { x: type.size(node).width / 2, y: 0 });
  }
});

test("a tool attaches only to the Tools port of an agent, and only a tool does", () => {
  const github = tool("mcp_tool");
  assert.equal(g.canConnect(github, "tool", agent, "tools"), true);
  assert.equal(g.canConnect(github, "tool", agent, "in"), false);
  assert.equal(g.canConnect(github, "tool", output, "pass"), false);
  assert.equal(g.canConnect(code, "pass", agent, "tools"), false);
  assert.equal(g.canConnect(code, "pass", agent, "in"), true); // the flow is unchanged
});

test("an attachment is a vertical curve from the top of the tool up to the agent", () => {
  const from = { x: 200, y: 300 };
  const to = { x: 225, y: 184 };
  const box = { x: 0, y: 0, width: 10, height: 10 };
  const d = g.edgePath(from, to, box, box, { kind: EDGE_KINDS.attachment });
  assert.match(d, /^M 200 300 C 200 (\d+(\.\d+)?), 225 (\d+(\.\d+)?), 225 184$/);
  const [, up, down] = d.match(/C 200 ([\d.]+), 225 ([\d.]+)/).map(Number);
  assert.ok(up < 300 && down > 184, d); // leaves upwards, arrives from below
  // the styles are honoured now (the owner's decision, ADR-093): the same ends, a different line
  const straight = g.edgePath(from, to, box, box, { kind: EDGE_KINDS.attachment, style: "straight" });
  const elbow = g.edgePath(from, to, box, box, { kind: EDGE_KINDS.attachment, style: "elbow" });
  assert.match(straight, /^M 200 300 L 225 184$/);
  assert.match(elbow, /^M 200 300 .* 225 184$/);
  assert.notEqual(elbow, d);
  assert.notEqual(elbow, straight);
});

test("tool cards say what they reach, never a query string", () => {
  assert.equal(typeOf("mcp_tool").caption(tool("mcp_tool", { url: "https://api.githubcopilot.com/mcp/?token=x" })), "api.githubcopilot.com/mcp/");
  assert.equal(typeOf("mcp_tool").caption(tool("mcp_tool")), "no endpoint yet");
  assert.equal(typeOf("http_tool").caption(tool("http_tool", { method: "POST", url: "https://wttr.in/{city}?key=s" })), "POST wttr.in/{city}");
  assert.equal(typeOf("code_tool").caption(tool("code_tool", { language: "sh", tool_name: "add" })), "sh · add");
  assert.equal(typeOf("code_tool").caption(tool("code_tool")), "python · GitHub");
});

test("a new tool goes below the selected agent (or the last one), right of the tools it already has", () => {
  const nodes = new Map([
    ["a", agent],
    ["b", { id: "b", kind: "agent", name: "Other", x: 600, y: 120, config: {} }],
  ]);
  const edges = new Map();
  const height = typeOf(agent).size(agent).height;
  assert.deepEqual(g.nextToolPosition(nodes, edges, "a"), { agentId: "a", x: 100, y: 100 + height + g.TOOL_GAP });
  assert.equal(g.nextToolPosition(nodes, edges, null).agentId, "b"); // nothing selected: the last agent
  assert.equal(g.nextToolPosition(nodes, edges, "zz").agentId, "b");
  nodes.set("t", { id: "t", kind: "mcp_tool", name: "GitHub", x: 100, y: 300, config: {} });
  edges.set("e", { id: "e", source_id: "t", source_port: "tool", target_id: "a", target_port: "tools" });
  assert.equal(g.nextToolPosition(nodes, edges, "a").x, 100 + 200 + g.ACTION_GAP / 2);
  assert.deepEqual(g.nextToolPosition(new Map(), edges, null), null); // no agent: the caller places it like any node
});
