/* The card as a source of the run in the editor (ADR-064): the built-in references first in the picker, the input rows of
 * an agent node (the inputs that come from the artifact are fixed, the others are mapped), and the pure parts of the resolved preview. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { candidatesFor, suggestionsFor } from "../../openartifact/static/js/editor/reference-completion.js";
import { formatMapping, mappingRows, parseMapping, partOf, sampleHint, sourceOf } from "../../openartifact/static/js/agents/model.js";

const EPIC = { name: "epic", source: "artifact", part: "title_body" };
const OTHER = { name: "repository", source: "value", type: "string", required: false };

test("the card of this run is the first group and offers what every artifact has, then its own fields", () => {
  const all = candidatesFor([], { cardFields: [{ name: "test", label: "Test" }] });
  const groups = suggestionsFor(all, "");
  assert.deepEqual(groups.map((g) => g.insert), ["card."]);
  assert.equal(groups[0].icon, "card");
  assert.deepEqual(suggestionsFor(all, "card.").map((c) => c.insert), ["card.title", "card.body", "card.text", "card.number", "card.test"]);
  assert.deepEqual(suggestionsFor(all, "card.te").map((c) => c.insert), ["card.text", "card.test"]);
});

test("an input is a value or the artifact; the shape from before the sources reads the same as on the server", () => {
  assert.equal(sourceOf(EPIC), "artifact");
  assert.equal(sourceOf(OTHER), "value");
  assert.equal(sourceOf({ name: "x", type: "string" }), "value", "no source is a value");
  assert.equal(sourceOf({ name: "x", type: "artifact" }), "artifact", "the old type artifact is the artifact");
  assert.equal(partOf({ name: "x", type: "artifact" }), "title_body");
  assert.equal(partOf({ name: "x", source: "artifact", part: "comments" }), "comments");
});

test("the rows of a node: artifact inputs are fixed, value inputs are mapped, an old line for an artifact input is stale", () => {
  const rows = mappingRows([EPIC, OTHER], "epic = ${card.text}\nrepository = /srv/repo\nold = x");
  assert.deepEqual(rows.artifact.map((r) => [r.name, r.part]), [["epic", "title_body"]]);
  assert.deepEqual(rows.value.map((r) => [r.name, r.value]), [["repository", "/srv/repo"]]);
  assert.deepEqual(rows.stale.map((r) => r.name), ["epic"], "ignored by a run, shown so it can be removed");
  assert.deepEqual(rows.undeclared.map((r) => r.name), ["old"]);
});

test("a mapping is written without empty entries and a value stays one line", () => {
  assert.equal(formatMapping({ epic: "", repository: " /srv/repo\nmore " }), "repository = /srv/repo more");
  assert.deepEqual(parseMapping("repository = ${card.title}"), { repository: "${card.title}" });
});

test("the quick test of a value input has an example of its type and never the old epic example", () => {
  assert.equal(sampleHint({ name: "n", type: "number" }), "e.g. 3");
  assert.equal(sampleHint({ name: "n", type: "string", default: "x" }), "e.g. x");
});
