/* The pure part of the combobox (components/combobox-model.js): which options a typed text leaves and where the
 * arrow keys move the highlight. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { filterOptions, moveHighlight } from "../../openartifact/static/js/components/combobox-model.js";

const OPTIONS = [
  { value: "1", label: "Round guard", description: "On entered · Rounds of the scope is at least 5" },
  { value: "2", label: "Health agent", description: "Every 1 minute · Time without progress" },
  { value: "3", label: "Health guard", description: "On entered" },
  { value: "4", label: "Stall guard", description: "A watch on the health of a long run" },
  { value: "5", label: "Runtime guard", description: "Every 1 minute" },
];

test("an empty query leaves every option, by name", () => {
  assert.deepEqual(filterOptions(OPTIONS, "  ").map((o) => o.label), ["Health agent", "Health guard", "Round guard", "Runtime guard", "Stall guard"]);
});

test("'hea' finds the Health guard and the Health agent, the names first, then a guard whose description says health", () => {
  assert.deepEqual(filterOptions(OPTIONS, "hea").map((o) => o.label), ["Health agent", "Health guard", "Stall guard"]);
});

test("the match ignores case and ranks a name that starts with it before a word inside the name and before the description", () => {
  const options = [
    { value: "a", label: "Late guard", description: "stall is in the text" },
    { value: "b", label: "A stall watch" },
    { value: "c", label: "Stall guard" },
    { value: "d", label: "Install guard" },
  ];
  assert.deepEqual(filterOptions(options, "STALL").map((o) => o.value), ["c", "b", "d", "a"]);
});

test("keywords are searched like the description and are not shown", () => {
  const options = [{ value: "a", label: "Alpha", description: "shown line", keywords: "A long run that stalls" }, { value: "b", label: "Beta" }];
  assert.deepEqual(filterOptions(options, "stalls").map((o) => o.value), ["a"]);
  assert.deepEqual(filterOptions(options, "shown").map((o) => o.value), ["a"]);
});

test("an option that holds the text nowhere is dropped, and nothing found is an empty list", () => {
  assert.deepEqual(filterOptions(OPTIONS, "zzz"), []);
  assert.deepEqual(filterOptions(OPTIONS, "runtime").map((o) => o.value), ["5"]);
});

test("the arrow keys move the highlight and wrap, Home and End go to the ends, from none Down lands on the first and Up on the last", () => {
  assert.equal(moveHighlight(-1, "ArrowDown", 3), 0);
  assert.equal(moveHighlight(-1, "ArrowUp", 3), 2);
  assert.equal(moveHighlight(2, "ArrowDown", 3), 0);
  assert.equal(moveHighlight(0, "ArrowUp", 3), 2);
  assert.equal(moveHighlight(1, "Home", 3), 0);
  assert.equal(moveHighlight(1, "End", 3), 2);
  assert.equal(moveHighlight(1, "x", 3), 1);
  assert.equal(moveHighlight(0, "ArrowDown", 0), -1);
});
