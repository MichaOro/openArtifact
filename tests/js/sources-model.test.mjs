/* The list of sources of a Build Context node (editor/sources-model.js, ADR-078): the rules of the list as pure functions. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const {
  DEFAULT_SOURCES, addSource, entryProblem, formatBytes, listProblem, moveSource, parseNames, removeSource, setOption, specOf, startEntry, summarize, unused,
} = await import("../../openartifact/static/js/editor/sources-model.js");

/** The specs as the server describes them: the live answer recorded for the editor tests. */
const description = JSON.parse(readFileSync(new URL("./../fixtures/node-types.json", import.meta.url), "utf8"));
const setting = description.find((d) => d.kind === "context").settings.find((s) => s.key === "sources");
const specs = setting.sources;

test("the specs of the server are what the editor offers, in the order of the menu", () => {
  assert.deepEqual(specs.map((s) => s.key), ["card", "fields", "comments", "parent", "children", "siblings", "nodes", "handovers", "executions"]);
  assert.equal(setting.max_sources, 9);
});

test("the default list of the editor is the default of the setting (a node whose list was never saved builds from it)", () => {
  assert.deepEqual(DEFAULT_SOURCES, setting.default);
});

test("a new entry starts with every option its source takes at the default", () => {
  assert.deepEqual(startEntry(specOf(specs, "card")), { source: "card" });
  assert.deepEqual(startEntry(specOf(specs, "comments")), { source: "comments", count: 20 });
  assert.deepEqual(startEntry(specOf(specs, "children")), { source: "children", count: 20, detail: "title" });
  assert.deepEqual(startEntry(specOf(specs, "parent")), { source: "parent", detail: "title" });
  assert.deepEqual(startEntry(specOf(specs, "nodes")), { source: "nodes", names: [] });
  assert.deepEqual(startEntry(specOf(specs, "executions")), { source: "executions", count: 3 });
});

test("a source can be added once: what is in the list is no longer offered", () => {
  const list = [{ source: "card" }, { source: "comments", count: 20 }];
  assert.deepEqual(unused(list, specs).map((s) => s.key), ["fields", "parent", "children", "siblings", "nodes", "handovers", "executions"]);
  assert.deepEqual(unused([], specs).length, 9);
});

test("add, remove and move return a new list and never change the one they were given", () => {
  const list = Object.freeze([{ source: "card" }, { source: "comments", count: 20 }, { source: "parent", detail: "title" }]);
  assert.deepEqual(addSource(list, specOf(specs, "fields")).map((e) => e.source), ["card", "comments", "parent", "fields"]);
  assert.deepEqual(removeSource(list, 1).map((e) => e.source), ["card", "parent"]);
  assert.deepEqual(moveSource(list, 2, 0).map((e) => e.source), ["parent", "card", "comments"]);
  assert.deepEqual(moveSource(list, 0, 1).map((e) => e.source), ["comments", "card", "parent"]);
  assert.equal(moveSource(list, 1, 1), list);
  assert.equal(moveSource(list, 0, 9), list);
  assert.equal(list.length, 3);
});

test("an option is set on one entry only", () => {
  const list = [{ source: "comments", count: 20 }, { source: "executions", count: 3 }];
  const next = setOption(list, 1, "count", 7);
  assert.deepEqual(next, [{ source: "comments", count: 20 }, { source: "executions", count: 3 + 4 }]);
  assert.equal(list[1].count, 3);
});

test("node names are read one per line, trimmed, blank lines dropped", () => {
  assert.deepEqual(parseNames("  Classify \n\nFetch data\n   \n"), ["Classify", "Fetch data"]);
  assert.deepEqual(parseNames(""), []);
});

test("a count outside its bounds, a text that is no number and too many or double node names are problems with a code", () => {
  const comments = specOf(specs, "comments");
  assert.deepEqual(entryProblem({ source: "comments", count: 20 }, comments), null);
  assert.equal(entryProblem({ source: "comments", count: 0 }, comments).code, "count_bounds");
  assert.equal(entryProblem({ source: "comments", count: 101 }, comments).code, "count_bounds");
  assert.equal(entryProblem({ source: "comments", count: null }, comments).code, "count_bounds"); // an emptied field
  assert.equal(entryProblem({ source: "comments", count: 2.5 }, comments).code, "count_bounds");
  assert.deepEqual(entryProblem({ source: "comments", count: 0 }, comments).params, { label: "Comments", min: 1, max: 100 });
  const nodes = specOf(specs, "nodes");
  assert.equal(entryProblem({ source: "nodes", names: Array.from({ length: 11 }, (_, i) => `n${i}`) }, nodes).code, "names_many");
  assert.equal(entryProblem({ source: "nodes", names: ["A", "A"] }, nodes).code, "names_twice");
  assert.equal(entryProblem({ source: "nodes", names: ["x".repeat(201)] }, nodes).code, "names_long");
  assert.equal(entryProblem({ source: "nodes", names: ["A", "B"] }, nodes), null);
});

test("the first problem of a list is told, an unknown source is left to the server", () => {
  assert.equal(listProblem([{ source: "card" }, { source: "comments", count: 0 }], specs).code, "count_bounds");
  assert.equal(listProblem([{ source: "card" }, { source: "weather" }], specs), null);
  assert.equal(listProblem(DEFAULT_SOURCES, specs), null);
});

test("the caption names the first two sources and counts the rest", () => {
  const say = { empty: "no source yet", more: (n) => `+${n} more` };
  const label = (key) => key.toUpperCase();
  assert.equal(summarize([], label, say), "no source yet");
  assert.equal(summarize(undefined, label, say), "no source yet");
  assert.equal(summarize([{ source: "card" }], label, say), "CARD");
  assert.equal(summarize([{ source: "card" }, { source: "fields" }], label, say), "CARD, FIELDS");
  assert.equal(summarize([{ source: "card" }, { source: "fields" }, { source: "parent" }, { source: "nodes" }], label, say), "CARD, FIELDS +2 more");
});

test("a size for reading is shown with one decimal in the unit that fits", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(812), "812 B");
  assert.equal(formatBytes(1024), "1.0 KiB");
  assert.equal(formatBytes(5213), "5.1 KiB");
  assert.equal(formatBytes(8192), "8.0 KiB");
  assert.equal(formatBytes(1572864), "1.5 MiB");
  assert.equal(formatBytes("nonsense"), "0 B");
  assert.equal(formatBytes(-4), "0 B");
});
