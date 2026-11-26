/* The pure parts of the archive view (static/js/tasks/archive-model.js): the orders, the search text, the rows of the Context tab. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { SORTS, contextRows, fieldText, searchText } from "../../openartifact/static/js/tasks/archive-model.js";
import { sentenceOf } from "../../openartifact/static/js/tasks/activity-model.js";

const card = (number, title, archivedAt) => ({ number, title, archived_at: archivedAt });
const order = (key, cards) => [...cards].sort(SORTS.find((s) => s.key === key).compare).map((c) => c.title);
const CARDS = [card(1, "Beta", "2026-01-02T00:00:00Z"), card(2, "alpha", "2026-01-03T00:00:00Z"), card(3, "Gamma", "2026-01-01T00:00:00Z")];

test("the archive is ordered by the time of entry, newest first, and can be turned around or sorted by title", () => {
  assert.deepEqual(SORTS.map((s) => s.key), ["archived", "archived_asc", "title", "title_desc"]);
  assert.deepEqual(order("archived", CARDS), ["alpha", "Beta", "Gamma"]);
  assert.deepEqual(order("archived_asc", CARDS), ["Gamma", "Beta", "alpha"]);
  assert.deepEqual(order("title", CARDS), ["alpha", "Beta", "Gamma"]);
  assert.deepEqual(order("title_desc", CARDS), ["Gamma", "Beta", "alpha"]);
});

test("cards that came in at the same time keep their number order", () => {
  const same = [card(5, "b", "2026-01-01T00:00:00Z"), card(4, "a", "2026-01-01T00:00:00Z")];
  assert.deepEqual(order("archived", same).map((x) => x), ["a", "b"]);
});

test("the search reads number, title and the first words of the text", () => {
  assert.equal(searchText({ number: 7, title: "Moon", preview: "first words", body: "ignored" }), "#7 Moon first words");
  assert.equal(searchText({ number: 7, title: "Moon", body: "body text" }), "#7 Moon body text");
});

test("a field value is said in words; nothing is null", () => {
  assert.equal(fieldText(""), null);
  assert.equal(fieldText(null), null);
  assert.equal(fieldText(3), "3");
  assert.equal(fieldText(true), "Yes");
  assert.equal(fieldText(false), "No");
});

test("the context is the lane it came from, the parent and the fields that are set; never pipeline, stage or action", () => {
  const task = { archived_from_lane: "Backlog", parent_id: "p1", fields: { secret: "bye", empty: "", other: 2 }, pipeline_id: "x", stage_id: "y", action_id: "z" };
  const rows = contextRows(task, [{ name: "secret", label: "Secret" }], "Mother");
  assert.deepEqual(rows, [
    { label: "Lane", value: "Backlog" },
    { label: "Parent", value: "Mother" },
    { label: "Secret", value: "bye" },
    { label: "other", value: "2" },
  ]);
});

test("a lane that is gone and a parent that is not on the board are said so", () => {
  const rows = contextRows({ archived_from_lane: null, parent_id: "p1", fields: {} }, [], null);
  assert.deepEqual(rows.map((r) => r.value), ["(lane no longer exists)", "(not on the board)"]);
  assert.equal(contextRows({ archived_from_lane: "A", parent_id: null, fields: {} }, [], null).length, 1);
});

test("the history says archived and unarchived", () => {
  assert.equal(sentenceOf({ kind: "archived", data: {} }), "moved it to the archive");
  assert.equal(sentenceOf({ kind: "unarchived", data: { to: "MVP" } }), "took it out of the archive, back to MVP");
  assert.equal(sentenceOf({ kind: "unarchived", data: {} }), "took it out of the archive");
});
