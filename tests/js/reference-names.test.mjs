/* What a field shows of a reference (editor/reference-names.js, ADR-082 addendum 1): stored text has `${node:<uuid>.field}`, the user reads and
 * writes `${node:<name>.field}`; two pure conversions that never resolve anything. */
import assert from "node:assert/strict";
import { test } from "node:test";

const { ReferenceNames, labelsFor } = await import("../../openartifact/static/js/editor/reference-names.js");

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const C = "33333333-3333-4333-8333-333333333333";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

const nodes = [
  { id: A, name: "Fetch user" },
  { id: B, name: "Test", definition_name: "Test: Code und HTTP", placement_number: 4 },
];
const names = () => new ReferenceNames(() => nodes);

test("an id is shown as the name of its node, a placement with its number, and no uuid is left in the text", () => {
  const shown = names().display(`a \${node:${A}.data.id} and \${node:${B}.success}`);
  assert.equal(shown, "a ${node:Fetch user.data.id} and ${node:Test: Code und HTTP #4.success}");
  assert.doesNotMatch(shown, UUID);
});

test("the way back gives the stored text again (a round trip), also for a reference that is still being typed", () => {
  const stored = `x \${node:${A}.output} y \${node:${B}.data.greeting}`;
  const converter = names();
  assert.equal(converter.stored(converter.display(stored)), stored);
  assert.equal(converter.display(`\${node:${A}.`), "${node:Fetch user.");
  assert.equal(converter.stored("${node:Fetch user."), `\${node:${A}.`);
});

test("a rename changes what is shown and not what is stored", () => {
  const stored = `\${node:${A}.output}`;
  const renamed = [{ id: A, name: "Download" }, nodes[1]];
  const converter = new ReferenceNames(() => renamed);
  assert.equal(converter.display(stored), "${node:Download.output}");
  assert.equal(converter.stored("${node:Download.output}"), stored);
});

test("names that two nodes share are told apart by (1) and (2); the bare shared name names neither and stays as typed", () => {
  const twice = [{ id: A, name: "Same" }, { id: B, name: "Same" }];
  assert.deepEqual([...labelsFor(twice).values()], ["Same (1)", "Same (2)"]);
  const converter = new ReferenceNames(() => twice);
  assert.equal(converter.display(`\${node:${B}.output}`), "${node:Same (2).output}");
  assert.equal(converter.stored("${node:Same (2).output}"), `\${node:${B}.output}`);
  assert.equal(converter.stored("${node:Same.output}"), "${node:Same.output}", "ambiguous: left alone, the check before publishing reports it");
});

test("an id that no node has any more is shown as (deleted node) and is NOT destroyed by a save", () => {
  const converter = names();
  const shown = converter.display(`\${node:${C}.output} then \${node:${A}.output}`);
  assert.equal(shown, "${node:(deleted node).output} then ${node:Fetch user.output}");
  assert.equal(converter.stored(shown), `\${node:${C}.output} then \${node:${A}.output}`, "the deleted node's own id goes back");
  const D = "44444444-4444-4444-8444-444444444444";
  const two = converter.display(`\${node:${C}.x} \${node:${D}.y}`);
  assert.equal(two, "${node:(deleted node).x} ${node:(deleted node 2).y}");
  assert.equal(converter.stored(two), `\${node:${C}.x} \${node:${D}.y}`);
});

test("a readable form that names no node is left as written, the old name form and other references are not touched", () => {
  const converter = names();
  assert.equal(converter.stored("${node:Nobody.output}"), "${node:Nobody.output}");
  const plain = "${(Fetch user).output} ${card.title} ${var.x} ${secret:KEY} and text";
  assert.equal(converter.display(plain), plain);
  assert.equal(converter.stored(plain), plain);
  assert.equal(converter.stored(`\${node:${A}.output}`), `\${node:${A}.output}`, "an id already: nothing to do");
});

test("the longest name wins when one name begins with another, and a character that would end a reference is cleaned", () => {
  const several = [{ id: A, name: "A" }, { id: B, name: "A.B" }, { id: C, name: "Odd} name" }];
  const converter = new ReferenceNames(() => several);
  assert.equal(converter.stored("${node:A.B.output}"), `\${node:${B}.output}`);
  assert.equal(converter.stored("${node:A.output}"), `\${node:${A}.output}`);
  assert.equal(converter.display(`\${node:${C}.output}`), "${node:Odd name.output}");
});
