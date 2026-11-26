/* The card rules in the browser (ADR-071): what a rule makes of a card (tasks/card-marks.js) and the schema the rule builder
 * takes (tasks/card-rules-schema.js). No browser: a card is a small object with what the code touches. */
import assert from "node:assert/strict";
import { test } from "node:test";

const { applyMarks, marksOfRule, drawLabels } = await import("../../openartifact/static/js/tasks/card-marks.js");
const { buildSchema } = await import("../../openartifact/static/js/tasks/card-rules-schema.js");

function fakeCard() {
  const classes = new Set();
  const list = { hidden: true, children: [], replaceChildren(...items) { this.children = items; } };
  return {
    classes,
    list,
    dataset: {},
    classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) },
    querySelector: (selector) => (selector === ".task-card__labels" ? list : null),
  };
}

globalThis.document = { createElement: () => ({ dataset: {} }) };

test("each action gives the card its own look and nothing else", () => {
  assert.deepEqual(marksOfRule({ action: "set_done" }), { done: true, labels: [], colour: null });
  assert.deepEqual(marksOfRule({ action: "label", params: { text: "Old", tone: "red" } }).labels, [{ text: "Old", tone: "red" }]);
  assert.deepEqual(marksOfRule({ action: "colour", params: { tone: "green", mode: "border" } }).colour, { tone: "green", mode: "border" });
  assert.equal(marksOfRule({ action: "archive" }).archived, true);
  assert.equal(marksOfRule({ action: "delete" }).done, false, "a deleted card has no look: it is gone");
});

test("a label without text still shows something in the preview", () => {
  assert.equal(marksOfRule({ action: "label", params: {} }).labels[0].text, "…");
});

test("marks are drawn on the card and taken off again when they are gone", () => {
  const card = fakeCard();
  applyMarks(card, { done: true, labels: [{ text: "Old", tone: "red" }], colour: { tone: "green", mode: "fill" } });
  assert.ok(card.classes.has("task-card--done"));
  assert.equal(card.dataset.colourTone, "green");
  assert.equal(card.dataset.colourMode, "fill");
  assert.equal(card.list.hidden, false);
  assert.equal(card.list.children[0].textContent, "Old");
  assert.equal(card.list.children[0].dataset.tone, "red");
  applyMarks(card, { done: false, labels: [], colour: null });
  assert.ok(!card.classes.has("task-card--done"));
  assert.equal(card.dataset.colourTone, undefined);
  assert.equal(card.list.hidden, true);
  applyMarks(card, undefined); // a card the server sent without marks
  assert.equal(card.list.children.length, 0);
});

test("labels hide their list while there are none", () => {
  const list = { hidden: false, replaceChildren() {} };
  drawLabels(list, []);
  assert.equal(list.hidden, true);
});

const SERVER = {
  fields: [
    { key: "lane", kind: "text", operators: ["is", "is_not"], options: [], minimum: null, prefix: null, units: [] },
    { key: "in_lane", kind: "duration", operators: ["at_least", "below"], options: [], minimum: 0, prefix: null, units: ["days", "hours", "minutes"] },
    { key: "has_parent", kind: "choice", operators: ["is"], options: ["yes", "no"], minimum: null, prefix: null, units: [] },
    { key: "field.", kind: "text", operators: ["is"], options: [], minimum: null, prefix: "field.", units: [] },
  ],
  consequences: [
    { key: "archive", available: true },
    { key: "delete", available: true },
    { key: "label", available: true },
    { key: "colour", available: true },
    { key: "planned", available: false },
  ],
};

test("the schema offers the available actions, with the settings of the ones that have some", () => {
  const schema = buildSchema(SERVER);
  assert.deepEqual(schema.actions.map((a) => a.key), ["archive", "delete", "label", "colour"], "an action that is not available is not offered");
  const byKey = Object.fromEntries(schema.actions.map((a) => [a.key, a]));
  assert.equal(byKey.delete.startsOff, true, "a rule that deletes starts switched off");
  assert.equal(byKey.archive.startsOff, false);
  assert.deepEqual(byKey.label.defaults, { text: "", tone: "blue" });
  assert.deepEqual(byKey.label.params.map((p) => p.key), ["text", "tone"]);
  assert.deepEqual(byKey.colour.params.map((p) => p.key), ["tone", "mode"]);
  assert.equal(byKey.archive.params, undefined);
});

test("the choice Always / Only when is there for card rules only, and a rule that deletes cannot be always", () => {
  assert.equal(buildSchema(SERVER).always, undefined, "no scope, no choice (the retention rules and guards keep their meaning)");
  assert.ok(buildSchema(SERVER, { scope: "lane" }).always.label.length > 0);
  assert.notEqual(buildSchema(SERVER, { scope: "lane" }).always.label, buildSchema(SERVER, { scope: "board" }).always.label, "each place names its cards");
  const byKey = Object.fromEntries(buildSchema(SERVER, { scope: "board" }).actions.map((a) => [a.key, a]));
  assert.equal(byKey.delete.needsCondition, true);
  assert.equal(byKey.archive.needsCondition, false);
});

test("the board's lanes are the choices of the field Lane", () => {
  const schema = buildSchema(SERVER, { lanes: [{ status: "backlog", title: "Optional" }, { status: "done_2", title: "Done" }] });
  const lane = schema.fields.find((f) => f.key === "lane");
  assert.equal(lane.kind, "choice");
  assert.deepEqual(lane.options, [{ value: "backlog", label: "Optional" }, { value: "done_2", label: "Done" }]);
});

test("a duration starts at a week, a field with a prefix asks for a name", () => {
  const schema = buildSchema(SERVER);
  assert.equal(schema.fields.find((f) => f.key === "in_lane").default, 604800);
  const custom = schema.fields.find((f) => f.key === "field.");
  assert.equal(custom.prefix, "field.");
  assert.ok(custom.placeholder);
});
