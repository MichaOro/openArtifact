/* The pure part of the board search (static/js/tasks/board-search-model.js): title and number only. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { fold, matches, parseQuery, tally } from "../../openartifact/static/js/tasks/board-search-model.js";

const card = (number, title) => ({ number, title });
const CARDS = [card(3, "Zusammenfassung der Woche"), card(154, "Zusammenfassung"), card(15, "Summary of week 3"), card(7, "Überblick"), card(30, "Release 154 vorbereiten")];
const keep = (query) => CARDS.filter((c) => matches(c, parseQuery(query))).map((c) => c.number);

test("an empty or blank query keeps everything", () => {
  assert.deepEqual(parseQuery(""), { kind: "all" });
  assert.deepEqual(parseQuery("   "), { kind: "all" });
  assert.deepEqual(keep(""), [3, 154, 15, 7, 30]);
});

test("a word is looked for in the title, case ignored, and all words must be there", () => {
  assert.deepEqual(keep("zusammen"), [3, 154]);
  assert.deepEqual(keep("ZUSAMMENFASSUNG woche"), [3]);
  assert.deepEqual(keep("woche zusammen"), [3], "the order of the words does not matter");
  assert.deepEqual(keep("nothing"), []);
});

test("#154 finds the number only, 154 finds the number and titles that contain it", () => {
  assert.deepEqual(parseQuery("#154"), { kind: "number", number: 154 });
  assert.deepEqual(keep("#154"), [154]);
  assert.deepEqual(keep("154"), [154, 30], "the card 154 and the title 'Release 154 vorbereiten'");
  assert.deepEqual(keep("#3"), [3], "a number is exact: not 30, not 154");
  assert.deepEqual(keep("3"), [3, 15], "number 3 and 'week 3' (the title text), not the number 30");
});

test("umlauts and accents are folded both ways", () => {
  assert.equal(fold("Überblick"), "ueberblick");
  assert.equal(fold("Straße"), "strasse");
  assert.equal(fold("Café"), "cafe");
  assert.deepEqual(keep("ueber"), [7], "ue finds ü");
  assert.deepEqual(keep("Über"), [7], "ü finds ü");
});

test("the body is not part of what is compared, so it cannot be found", () => {
  const withBody = { number: 9, title: "Plain", body: "Zusammenfassung in the text" };
  assert.equal(matches(withBody, parseQuery("zusammen")), false);
});

test("tally counts what stays and what there is", () => {
  assert.deepEqual(tally(CARDS, parseQuery("zusammen")), { shown: 2, total: 5 });
  assert.deepEqual(tally(CARDS, parseQuery("")), { shown: 5, total: 5 });
});
