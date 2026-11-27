import assert from "node:assert/strict";
import test from "node:test";

import { findingItems, findingsConfirm } from "../../openartifact/static/js/editor/findings.js";

const FOUND = [
  { level: "warning", node_name: "B", message: "maybe" },
  { level: "error", node_name: "Z", message: "late" },
  { level: "error", node_name: "A", message: "broken" },
];

test("the findings come errors first and then by the name of the node", () => {
  assert.deepEqual(findingItems(FOUND).map((i) => `${i.mark} ${i.label}`), ["Error A", "Error Z", "Warning B"]);
});

test("a publish over errors is asked in red and says how many of each", () => {
  const options = findingsConfirm(FOUND);
  assert.equal(options.tone, "danger");
  assert.match(options.message, /^The check found 2 error\(s\) and 1 warning\(s\) in the draft\./);
  assert.equal(options.confirmLabel, "Publish anyway");
  assert.equal(options.title, "Publish with findings?");
});

test("a publish over warnings only is asked in the accent colour", () => {
  assert.equal(findingsConfirm([FOUND[0]]).tone, "primary");
});
