import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { FakeNode, installDocument, textOf, uninstallDocument } from "./support.mjs";

const { parseInline, parseMarkdown, renderMarkdown } = await import("../../openartifact/static/js/components/markdown.js");

beforeEach(() => installDocument());
afterEach(() => uninstallDocument());

/** A compact picture of the inline nodes: text stays text, an emphasis becomes "tag(children)". */
function show(nodes) {
  return nodes.map((node) => (node.type === "text" ? node.text : `${node.type}(${show(node.children)})`)).join("|");
}
const inline = (text) => show(parseInline(text));

/** The same for a drawn fragment (strings and elements). */
function drawn(node) {
  if (typeof node === "string") return node;
  const inner = node.children.map(drawn).join("|");
  return node.tagName === "#fragment" ? inner : `${node.tagName}(${inner})`;
}
const draw = (text, options) => drawn(renderMarkdown(text, options));

test("bold, italic and strikethrough", () => {
  assert.equal(inline("a **bold** b"), "a |strong(bold)| b");
  assert.equal(inline("a *italic* b"), "a |em(italic)| b");
  assert.equal(inline("a ~~gone~~ b"), "a |del(gone)| b");
});

test("emphasis nests: italic in bold, bold in italic, all three", () => {
  assert.equal(inline("**bold and *italic* here**"), "strong(bold and |em(italic)| here)");
  assert.equal(inline("*italic and **bold** here*"), "em(italic and |strong(bold)| here)");
  assert.equal(inline("~~**x**~~"), "del(strong(x))");
  assert.equal(inline("***x***"), "strong(em(x))");
});

test("a marker that opens beside a blank, or never closes, is text; so is an empty emphasis", () => {
  assert.equal(inline("2 * 3 * 4"), "2 * 3 * 4");
  assert.equal(inline("a ** b ** c"), "a ** b ** c");
  assert.equal(inline("*never closed"), "*never closed");
  assert.equal(inline("**never closed"), "**never closed");
  assert.equal(inline("~~never"), "~~never");
  assert.equal(inline("**** and ~~~~"), "**** and ~~~~");
  assert.equal(inline("trailing *"), "trailing *");
});

test("a closing marker after a blank does not close", () => {
  assert.equal(inline("*a *"), "*a *");
  assert.equal(inline("**a **"), "**a **");
});

test("an emphasis inside a word is no emphasis: a*b*c, 2*3*4, snake_case, file*.txt", () => {
  for (const text of ["a*b*c", "2*3*4", "snake_case_name", "*.txt and *.md", "x**y**z", "a~~b~~c"]) {
    assert.equal(inline(text), text, text);
  }
});

test("underscores never make an emphasis", () => {
  assert.equal(inline("_italic_ and __bold__"), "_italic_ and __bold__");
});

test("an emphasis never spans a line: each line is read alone", () => {
  const blocks = parseMarkdown("*one\ntwo*");
  assert.equal(blocks.length, 1);
  assert.deepEqual(blocks[0].lines.map((line) => show(line.nodes)), ["*one", "two*"]);
});

test("the positions of the pieces point into the text", () => {
  const text = "ab **cd** ef";
  const nodes = parseInline(text);
  assert.equal(nodes[0].start, 0);
  assert.equal(nodes[1].children[0].start, 5);
  assert.equal(text.slice(nodes[1].children[0].start, nodes[1].children[0].start + 2), "cd");
  assert.equal(nodes[2].start, 9);
});

test("a list: items with '- ', sub items two spaces deeper, three levels at most", () => {
  const [list] = parseMarkdown("- one\n  - two\n    - three\n      - far\n- four");
  assert.equal(list.type, "list");
  assert.deepEqual(list.items.map((item) => [show(item.nodes), item.depth]), [
    ["one", 0], ["two", 1], ["three", 2], ["far", 3], ["four", 0],
  ]);
});

test("a deep first item starts at the top, and a jump is one level at a time", () => {
  const [list] = parseMarkdown("    - deep\n- top\n      - jump");
  assert.deepEqual(list.items.map((item) => item.depth), [0, 0, 1]);
});

test("only '- ' with something after it is an item: a dash, '-x', '1.', '* ' and a lone '- ' stay text", () => {
  for (const text of ["-x", "- ", "1. one", "* star", "– dash", "a - b", "-- two"]) {
    const blocks = parseMarkdown(text);
    assert.deepEqual(blocks.map((block) => block.type), ["para"], text);
  }
});

test("with lists off, a '- ' line is a line of text (the first words of a card)", () => {
  assert.deepEqual(parseMarkdown("- one", { lists: false }).map((block) => block.type), ["para"]);
});

test("a rendered text: lists are ul/li, emphasis are strong/em/del, the lines keep their breaks", () => {
  assert.equal(draw("a\nb"), "a|\n|b");
  assert.equal(draw("x **b** y"), "x |strong(b)| y");
  assert.equal(draw("- one\n- two"), "ul(li(one)|li(two))");
  assert.equal(draw("intro\n- one\noutro"), "intro|ul(li(one))|outro");
  assert.equal(draw("- a\n  - b\n- c"), "ul(li(a|ul(li(b)))|li(c))");
});

test("a blank line after a list stays a blank line; the break before a list is the list's own", () => {
  assert.equal(draw("- a\n\nb"), "ul(li(a))|\n|b");
  assert.equal(draw("a\n\n- b"), "a|\n|ul(li(b))");
});

test("a text of an old kind reads as before", () => {
  const old = [
    "1. first\n2. second",
    "see #117 and ${card.title}",
    "snake_case and 2 * 3 * 4 and a - dash",
    "ZIEL: Zentraler Blick (Stand 25.11.2026)",
    "-- not a list\n-x",
  ];
  for (const text of old) assert.equal(textOf(renderMarkdown(text)), text, text);
});

test("what is not Markdown of this subset stays literal: headings, code, links, images, html, numbered lists", () => {
  const literal = ["# heading", "## two", "`code`", "[text](https://x.test)", "![alt](x.png)", "<b>x</b>", "> quote", "```\nfence\n```"];
  for (const text of literal) {
    assert.equal(textOf(renderMarkdown(text)), text, text);
    const tags = [];
    (function walk(node) {
      if (node instanceof FakeNode) {
        tags.push(node.tagName);
        node.children.forEach(walk);
      }
    })(renderMarkdown(text));
    assert.deepEqual(tags.filter((tag) => tag !== "#fragment"), [], text);
  }
});

test("markup in a text is text: nothing is ever drawn as an element but strong, em, del, ul and li", () => {
  // [what was written, what is read: the markers that formatted are gone, every other character is there]
  const attacks = [
    ["<script>alert(1)</script>", "<script>alert(1)</script>"],
    ["<img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>"],
    ["**<img src=x onerror=alert(1)>**", "<img src=x onerror=alert(1)>"],
    ["- <script>alert(1)</script>", "<script>alert(1)</script>"],
    ["[click](javascript:alert(1))", "[click](javascript:alert(1))"],
    ["javascript:alert(1)", "javascript:alert(1)"],
    ["&lt;b&gt; &amp; &#60;", "&lt;b&gt; &amp; &#60;"],
    ['<a href="javascript:alert(1)">x</a> *<b>y</b>*', '<a href="javascript:alert(1)">x</a> <b>y</b>'],
  ];
  const allowed = new Set(["#fragment", "strong", "em", "del", "ul", "li"]);
  for (const [text, read] of attacks) {
    const fragment = renderMarkdown(text);
    const tags = [];
    (function walk(node) {
      if (node instanceof FakeNode) {
        tags.push(node.tagName);
        node.children.forEach(walk);
      }
    })(fragment);
    assert.ok(tags.every((tag) => allowed.has(tag)), `${text}: ${tags}`);
    assert.equal(textOf(fragment), read, text);
  }
});

test("the plain pieces are drawn by renderText, with their position in the text", () => {
  const seen = [];
  renderMarkdown("ab **cd**\nef", { renderText: (piece, start) => (seen.push([piece, start]), piece) });
  assert.deepEqual(seen, [["ab ", 0], ["cd", 5], ["\n", 9], ["ef", 10]]);
});

test("a text that is nothing, null or undefined draws nothing", () => {
  assert.equal(draw(""), "");
  assert.equal(draw(null), "");
  assert.equal(draw(undefined), "");
});
