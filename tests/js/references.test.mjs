import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { FakeNode, installDocument, textOf, uninstallDocument } from "./support.mjs";

const { renderReferences, renderResolvedBody } = await import("../../openartifact/static/js/tasks/references.js");

beforeEach(() => installDocument());
afterEach(() => uninstallDocument());

const known = new Map([[12, { title: "Fix login" }], [7, { title: "Docs" }]]);
const find = (n) => known.get(n);
const parts = (text) => renderReferences(text, find).children;

test("plain text stays one piece", () => {
  assert.deepEqual(parts("nothing here"), ["nothing here"]);
});

test("a known number becomes a link carrying the title; an unknown one a marked span", () => {
  const [before, link, between, missing, after] = parts("see #12 and #99.");
  assert.equal(before, "see ");
  assert.equal(link.tagName, "a");
  assert.equal(link.className, "ref");
  assert.equal(link.textContent, "#12");
  assert.equal(link.href, "#12");
  assert.equal(link.dataset.number, "12");
  assert.equal(link.title, "Fix login");
  assert.equal(between, " and ");
  assert.equal(missing.tagName, "span");
  assert.equal(missing.className, "ref ref--missing");
  assert.equal(missing.title, "No artifact #99");
  assert.equal(missing.href, undefined);
  assert.equal(after, ".");
});

test("a reference at the very start and one right after punctuation or a newline count", () => {
  assert.equal(textOf(renderReferences("#7 (#12)\n#7", find)), "#7 (#12)\n#7");
  assert.equal(parts("#7").filter((p) => p instanceof FakeNode).length, 1);
  assert.equal(parts("(#7)").filter((p) => p instanceof FakeNode).length, 1);
  assert.equal(parts("a\n#7").filter((p) => p instanceof FakeNode).length, 1);
});

test("a number glued to a word, a hash or an entity is not a reference", () => {
  for (const text of ["issue#12", "##12", "&#12;", "a#12", "x_#12"]) {
    assert.equal(parts(text).filter((p) => p instanceof FakeNode).length, 0, text);
  }
});

test("only 1 to 9 digits and a word boundary", () => {
  assert.equal(parts("#1234567890").filter((p) => p instanceof FakeNode).length, 0, "ten digits");
  assert.equal(parts("#123456789").filter((p) => p instanceof FakeNode).length, 1, "nine digits");
  assert.equal(parts("#12abc").filter((p) => p instanceof FakeNode).length, 0, "no boundary after the digits");
  assert.equal(parts("#").filter((p) => p instanceof FakeNode).length, 0);
});

test("leading zeros resolve by value", () => {
  const [, link] = parts("see #012");
  assert.equal(link.tagName, "a");
  assert.equal(link.textContent, "#12");
});

test("adjacent references keep the text between them and the original is never mutated", () => {
  const text = "#7 #12";
  assert.equal(textOf(renderReferences(text, find)), "#7 #12");
  assert.equal(text, "#7 #12");
});

test("markup in the text is kept as text, never as elements", () => {
  const out = renderReferences("<img src=x onerror=alert(1)> #7", find);
  assert.equal(out.children[0], "<img src=x onerror=alert(1)> ");
  assert.equal(out.children.filter((p) => p instanceof FakeNode).length, 1);
});

test("resolved text is marked and written text is not; a #n inside either is still a link", () => {
  const segments = [
    { text: "The word is ", resolved: false },
    { text: "see #12", resolved: true },
    { text: " and #7.", resolved: false },
  ];
  const [written, marked, after] = renderResolvedBody(segments, find).children;
  assert.deepEqual(written.children, ["The word is "]);
  assert.equal(marked.tagName, "mark");
  assert.equal(marked.className, "resolved-ref");
  const [inside] = marked.children[0].children;
  assert.equal(inside, "see ");
  assert.equal(marked.children[0].children[1].tagName, "a", "a reference inside the marked text is a link");
  assert.equal(after.children[1].tagName, "a");
  assert.equal(textOf(renderResolvedBody(segments, find)), "The word is see #12 and #7.", "the text is the same, only marked");
});
