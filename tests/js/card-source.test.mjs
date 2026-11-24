/* The card as a source of the run in the editor (ADR-064): the built-in references first in the picker, the pre-fill of an
 * artifact input of an agent (once, never again after the user cleared it), and the pure parts of the resolved preview. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { candidatesFor, suggestionsFor } from "../../openartifact/static/js/editor/reference-completion.js";
import { ARTIFACT_PREFILL, formatMapping, mappingRows, parseMapping, prefillMapping, sampleHint } from "../../openartifact/static/js/agents/model.js";
import { cardFromLocation, cardOptions, needsPreview, previewLines } from "../../openartifact/static/js/editor/reference-preview-model.js";

const EPIC = { name: "epic", type: "artifact", required: true };
const OTHER = { name: "repository", type: "string", required: false };

test("the card of this run is the first group and offers what every artifact has, then its own fields", () => {
  const all = candidatesFor([], { cardFields: [{ name: "test", label: "Test" }] });
  const groups = suggestionsFor(all, "");
  assert.deepEqual(groups.map((g) => g.insert), ["card."]);
  assert.equal(groups[0].icon, "card");
  assert.deepEqual(suggestionsFor(all, "card.").map((c) => c.insert), ["card.title", "card.body", "card.text", "card.number", "card.id", "card.test"]);
  assert.deepEqual(suggestionsFor(all, "card.te").map((c) => c.insert), ["card.text", "card.test"]);
});

test("an artifact input is filled with the card text once, and an entry of the user is never replaced", () => {
  assert.equal(ARTIFACT_PREFILL, "${card.text}");
  assert.equal(prefillMapping([EPIC, OTHER], ""), "epic = ${card.text}");
  assert.equal(prefillMapping([EPIC, OTHER], "repository = /srv/repo"), "repository = /srv/repo\nepic = ${card.text}");
  assert.equal(prefillMapping([EPIC], "epic = ${card.body}"), null, "an entry the user changed stays");
  assert.equal(prefillMapping([OTHER], ""), null, "only an artifact input is filled");
});

test("no second copy of the card: nothing is pre-filled when another input already holds a card reference", () => {
  assert.equal(prefillMapping([EPIC, OTHER], "repository = ${card.body}"), null);
  assert.equal(prefillMapping([EPIC, OTHER], "repository = Epic: ${card.title}"), null);
  assert.equal(prefillMapping([EPIC, OTHER], "repository = ${var.x}"), "repository = ${var.x}\nepic = ${card.text}");
});

test("an artifact input the user cleared stays an entry, so it is not filled in again", () => {
  const cleared = formatMapping({ epic: "", repository: "" }, ["epic"]);
  assert.equal(cleared, "epic =");
  assert.deepEqual(parseMapping(cleared), { epic: "" });
  assert.equal(prefillMapping([EPIC, OTHER], cleared), null);
  assert.equal(formatMapping({ epic: "", repository: "" }), "", "without keep, empty entries are left out as before");
});

test("a mapped name the agent no longer declares is a row of its own, so it can be seen and removed", () => {
  const rows = mappingRows([EPIC], "epic = ${card.text}\nold = ${card.body}");
  assert.deepEqual(rows.map((r) => [r.name, r.declared]), [["epic", true], ["old", false]]);
});

test("the quick test of an artifact input has an example", () => {
  assert.match(sampleHint(EPIC), /#1 Example epic/);
});

test("a field previews only with a chosen card and a reference in its text", () => {
  assert.equal(needsPreview("Epic: ${card.title}", "98"), true);
  assert.equal(needsPreview("Epic: ${card.title}", null), false);
  assert.equal(needsPreview("plain text", "98"), false);
  assert.equal(needsPreview("${", "98"), false);
});

test("the card of the address and the choice of cards", () => {
  assert.equal(cardFromLocation("?card=98"), "98");
  assert.equal(cardFromLocation("?card=x%3Cscript"), null, "anything else than a number or an id is ignored");
  assert.equal(cardFromLocation(""), null);
  const options = cardOptions([{ number: 2, title: "Two", status: "backlog" }, { number: 98, title: "Epic", status: "done" }]);
  assert.deepEqual(options.map((o) => [o.value, o.label]), [["98", "#98 Epic"], ["2", "#2 Two"]]);
});

test("the preview shows the resolved text and says what could not be resolved", () => {
  assert.deepEqual(previewLines({ resolved: "A", unresolved: [] }, (n) => `no ${n}`), ["A"]);
  assert.deepEqual(previewLines({ resolved: "A", unresolved: ["card.x", "card.y"] }, (n) => `no ${n}`), ["A", "no card.x, card.y"]);
  assert.deepEqual(previewLines(null, () => ""), []);
});
