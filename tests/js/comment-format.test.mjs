/* The pure helpers of the Comments tab (static/js/tasks/comment-format.js). */
import assert from "node:assert/strict";
import { test } from "node:test";

import { canSend, countText, inOrder, isEdited, kindOf, runLink, withComment } from "../../openartifact/static/js/tasks/comment-format.js";

const comment = (id, at, extra = {}) => ({ id, created_at: at, updated_at: at, author_kind: "user", author: "You", body: id, execution_id: null, ...extra });

test("every kind of author has a label and an icon, an unknown one keeps its own name", () => {
  assert.deepEqual(["user", "api", "mcp", "run", "system"].map((k) => kindOf({ author_kind: k }).label), ["User", "API", "MCP", "Run", "System"]);
  assert.deepEqual(kindOf({ author_kind: "robot" }), { label: "robot", icon: "message" });
});

test("a comment is edited only when its text changed after it was written", () => {
  assert.equal(isEdited(comment("a", "2026-11-23T10:00:00Z")), false);
  assert.equal(isEdited(comment("a", "2026-11-23T10:00:00Z", { updated_at: "2026-11-23T10:05:00Z" })), true);
});

test("only a run comment with an execution links to it, by the artifact's number", () => {
  const run = comment("r", "2026-11-23T10:00:00Z", { author_kind: "run", execution_id: "e/1" });
  assert.equal(runLink(run, 12), "/artifacts/12/executions/e%2F1");
  assert.equal(runLink({ ...run, execution_id: null }, 12), null);
  assert.equal(runLink({ ...run, author_kind: "user" }, 12), null);
  assert.equal(runLink(run, null), null);
});

test("comments are shown oldest first, newest last, and a changed one replaces its old version", () => {
  const a = comment("a", "2026-11-23T10:00:00Z");
  const b = comment("b", "2026-11-23T10:01:00Z");
  assert.deepEqual(inOrder([b, a]).map((c) => c.id), ["a", "b"]);
  const edited = { ...a, body: "new", updated_at: "2026-11-23T10:09:00Z" };
  const next = withComment([a, b], edited);
  assert.deepEqual(next.map((c) => c.id), ["a", "b"]);
  assert.equal(next[0].body, "new");
  assert.equal(withComment([a], a).length, 1); // an event that arrives after the answer adds nothing twice
});

test("the count is said in words and white space alone cannot be sent", () => {
  assert.equal(countText(1), "1 comment");
  assert.equal(countText(0), "0 comments");
  assert.equal(countText(5), "5 comments");
  assert.equal(canSend(" \n\t "), false);
  assert.equal(canSend(" a "), true);
});
