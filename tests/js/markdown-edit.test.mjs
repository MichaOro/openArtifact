import assert from "node:assert/strict";
import { test } from "node:test";

const { toggleList, toggleWrap } = await import("../../openartifact/static/js/components/markdown-edit.js");

/** Apply an edit to a text the way the textarea does, and say what is selected after it. */
function apply(text, edit) {
  const value = text.slice(0, edit.from) + edit.insert + text.slice(edit.to);
  return { value, selected: value.slice(edit.selStart, edit.selEnd), caret: edit.selStart === edit.selEnd ? edit.selStart : null };
}
const wrap = (text, start, end, marker) => apply(text, toggleWrap(text, start, end, marker));
const list = (text, start, end) => apply(text, toggleList(text, start, end));

test("a selection gets the marker on both sides and stays selected", () => {
  assert.deepEqual(wrap("make this bold", 5, 9, "**"), { value: "make **this** bold", selected: "this", caret: null });
  assert.equal(wrap("make this italic", 5, 9, "*").value, "make *this* italic");
  assert.equal(wrap("make this gone", 5, 9, "~~").value, "make ~~this~~ gone");
});

test("nothing selected: the markers go in at the caret, and the caret ends between them", () => {
  const result = wrap("ab", 1, 1, "**");
  assert.equal(result.value, "a****b");
  assert.equal(result.caret, 3);
  assert.equal(wrap("", 0, 0, "*").caret, 1);
});

test("blanks at the ends of the selection stay outside the markers", () => {
  const result = wrap("a  word  b", 1, 9, "**");
  assert.equal(result.value, "a  **word**  b");
  assert.equal(result.selected, "word");
});

test("a selection of blanks only is like no selection: markers at the caret", () => {
  assert.equal(wrap("a   b", 1, 4, "**").value, "a****b", "the blanks are replaced by the markers");
});

test("a wrapped selection is unwrapped: the markers outside it, or taken along in it", () => {
  assert.equal(wrap("make **this** bold", 7, 11, "**").value, "make this bold", "markers outside");
  assert.equal(wrap("make **this** bold", 5, 13, "**").value, "make this bold", "markers inside the selection");
  assert.equal(wrap("make *this* it", 6, 10, "*").value, "make this it");
  assert.equal(wrap("make ~~this~~ x", 7, 11, "~~").value, "make this x");
});

test("bold is no italic: asking for italic on **bold** adds a star pair, and the other way round", () => {
  assert.equal(wrap("**this**", 2, 6, "*").value, "***this***");
  assert.equal(wrap("***this***", 3, 7, "**").value, "*this*", "bold taken from bold-italic");
  assert.equal(wrap("***this***", 3, 7, "*").value, "**this**", "italic taken from bold-italic");
});

test("two selected lines are wrapped as they are (the markers do not cross lines in the display, the bar does not care)", () => {
  assert.equal(wrap("one\ntwo", 0, 7, "**").value, "**one\ntwo**");
});

test("the list button puts '- ' before every non-empty line of the selection", () => {
  assert.equal(list("one\ntwo\n\nfour", 0, 13).value, "- one\n- two\n\n- four");
  assert.equal(list("one\ntwo", 0, 7).selected, "- one\n- two");
});

test("a list is taken back: every line an item, the bullets go", () => {
  assert.equal(list("- one\n- two", 0, 11).value, "one\ntwo");
  assert.equal(list("- one\n  - sub", 0, 13).value, "one\n  sub");
});

test("a mixed selection becomes a list in full (lines that are items stay)", () => {
  assert.equal(list("- one\ntwo", 0, 9).value, "- one\n- two");
});

test("one line: the caret anywhere in it; the caret moves with the bullet", () => {
  const added = list("hello", 3, 3);
  assert.equal(added.value, "- hello");
  assert.equal(added.caret, 5);
  const removed = list("- hello", 5, 5);
  assert.equal(removed.value, "hello");
  assert.equal(removed.caret, 3);
});

test("the caret on an empty line starts an item there", () => {
  const result = list("a\n\nb", 2, 2);
  assert.equal(result.value, "a\n- \nb");
  assert.equal(result.caret, 4);
});

test("a selection that ends at the start of a line leaves that line out", () => {
  assert.equal(list("one\ntwo\nthree", 0, 8).value, "- one\n- two\nthree");
});
