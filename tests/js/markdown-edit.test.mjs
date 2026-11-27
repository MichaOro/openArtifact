import assert from "node:assert/strict";
import { test } from "node:test";

const { cycleHeading, findLink, headingLevel, linkEdit, normalizeAddress, toggleCodeBlock, toggleList, toggleOrdered, toggleQuote, toggleWrap } = await import("../../openartifact/static/js/components/markdown-edit.js");

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

// ── the buttons of the wider bar ─────────────────────────────────────────────────────────────────────────────

const ordered = (text, start, end) => apply(text, toggleOrdered(text, start, end));
const quote = (text, start, end) => apply(text, toggleQuote(text, start, end));
const heading = (text, start, end) => apply(text, cycleHeading(text, start, end));
const block = (text, start, end) => apply(text, toggleCodeBlock(text, start, end));

test("inline code is a wrap with a backtick: on, off, and at the caret", () => {
  assert.equal(wrap("run npm test now", 4, 12, "`").value, "run `npm test` now");
  assert.equal(wrap("run `npm test` now", 5, 13, "`").value, "run npm test now");
  assert.equal(wrap("ab", 1, 1, "`").caret, 2);
});

test("the numbered list counts the filled in lines, skips empty ones, and is taken back when every line is numbered", () => {
  assert.equal(ordered("one\ntwo\n\nfour", 0, 13).value, "1. one\n2. two\n\n3. four");
  assert.equal(ordered("1. one\n2. two", 0, 13).value, "one\ntwo");
  assert.equal(ordered("- one\n- two", 0, 11).value, "1. one\n2. two", "a bulleted list becomes a numbered one");
  assert.equal(list("1. one\n2. two", 0, 13).value, "- one\n- two", "and the other way round");
});

test("a quote goes before every line, blank lines carry a bare '>', and it comes off when every line is quoted", () => {
  assert.equal(quote("one\ntwo", 0, 7).value, "> one\n> two");
  assert.equal(quote("one\n\ntwo", 0, 8).value, "> one\n>\n> two");
  assert.equal(quote("> one\n> two", 0, 11).value, "one\ntwo");
  assert.equal(quote("> one\ntwo", 0, 9).value, "> one\n> two", "a mixed selection is quoted in full");
  assert.equal(quote("", 0, 0).value, "> ");
});

test("the heading button goes none, #, ##, ### and none again, on every line of the selection, and keeps the words", () => {
  assert.equal(heading("Title", 2, 2).value, "# Title");
  assert.equal(heading("# Title", 3, 3).value, "## Title");
  assert.equal(heading("## Title", 3, 3).value, "### Title");
  assert.equal(heading("### Title", 3, 3).value, "Title");
  assert.equal(heading("#### Title", 3, 3).value, "Title", "a deeper heading is taken to none");
  assert.equal(heading("a\nb", 0, 3).value, "# a\n# b");
  assert.equal(headingLevel("## x", 1), 2);
  assert.equal(headingLevel("#117 x", 1), 0, "#117 is no heading");
  assert.equal(heading("#117 x", 2, 2).value, "# #117 x");
});

test("a code block puts a fence above and below the lines, and takes it away again", () => {
  const added = block("a\nb", 0, 3);
  assert.equal(added.value, "```\na\nb\n```");
  assert.equal(added.selected, "a\nb");
  assert.equal(block("```\na\nb\n```", 0, 12).value, "a\nb", "the selection holds the fence");
  assert.equal(block("```\na\nb\n```", 4, 7).value, "a\nb", "the caret is inside the fence");
  assert.equal(block("x\n```js\ncode\n```\ny", 8, 8).value, "x\ncode\ny", "a fence with a language");
  const empty = block("", 0, 0);
  assert.equal(empty.value, "```\n\n```");
  assert.equal(empty.caret, 4);
});

test("the link the caret is in is found, with its words and its address; none is found outside", () => {
  const text = "see [the site](https://x.test/a) now\nsecond [b](https://y.test)";
  assert.deepEqual(findLink(text, 10), { from: 4, to: 32, label: "the site", address: "https://x.test/a" });
  assert.equal(findLink(text, 4).label, "the site", "at its first character");
  assert.equal(findLink(text, 33), null);
  assert.equal(findLink(text, 0), null);
  assert.equal(findLink(text, 45).label, "b", "on the second line");
});

test("an address is made usable: https for a bare host, mailto for an e-mail, only http, https and mailto pass", () => {
  assert.deepEqual(normalizeAddress("https://x.test/a"), { href: "https://x.test/a" });
  assert.deepEqual(normalizeAddress("  www.x.test  "), { href: "https://www.x.test" });
  assert.deepEqual(normalizeAddress("x.test/path?q=1"), { href: "https://x.test/path?q=1" });
  assert.deepEqual(normalizeAddress("me@x.test"), { href: "mailto:me@x.test" });
  assert.deepEqual(normalizeAddress("mailto:me@x.test"), { href: "mailto:me@x.test" });
  assert.deepEqual(normalizeAddress(""), { error: "empty" });
  assert.deepEqual(normalizeAddress("   "), { error: "empty" });
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "ftp://x.test", "nonsense", "https://", "a b c", 'https://x.test/"']) {
    assert.deepEqual(normalizeAddress(bad), { error: "invalid" }, bad);
  }
});

test("a link is written as [words](address) in place of the selection; the caret ends after it", () => {
  const text = "go to the site now";
  const edit = linkEdit(text, 6, 14, "the site", "https://x.test");
  const result = apply(text, edit);
  assert.equal(result.value, "go to [the site](https://x.test) now");
  assert.equal(result.caret, "go to [the site](https://x.test)".length);
});

test("an empty word shows the address; brackets and line breaks in the words cannot break the link; a link under the caret is replaced", () => {
  assert.equal(apply("", linkEdit("", 0, 0, "", "https://x.test")).value, "[https://x.test](https://x.test)");
  assert.equal(apply("", linkEdit("", 0, 0, "a [b]\nc", "https://x.test")).value, "[a (b) c](https://x.test)");
  const text = "see [old](https://old.test) here";
  const existing = findLink(text, 6);
  assert.equal(apply(text, linkEdit(text, 6, 6, "new", "https://new.test", existing)).value, "see [new](https://new.test) here");
});
