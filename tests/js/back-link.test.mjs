import assert from "node:assert/strict";
import test from "node:test";
import { backTarget, editorOrigin, withOrigin } from "../../openartifact/static/js/execution/back-link.js";

test("the Back button leads to where the user came from, by a short word", () => {
  assert.deepEqual(backTarget("board"), { kind: "board", href: "/", named: false });
  assert.deepEqual(backTarget("executions"), { kind: "executions", href: "/executions", named: false });
  assert.deepEqual(backTarget("card:12"), { kind: "card", href: "/?artifact=12", named: false });
  assert.deepEqual(backTarget("action:test-code-http"), { kind: "action", href: "/actions/test-code-http", named: true });
  assert.deepEqual(backTarget("pipeline:flow-1"), { kind: "pipeline", href: "/pipelines/flow-1", named: true });
});

test("anything that is not on the list is the board: no address is ever taken from the link", () => {
  for (const bad of [null, undefined, "", "elsewhere", "https://evil.example/", "//evil.example", "action:../x", "action:a/b", "card:x", "card:1234567890", "action:", "pipeline:a b", "javascript:alert(1)"]) {
    assert.deepEqual(backTarget(bad), { kind: "board", href: "/", named: false }, String(bad));
  }
});

test("a link to an execution carries its origin, after an existing query too", () => {
  assert.equal(withOrigin("/artifacts/3/executions/e1", "card:3"), "/artifacts/3/executions/e1?from=card%3A3");
  assert.equal(withOrigin("/x?visit=2", "executions"), "/x?visit=2&from=executions");
  assert.equal(withOrigin("/x", null), "/x");
});

test("the editor the user is on is the origin of a link followed from it", () => {
  assert.equal(editorOrigin("/actions/my-action"), "action:my-action");
  assert.equal(editorOrigin("/pipelines/flow/"), "pipeline:flow");
  assert.equal(editorOrigin("/actions"), null);
  assert.equal(editorOrigin("/settings/personal"), null);
});
