import assert from "node:assert/strict";
import { before, test } from "node:test";
import { loadTypes } from "./support.mjs";

const JS = new URL("../../openartifact/static/js/editor/", import.meta.url).href;
const { loadNodeTypes, typeOf } = await import(`${JS}node-types.js`);
const g = await import(`${JS}geometry.js`);

before(() => loadTypes(loadNodeTypes));

const node = (kind, config = {}, name = "Tickets") => ({ id: `n-${kind}`, kind, name, x: 100, y: 300, config });
const agent = { id: "a", kind: "agent", name: "Ask", x: 100, y: 100, config: {} };
const output = { id: "o", kind: "output", name: "Output", x: 500, y: 100, fail_enabled: true };

test("a GitHub card says the operation and the repository", () => {
  const type = typeOf("github");
  assert.equal(type.caption(node("github", { operation: "List issues", repository: "acme/tool" })), "List issues · acme/tool");
  assert.equal(type.caption(node("github", { repository: "${var.repo}" })), "Get repository · ${var.repo}");
  assert.equal(type.caption(node("github")), "Get repository · no repository yet");
  assert.equal(type.constructor.icon, "github");
});

test("a GitHub card shows when it writes, and only then", () => {
  const type = typeOf("github");
  const comment = { operation: "Create comment", repository: "acme/tool", allow_comments: true };
  assert.equal(type.caption(node("github", comment)), "Create comment · acme/tool");
  assert.equal(type.caption(node("github", { ...comment, allow_comments: false })), "Create comment (off) · acme/tool");
});

test("a Postgres card shows the first line of its query, and when it may change data", () => {
  const type = typeOf("postgres");
  assert.equal(type.caption(node("postgres", { query: "\n  SELECT id, title\nFROM tickets" })), "SELECT id, title");
  assert.equal(type.caption(node("postgres")), "no query yet");
  assert.equal(type.caption(node("postgres", { query: "UPDATE tickets SET status = $1", allow_write: true })), "changes · UPDATE tickets SET status = $1");
  assert.equal(type.caption(node("postgres", { query: "SELECT " + "x".repeat(80) })).length, 41); // cut with …
  assert.equal(type.constructor.icon, "database");
});

test("a Postgres node is a flow node with the usual ports", () => {
  const type = typeOf("postgres");
  assert.ok(!type.tool);
  assert.deepEqual(type.ports().map((p) => [p.name, p.direction]), [["in", "input"], ["pass", "output"], ["fail", "output"]]);
  assert.equal(g.canConnect(node("postgres"), "pass", output, "pass"), true);
  assert.equal(g.canConnect(node("postgres"), "pass", agent, "tools"), false);
});

test("a Postgres Tool hangs below an agent like the other tools", () => {
  const type = typeOf("postgres_tool");
  const tool = node("postgres_tool", { tool_name: "find_tickets", query: "SELECT 1" });
  assert.equal(type.tool, true);
  assert.deepEqual(type.ports().map((p) => [p.name, p.direction, p.side]), [["tool", "output", "top"]]);
  assert.equal(g.canConnect(tool, "tool", agent, "tools"), true);
  assert.equal(g.canConnect(tool, "tool", output, "pass"), false);
  assert.equal(type.caption(tool), "find_tickets · SELECT 1");
  assert.equal(type.caption(node("postgres_tool")), "Tickets · no query yet");
  assert.equal(type.constructor.icon, "database");
});
