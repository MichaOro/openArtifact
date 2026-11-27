import assert from "node:assert/strict";
import { test } from "node:test";

const { skippedWhat, cornerMarks } = await import("../../openartifact/static/js/components/skip-marker-model.js");
const { CARD_ORDER } = await import("../../openartifact/static/js/components/card-icons.js");
const { shownKeys } = await import("../../openartifact/static/js/components/icon-list-model.js");

const skipped = { data: { dry_run: true, would_have: "waited 3 s" } };

test("a skipped step says what it would have done; a step that ran, a mocked step and one that was not observable say nothing", () => {
  assert.equal(skippedWhat(skipped), "waited 3 s");
  assert.equal(skippedWhat({ data: { would_have: "waited 3 s" } }), null, "without dry_run it is no skipped step");
  assert.equal(skippedWhat({ data: { dry_run: true, mock: true, would_have: "x" } }), null, "a mocked node was processed, not skipped");
  assert.equal(skippedWhat({ data: { dry_run: true, not_observable: true, would_have: "x" } }), null);
  assert.equal(skippedWhat({ data: { dry_run: true, would_have: "  " } }), null);
  assert.equal(skippedWhat({ data: null }), null);
  assert.equal(skippedWhat(null), null);
});

test("the skip marker and the mock pin never meet on a node", () => {
  assert.deepEqual(cornerMarks(skipped), [{ key: "skipped", what: "waited 3 s" }]);
  assert.deepEqual(cornerMarks(skipped, { mocked: true }), [{ key: "mock" }], "the pin wins, never both");
  assert.deepEqual(cornerMarks({ data: { dry_run: true, mock: true } }), []);
});

test("on a card the skip marker sits left of the pin and the shield; the shield stays the right-most, nothing is left open", () => {
  assert.ok(CARD_ORDER.skipped < CARD_ORDER.mock && CARD_ORDER.mock < CARD_ORDER.guard);
  const entries = (active) => Object.entries(CARD_ORDER).map(([key, order]) => ({ key, order, visible: active.includes(key) }));
  assert.deepEqual(shownKeys(entries(["skipped", "guard"])), ["skipped", "guard"], "no placeholder for the pin that is not there");
  assert.deepEqual(shownKeys(entries(["skipped"])), ["skipped"]);
  assert.deepEqual(shownKeys(entries(["mock", "guard"])), ["mock", "guard"]);
});
