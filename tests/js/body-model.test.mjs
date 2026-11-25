/* The body as it is read: filled in or as written, the board's preview, the notes of a save (tasks/body-model.js). */
import assert from "node:assert/strict";
import { test } from "node:test";

import { bodyText, cardPreview, hasResolved, needsFullBody, rememberWarnings, warningsFor } from "../../openartifact/static/js/tasks/body-model.js";

const WRITTEN = "Elias: ${card.test}";

test("the read view shows the filled in text", () => {
  const task = { body: WRITTEN, body_resolved: "Elias: Als er erwachte" };
  assert.equal(bodyText(task), "Elias: Als er erwachte");
  assert.ok(hasResolved(task));
});

test("a body with nothing to fill in is shown as it is and has no marker", () => {
  const task = { body: "plain", body_resolved: null };
  assert.equal(bodyText(task), "plain");
  assert.equal(hasResolved(task), false);
  assert.equal(bodyText({ body: null }), "");
});

test("an empty filled in text is still filled in (a reference to an empty field)", () => {
  const task = { body: "[${card.test}]", body_resolved: "[]" };
  assert.equal(hasResolved(task), true);
  assert.equal(bodyText(task), "[]");
});

test("a card on the board shows the preview of the server, else the original", () => {
  assert.equal(cardPreview({ body: WRITTEN, preview: "Elias: Als er…" }), "Elias: Als er…");
  assert.equal(cardPreview({ body: "plain", preview: null }), "plain");
  assert.equal(cardPreview({ body: null }), "");
});

test("only a listed body with references still needs the single read for its full text", () => {
  assert.equal(needsFullBody({ preview: "x", body_resolved: null }), true); // the list: preview set, text not carried
  assert.equal(needsFullBody({ preview: "x", body_resolved: undefined }), true);
  assert.equal(needsFullBody({ preview: "x", body_resolved: "full" }), false);
  assert.equal(needsFullBody({ preview: null }), false);
  assert.equal(needsFullBody({ preview: null, body_resolved: null }), false); // no reference at all
});

test("the notes of a save belong to the artifact that was saved and are not part of it", () => {
  const { artifact, warned } = rememberWarnings({ id: "a", title: "T", warnings: ["${card.nope}: the artifact has no field 'nope'"] });
  assert.deepEqual(artifact, { id: "a", title: "T" });
  assert.deepEqual(warningsFor(warned, { id: "a" }), ["${card.nope}: the artifact has no field 'nope'"]);
  assert.deepEqual(warningsFor(warned, { id: "b" }), []);
  assert.deepEqual(warningsFor(null, { id: "a" }), []);
  assert.deepEqual(rememberWarnings({ id: "c" }).warned, { id: "c", warnings: [] });
});
