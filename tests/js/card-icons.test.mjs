import assert from "node:assert/strict";
import { test } from "node:test";

const { CARD_ORDER } = await import("../../openartifact/static/js/components/card-icons.js");
const { shownKeys } = await import("../../openartifact/static/js/components/icon-list-model.js");

const entries = (active) => [
  { key: "a", order: 5, visible: active.includes("a") },
  { key: "mock", order: CARD_ORDER.mock, visible: active.includes("mock") },
  { key: "b", order: 15, visible: active.includes("b") },
  { key: "guard", order: CARD_ORDER.guard, visible: active.includes("guard") },
];

test("on a node card the mock pin sits left of the shield of the guards, the shield stays the right-most", () => {
  assert.ok(CARD_ORDER.mock < CARD_ORDER.guard);
  assert.deepEqual(shownKeys(entries(["guard", "mock"])), ["mock", "guard"]);
  assert.deepEqual(shownKeys(entries(["guard"])), ["guard"], "only the shield: where it always was");
  assert.deepEqual(shownKeys(entries(["mock"])), ["mock"], "only the pin: at the right anchor");
});

test("the central rule of a flexible icon list: four places and only the second and the fourth active are next to each other, no placeholder", () => {
  assert.deepEqual(shownKeys(entries(["mock", "guard"])), ["mock", "guard"]);
  assert.deepEqual(shownKeys(entries(["a", "b"])), ["a", "b"]);
  assert.deepEqual(shownKeys(entries(["a", "mock", "b", "guard"])), ["a", "mock", "b", "guard"], "all four: in their fixed order");
  assert.deepEqual(shownKeys(entries([])), [], "none: no list at all");
});
