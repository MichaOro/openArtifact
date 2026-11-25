/* Where a pipeline or an action stands between its draft and its published versions (static/js/editor/versions-model.js, ADR-070). */
import assert from "node:assert/strict";
import { test } from "node:test";

const { canPublish, publicationOf } = await import("../../openartifact/static/js/editor/versions-model.js");

test("a definition nobody published is a draft that can be published", () => {
  assert.deepEqual(publicationOf({ published_version: null, draft_changed: false }), { state: "draft", number: null });
  assert.deepEqual(publicationOf({}), { state: "draft", number: null }, "an answer without the fields is a draft too");
  assert.equal(canPublish({ published_version: null }), true);
});

test("a published definition is published while the draft equals it and has changes once the draft differs", () => {
  assert.deepEqual(publicationOf({ published_version: 3, draft_changed: false }), { state: "published", number: 3 });
  assert.deepEqual(publicationOf({ published_version: 3, draft_changed: true }), { state: "changed", number: 3 });
});

test("publishing is offered unless the draft equals the published version", () => {
  assert.equal(canPublish({ published_version: 3, draft_changed: false }), false);
  assert.equal(canPublish({ published_version: 3, draft_changed: true }), true);
});
