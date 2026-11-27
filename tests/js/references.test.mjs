import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { FakeNode, installDocument, textOf, uninstallDocument } from "./support.mjs";

const { renderBody, renderReferences, renderResolvedBody } = await import("../../openartifact/static/js/tasks/references.js");

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

/** A compact picture of a drawn tree: elements as tag(children) (a link as a:#12, a mark as mark(...)), text as it is. */
function drawn(node) {
  if (typeof node === "string") return node;
  const inner = node.children.map(drawn).filter((part) => part !== "").join("|"); // renderReferences ends with an empty piece
  if (node.tagName === "#fragment") return inner;
  return `${node.tagName}${node.tagName === "a" ? `:${node.textContent}` : `(${inner || node.textContent})`}`;
}

test("renderBody: Markdown with the references as links inside the formatting", () => {
  assert.equal(drawn(renderBody("a **see #12** b", find)), "p(a |strong(see |a:#12)| b)");
  assert.equal(drawn(renderBody("- #7 first\n- second", find)), "ul(li(a:#7| first)|li(second))");
});

test("renderBody: the filled in parts are marked inside the formatting, wherever the text is cut", () => {
  const segments = [
    { text: "a **bo", resolved: false },
    { text: "ld", resolved: true },
    { text: "** #12 end", resolved: false },
  ];
  assert.equal(drawn(renderBody("ignored when segments are given", find, { segments })), "p(a |strong(bo|mark(ld))| |a:#12| end)");
});

test("renderBody: the marks change nothing about the text that is read", () => {
  const segments = [{ text: "one *two* ", resolved: false }, { text: "three", resolved: true }, { text: "\n- four", resolved: false }];
  const joined = segments.map((segment) => segment.text).join("");
  assert.equal(textOf(renderBody("", find, { segments })), textOf(renderBody(joined, find)));
  assert.equal(textOf(renderBody(joined, find)), "one two three" + "four", "the markers and the bullet are not read");
});

test("renderBody on the board: plain lines, and no links unless the references are marked", () => {
  assert.equal(drawn(renderBody("- **x** see #12", find, { plain: true, links: false })), "strong(x)| see #12");
  assert.equal(drawn(renderBody("# Title\n> quote #12", find, { plain: true, links: false })), "Title|\n|quote #12");
  const segments = [{ text: "see #12", resolved: false }];
  assert.equal(drawn(renderBody("", find, { segments, plain: true, links: true })), "see |a:#12");
});

/** Every element of a drawn tree that the test says yes to. */
function findAll(node, yes, found = []) {
  if (!(node instanceof FakeNode)) return found;
  if (yes(node)) found.push(node);
  node.children.forEach((child) => findAll(child, yes, found));
  return found;
}

test("renderBody: marks and '#12' links sit inside every kind of block; code and the words of a link get marks but no '#12' link", () => {
  const text = (value, resolved = false) => ({ text: value, resolved });
  const segments = [
    text("# Title "), text("R1", true), text(" #12\n\n> quote "), text("R2", true), text(" #7\n\n- item "), text("R3", true),
    text("\n\n| h |\n|---|\n| cell "), text("R4", true), text(" #12 |\n\n```\ncode "), text("R5", true), text(" #12\n```\n\n[link "), text("R6", true),
    text(" #12](https://x.test)"),
  ];
  const out = renderBody("", find, { segments });
  const inside = (tag, mark) => findAll(out, (el) => el.tagName === tag).some((el) => findAll(el, (m) => m.tagName === "mark" && textOf(m) === mark).length === 1);
  assert.ok(inside("h1", "R1"), "heading");
  assert.ok(inside("blockquote", "R2"), "quote");
  assert.ok(inside("li", "R3"), "list item");
  assert.ok(inside("td", "R4"), "table cell");
  assert.ok(inside("code", "R5"), "code block");
  assert.ok(inside("a", "R6"), "words of a link");
  assert.equal(findAll(out, (el) => el.tagName === "mark").length, 6);
  const refs = findAll(out, (el) => el.className === "ref");
  assert.equal(refs.length, 3, "#12 in the heading, #7 in the quote, #12 in the cell; none in code or in a link's words");
  assert.equal(findAll(out, (el) => el.tagName === "a" && el.className === "md-link").length, 1);
  assert.equal(textOf(out), "Title R1 #12quote R2 #7item R3hcell R4 #12code R5 #12link R6 #12", "the marks change nothing about what is read");
});
