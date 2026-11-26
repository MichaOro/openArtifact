import assert from "node:assert/strict";
import { test } from "node:test";

const { contextSummary, formatContext } = await import("../../openartifact/static/js/tasks/context-format.js");

test("an empty or missing context reads as empty and formats as empty parts", () => {
  assert.equal(contextSummary(undefined), "empty");
  assert.equal(contextSummary({ vars: {}, nodes: {} }), "empty");
  assert.deepEqual(JSON.parse(formatContext(null)), { vars: {}, nodes: {} });
});

test("the summary counts variables and node results", () => {
  assert.equal(contextSummary({ vars: { a: 1 }, nodes: { X: {}, Y: {} } }), "1 variable · 2 node results");
  assert.equal(contextSummary({ vars: { a: 1, b: 2 }, nodes: {} }), "2 variables · 0 node results");
});

test("the text is indented JSON with vars first and keeps values as they are", () => {
  const text = formatContext({ nodes: { A: { output: "<b>x</b>" } }, vars: { n: [1, null] } });
  assert.ok(text.startsWith('{\n  "vars"'));
  assert.deepEqual(JSON.parse(text), { vars: { n: [1, null] }, nodes: { A: { output: "<b>x</b>" } } });
});
