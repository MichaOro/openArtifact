import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { FakeNode, installDocument, textOf, uninstallDocument } from "./support.mjs";

const { parseInline, parseMarkdown, renderMarkdown, safeHref } = await import("../../openartifact/static/js/components/markdown.js");

beforeEach(() => installDocument());
afterEach(() => uninstallDocument());

/** A compact picture of the inline nodes: text stays text, an emphasis becomes "tag(children)". */
function show(nodes) {
  return nodes
    .map((node) => {
      if (node.type === "text") return node.text;
      if (node.type === "code") return `code(${node.text})`;
      return `${node.type}(${show(node.children)})`;
    })
    .join("|");
}
const inline = (text) => show(parseInline(text));

/** The same for a drawn fragment (strings and elements). */
function drawn(node) {
  if (typeof node === "string") return node;
  const inner = node.children.map(drawn).join("|");
  return node.tagName === "#fragment" ? inner : `${node.tagName}(${inner})`;
}
const draw = (text, options) => drawn(renderMarkdown(text, options));

/** Every element of a drawn fragment. */
function elements(node, found = []) {
  if (node instanceof FakeNode) {
    if (node.tagName !== "#fragment") found.push(node);
    node.children.forEach((child) => elements(child, found));
  }
  return found;
}
const tags = (text) => elements(renderMarkdown(text)).map((el) => el.tagName);

// ── the owner's sample: only a test, it is nowhere in the application ────────────────────────────────────────────

const SAMPLE = [
  "# Welcome to my Markdown Parser",
  "",
  "This is a **simple example** to demonstrate how _Markdown_ is parsed and rendered.",
  "",
  "## Features",
  "",
  "- Headings",
  "- Text formatting (**bold**, _italic_)",
  "- Lists",
  "- Links",
  "- `Inline code` and code blocks",
  "- Tables",
  "- Blockquotes",
  "",
  "> Good documentation makes great software.",
  "",
  "#### Code Block Example",
  "",
  "```javascript",
  "function hello() {",
  '  console.log("Hello, Markdown!");',
  "}",
  "```",
  "",
  "## Table Example",
  "| Item | Detail |",
  "|------|--------|",
  "| Morning | 08:30 |",
  "| Afternoon | 13:15 |",
  "| Evening | 18:45 |",
  "| Night | 22:00 |",
].join("\n");

test("the sample draws a heading 1, a paragraph with bold and italic, a heading 2, a list of seven, a quote, a heading 4, a code block and a table", () => {
  const blocks = parseMarkdown(SAMPLE);
  assert.deepEqual(
    blocks.map((block) => (block.type === "heading" ? `h${block.level}` : block.type)),
    ["h1", "para", "h2", "list", "quote", "h4", "code", "h2", "table"],
  );
  assert.equal(blocks[3].items.length, 7);
  assert.equal(show(blocks[3].items[1].nodes), "Text formatting (|strong(bold)|, |em(italic)|)");
  assert.equal(show(blocks[3].items[4].nodes), "code(Inline code)| and code blocks");
  assert.equal(blocks[6].lang, "javascript");
  assert.equal(blocks[6].lines.length, 3);
  assert.equal(blocks[8].head.length, 2);
  assert.equal(blocks[8].rows.length, 4);

  const drawnTags = tags(SAMPLE);
  for (const tag of ["h1", "h2", "h4", "p", "ul", "li", "strong", "em", "code", "blockquote", "pre", "table", "thead", "tbody", "th", "td"]) {
    assert.ok(drawnTags.includes(tag), tag);
  }
  assert.equal(drawnTags.filter((tag) => tag === "li").length, 7);
  assert.equal(drawnTags.filter((tag) => tag === "td").length, 8);
  const code = elements(renderMarkdown(SAMPLE)).find((el) => el.tagName === "pre");
  assert.equal(textOf(code), 'function hello() {\n  console.log("Hello, Markdown!");\n}');
  const caption = elements(renderMarkdown(SAMPLE)).find((el) => el.className === "md-code__lang");
  assert.equal(textOf(caption), "javascript");
});

// ── inline ────────────────────────────────────────────────────────────────────────────────────────────────────

test("bold, italic and strikethrough, with stars and with underscores", () => {
  assert.equal(inline("a **bold** b"), "a |strong(bold)| b");
  assert.equal(inline("a __bold__ b"), "a |strong(bold)| b");
  assert.equal(inline("a *italic* b"), "a |em(italic)| b");
  assert.equal(inline("a _italic_ b"), "a |em(italic)| b");
  assert.equal(inline("a ~~gone~~ b"), "a |del(gone)| b");
});

test("emphasis nests: italic in bold, bold in italic, all three", () => {
  assert.equal(inline("**bold and *italic* here**"), "strong(bold and |em(italic)| here)");
  assert.equal(inline("*italic and **bold** here*"), "em(italic and |strong(bold)| here)");
  assert.equal(inline("~~**x**~~"), "del(strong(x))");
  assert.equal(inline("***x***"), "strong(em(x))");
  assert.equal(inline("__bold and _italic_ here__"), "strong(bold and |em(italic)| here)");
});

test("a marker that opens beside a blank, or never closes, is text; so is an empty emphasis", () => {
  assert.equal(inline("2 * 3 * 4"), "2 * 3 * 4");
  assert.equal(inline("a ** b ** c"), "a ** b ** c");
  assert.equal(inline("*never closed"), "*never closed");
  assert.equal(inline("**never closed"), "**never closed");
  assert.equal(inline("_never closed"), "_never closed");
  assert.equal(inline("~~never"), "~~never");
  assert.equal(inline("**** and ~~~~"), "**** and ~~~~");
  assert.equal(inline("trailing *"), "trailing *");
});

test("a closing marker after a blank does not close", () => {
  assert.equal(inline("*a *"), "*a *");
  assert.equal(inline("**a **"), "**a **");
  assert.equal(inline("_a _"), "_a _");
});

test("an emphasis inside a word is no emphasis: a*b*c, 2*3*4, snake_case, 2_3, file*.txt", () => {
  for (const text of ["a*b*c", "2*3*4", "snake_case_name", "2_3_4", "*.txt and *.md", "x**y**z", "a~~b~~c", "some_var_name and other_var"]) {
    assert.equal(inline(text), text, text);
  }
});

test("inline code keeps what is in it as it is, also stars and links", () => {
  assert.equal(inline("a `x *y* z` b"), "a |code(x *y* z)| b");
  assert.equal(inline("``a ` b``"), "code(a ` b)");
  assert.equal(inline("`[a](https://x.test)`"), "code([a](https://x.test))");
  assert.equal(inline("`never closed"), "`never closed");
  assert.equal(inline("``"), "``");
});

test("an emphasis never spans a line: each line is read alone", () => {
  const blocks = parseMarkdown("*one\ntwo*");
  assert.equal(blocks.length, 1);
  assert.deepEqual(blocks[0].lines.map((line) => show(line.nodes)), ["*one", "two*"]);
});

test("the positions of the pieces point into the text", () => {
  const text = "ab **cd** `ef` gh";
  const nodes = parseInline(text);
  assert.equal(nodes[0].start, 0);
  assert.equal(nodes[1].children[0].start, 5);
  assert.equal(text.slice(nodes[1].children[0].start, nodes[1].children[0].start + 2), "cd");
  assert.equal(nodes[2].start, 9);
  assert.equal(nodes[3].type, "code");
  assert.equal(text.slice(nodes[3].start, nodes[3].start + 2), "ef");
});

// ── links ─────────────────────────────────────────────────────────────────────────────────────────────────────

test("a link goes only to http, https or mailto; anything else is text", () => {
  assert.equal(safeHref("https://x.test/a?b=1#c"), "https://x.test/a?b=1#c");
  assert.equal(safeHref("http://x.test"), "http://x.test");
  assert.equal(safeHref("mailto:a@x.test"), "mailto:a@x.test");
  for (const bad of ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>", "vbscript:x", "file:///etc/passwd", "ftp://x.test", "//x.test", "www.x.test", "https://", "https://x.test/a b", 'https://x.test/"', "", null]) {
    assert.equal(safeHref(bad), null, String(bad));
  }
});

test("[text](address) is a link with the text the person wrote; a bare address is a link too", () => {
  const [link] = parseInline("[the site](https://x.test/a_b_c)");
  assert.equal(link.type, "link");
  assert.equal(link.href, "https://x.test/a_b_c");
  assert.equal(show(link.children), "the site");
  assert.equal(inline("see https://x.test/a_b_c and more"), "see |link(https://x.test/a_b_c)| and more");
  assert.equal(inline("(https://x.test/a)."), "(|link(https://x.test/a)|)."); // the dot ends the sentence; the bracket is the text's
  assert.equal(inline("https://en.x.test/w/Foo_(bar) end"), "link(https://en.x.test/w/Foo_(bar))| end");
  assert.equal(inline("[**bold** link](https://x.test)"), "link(strong(bold)| link)");
});

test("a link that is none stays text: an unsafe address, no address, an image, a link in a link, no closing bracket", () => {
  for (const text of ["[x](javascript:alert(1))", "[x](www.x.test)", "[x]()", "[x](data:text/html,a)"]) {
    assert.ok(!show(parseInline(text)).includes("link("), `${text}: ${show(parseInline(text))}`);
  }
  // with a safe address in it the words stay as written; the address alone may still be a bare link
  for (const text of ["[](https://x.test)", "[x] (https://x.test)", "[x](https://x.test", "![alt](https://x.test/p.png)"]) {
    assert.equal(textOf(renderMarkdown(text)), text, text);
  }
  assert.equal(inline("![alt](https://x.test/p.png)"), "![alt](https://x.test/p.png)");
  assert.equal(inline("xhttps://x.test"), "xhttps://x.test");
});

test("a drawn link opens in a new tab without referrer, shows its address, and holds only text", () => {
  const a = elements(renderMarkdown("[click **here**](https://x.test/a)")).find((el) => el.tagName === "a");
  assert.equal(a.tagName, "a");
  assert.equal(a.href, "https://x.test/a");
  assert.equal(a.target, "_blank");
  assert.equal(a.rel, "noopener noreferrer nofollow");
  assert.equal(a.title, "https://x.test/a");
  assert.equal(textOf(a), "click here");
});

// ── blocks ────────────────────────────────────────────────────────────────────────────────────────────────────

test("headings: one to six, a blank after the hashes; '##Hallo' and '#117' are text", () => {
  assert.deepEqual(parseMarkdown("# a\n## b\n### c\n#### d\n##### e\n###### f").map((block) => block.level), [1, 2, 3, 4, 5, 6]);
  assert.equal(draw("## Hallo"), "h2(Hallo)");
  assert.equal(draw("## Hallo **bold** ##"), "h2(Hallo |strong(bold))");
  for (const text of ["##Hallo", "#117 is a card", "####### seven", "#", "# "]) {
    assert.deepEqual(parseMarkdown(text).map((block) => block.type), ["para"], text);
  }
});

test("a quote: lines with '>', two levels, the inner text is read as blocks", () => {
  assert.equal(draw("> a\n> b"), "blockquote(p(a|\n|b))");
  assert.equal(draw("> # Title\n> - one\n> - two"), "blockquote(h1(Title)|ul(li(one)|li(two)))");
  assert.equal(draw("> a\n>> b"), "blockquote(p(a)|blockquote(p(b)))");
  assert.equal(draw("> a\n> > b\n> > > c").includes("blockquote(p(c))"), false); // the third level is text
  assert.ok(textOf(renderMarkdown("> a\n> > b\n> > > c")).includes("> c"));
});

test("a fenced block: its content is text, nothing in it is read, the language is a caption; an unclosed fence runs to the end", () => {
  assert.equal(draw("```js\na **b** # c\n- d\n```"), "div(div(js)|pre(code(a **b** # c|\n|- d)))");
  assert.equal(draw("```\nx\n```"), "div(pre(code(x)))");
  assert.equal(draw("~~~\nx\n~~~"), "div(pre(code(x)))");
  assert.equal(draw("```\nopen\nstill"), "div(pre(code(open|\n|still)))");
  assert.equal(draw("````\n```\n````"), "div(pre(code(```)))"); // a longer fence holds a shorter one
});

test("lists: bullets with - * +, numbers with '1.', nested by the indent, three levels below the first", () => {
  const [list] = parseMarkdown("- one\n  - two\n    - three\n      - far\n- four");
  assert.equal(list.type, "list");
  assert.deepEqual(list.items.map((item) => [show(item.nodes), item.depth]), [
    ["one", 0], ["two", 1], ["three", 2], ["far", 3], ["four", 0],
  ]);
  assert.equal(draw("* a\n+ b"), "ul(li(a)|li(b))");
  assert.equal(draw("1. a\n2. b"), "ol(li(a)|li(b))");
  assert.equal(draw("- a\n  1. b\n  2. c\n- d"), "ul(li(a|ol(li(b)|li(c)))|li(d))");
  assert.equal(draw("1. a\n- b"), "ol(li(a))|ul(li(b))"); // a bullet after a number is another list
  const [ordered] = elements(renderMarkdown("3. x\n4. y"));
  assert.equal(ordered.tagName, "ol");
  assert.equal(ordered.attributes.start, "3");
});

test("an indent of two, three or four spaces nests one level; a deep first item starts at the top, and a jump is one level at a time", () => {
  assert.deepEqual(parseMarkdown("- a\n   - b\n      - c")[0].items.map((item) => item.depth), [0, 1, 2]);
  assert.deepEqual(parseMarkdown("- a\n    - b")[0].items.map((item) => item.depth), [0, 1]);
  const [list] = parseMarkdown("    - deep\n- top\n      - jump");
  assert.deepEqual(list.items.map((item) => item.depth), [0, 0, 1]);
});

test("only a marker with something after it is an item: a dash, '-x', '2024.x', a lone '- ' stay text", () => {
  for (const text of ["-x", "- ", "– dash", "a - b", "-- two", "2024.x", "1.", "*star*"]) {
    assert.deepEqual(parseMarkdown(text).map((block) => block.type), ["para"], text);
  }
});

test("with lists off, a '- ' line is a line of text", () => {
  assert.deepEqual(parseMarkdown("- one", { lists: false }).map((block) => block.type), ["para"]);
});

test("a number other than 1 does not break a paragraph, a bullet and a heading do", () => {
  assert.deepEqual(parseMarkdown("text\n2. two").map((block) => block.type), ["para"]);
  assert.deepEqual(parseMarkdown("text\n1. one").map((block) => block.type), ["para", "list"]);
  assert.deepEqual(parseMarkdown("text\n- one\n# h").map((block) => block.type), ["para", "list", "heading"]);
});

test("a rule: three or more of - * _ on a line", () => {
  assert.equal(draw("a\n---\nb"), "p(a)|hr()|p(b)");
  assert.equal(draw("***"), "hr()");
  assert.equal(draw("- - -"), "hr()");
  assert.deepEqual(parseMarkdown("--").map((block) => block.type), ["para"]);
});

test("a table: header, delimiter and rows; alignment colons; escaped pipes; formatting in cells; short rows are filled, long ones cut", () => {
  const [table] = parseMarkdown("| a | b | c |\n|:--|:-:|--:|\n| 1 | **2** | `3` |\n| x \\| y |\n| p | q | r | s |");
  assert.equal(table.type, "table");
  assert.deepEqual(table.head.map((cell) => cell.align), ["left", "center", "right"]);
  assert.deepEqual(table.head.map((cell) => show(cell.nodes)), ["a", "b", "c"]);
  assert.equal(table.rows.length, 3);
  assert.deepEqual(table.rows[0].map((cell) => show(cell.nodes)), ["1", "strong(2)", "code(3)"]);
  assert.deepEqual(table.rows[1].map((cell) => cell.nodes.map((node) => node.text).join("")), ["x | y", "", ""]); // \| is a pipe in the cell
  assert.deepEqual(table.rows[2].map((cell) => show(cell.nodes)), ["p", "q", "r"]);
  const drawnTable = elements(renderMarkdown("a | b\n--|--\n1 | 2"));
  assert.deepEqual(drawnTable.map((el) => el.tagName), ["div", "table", "thead", "tr", "th", "th", "tbody", "tr", "td", "td"]);
  assert.equal(drawnTable.find((el) => el.tagName === "th").attributes.scope, "col");
  const aligned = elements(renderMarkdown("| a |\n|--:|\n| 1 |"));
  assert.equal(aligned.find((el) => el.tagName === "td").className, "md-al-right");
});

test("what is no table stays text: no delimiter row, other columns, no pipe", () => {
  for (const text of ["a | b\nno | delimiter", "| a | b |\n|---|\n| 1 | 2 |", "a\n---", "one line | with a pipe"]) {
    assert.ok(!parseMarkdown(text).some((block) => block.type === "table"), text);
  }
});

test("blocks need a blank line or a block mark between them; a blank line splits paragraphs", () => {
  assert.equal(draw("a\n\nb"), "p(a)|p(b)");
  assert.equal(draw("a\nb"), "p(a|\n|b)"); // one line break inside a paragraph stays visible
  assert.equal(draw("intro\n- one\noutro"), "p(intro)|ul(li(one))|p(outro)");
  assert.equal(draw("- a\n\nb"), "ul(li(a))|p(b)");
  assert.equal(draw("a\n\n\n\nb"), "p(a)|p(b)");
});

test("a text of an old kind reads as before", () => {
  const old = [
    "see #117 and ${card.title}",
    "snake_case and 2 * 3 * 4 and a - dash and some_var_x",
    "ZIEL: Zentraler Blick (Stand 25.11.2026)",
    "-- not a list\n-x",
    "email me: a@x.test, or visit www.x.test",
    "path/to/file_name.txt and a*b*c",
  ];
  for (const text of old) assert.equal(textOf(renderMarkdown(text)), text, text);
  for (const text of old) assert.ok(!tags(text).some((tag) => !["p"].includes(tag)), text);
});

test("an old numbered list or a line that starts with '#' now reads as a list or a heading (the owner widened the Markdown)", () => {
  assert.equal(draw("1. first\n2. second"), "ol(li(first)|li(second))");
  assert.equal(draw("# heading"), "h1(heading)");
});

test("what is not drawn stays literal: images, html, reference links, footnotes, task lists", () => {
  const literal = ["![alt](x.png)", "![alt](https://x.test/p.png)", "<b>x</b>", "<table><tr><td>x</td></tr></table>", "[a][b]", "[^1]", "text[^1]"];
  for (const text of literal) {
    assert.equal(textOf(renderMarkdown(text)), text, text);
    assert.deepEqual(tags(text), ["p"], text);
  }
  assert.equal(textOf(renderMarkdown("- [ ] todo")), "[ ] todo"); // a list item with the brackets as text
});

test("markup in a text is text: nothing is ever drawn as an element but those Markdown has", () => {
  // [what was written, what is read: the markers that formatted are gone, every other character is there]
  const attacks = [
    ["<script>alert(1)</script>", "<script>alert(1)</script>"],
    ["<img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>"],
    ["**<img src=x onerror=alert(1)>**", "<img src=x onerror=alert(1)>"],
    ["- <script>alert(1)</script>", "<script>alert(1)</script>"],
    ["# <script>alert(1)</script>", "<script>alert(1)</script>"],
    ["> <img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>"],
    ["| <b>x</b> |\n|---|\n| <i>y</i> |", "<b>x</b><i>y</i>"],
    ["```\n<script>alert(1)</script>\n```", "<script>alert(1)</script>"],
    ["`<script>alert(1)</script>`", "<script>alert(1)</script>"],
    ["[click](javascript:alert(1))", "[click](javascript:alert(1))"],
    ["[click](JaVaScRiPt:alert(1))", "[click](JaVaScRiPt:alert(1))"],
    ["[click](data:text/html;base64,PHNjcmlwdD4=)", "[click](data:text/html;base64,PHNjcmlwdD4=)"],
    ["javascript:alert(1)", "javascript:alert(1)"],
    ["&lt;b&gt; &amp; &#60;", "&lt;b&gt; &amp; &#60;"],
    ['<a href="javascript:alert(1)">x</a> *<b>y</b>*', '<a href="javascript:alert(1)">x</a> <b>y</b>'],
  ];
  const allowed = new Set(["p", "h1", "strong", "em", "del", "ul", "li", "code", "blockquote", "div", "pre", "table", "thead", "tbody", "tr", "th", "td"]);
  for (const [text, read] of attacks) {
    const fragment = renderMarkdown(text);
    const found = elements(fragment).map((el) => el.tagName);
    assert.ok(found.every((tag) => allowed.has(tag)), `${text}: ${found}`);
    assert.ok(!found.includes("a"), `${text}: no link`);
    assert.equal(textOf(fragment), read, text);
  }
});

test("a link's address is data: no element has an event handler or a style from the text", () => {
  const text = '[x](https://x.test/" onmouseover="alert(1))';
  const fragment = renderMarkdown(text);
  assert.equal(textOf(fragment), text); // the quote ends the address: the rest stays text, nothing is an attribute
  assert.deepEqual(elements(fragment).filter((el) => el.tagName === "a").map((el) => el.href), ["https://x.test/"]);
  const a = elements(renderMarkdown("[x](https://x.test/a)")).find((el) => el.tagName === "a");
  assert.deepEqual(Object.keys(a.attributes ?? {}), []);
});

// ── limits ────────────────────────────────────────────────────────────────────────────────────────────────────

test("hostile texts cost no time: long runs of markers, deep nesting, many cells, a huge text", () => {
  const bad = [
    "*a ".repeat(2000),
    "_a ".repeat(2000),
    `${"[".repeat(5000)}x${"]".repeat(5000)}(https://x.test)`,
    "[a](".repeat(1500),
    "**".repeat(3000),
    "`".repeat(4000),
    "~~a ".repeat(2000),
    `${"> ".repeat(4000)}x`,
    `${"  ".repeat(500)}- x\n`.repeat(200),
    `${"| a ".repeat(5000)}|\n${"|---".repeat(5000)}|\n${"| b ".repeat(5000)}|`,
    "- - ".repeat(3000),
    "https://".repeat(1500),
    "a".repeat(300_000),
    "*x* ".repeat(60_000),
    `${"- item\n".repeat(30_000)}`,
    `${"| a | b |\n|---|---|\n".repeat(20)}${"| 1 | 2 |\n".repeat(2000)}`,
  ];
  for (const text of bad) {
    const started = performance.now();
    renderMarkdown(text);
    const took = performance.now() - started;
    assert.ok(took < 1500, `${text.slice(0, 24)}: ${took} ms`);
  }
});

test("a text past the limit keeps its first part as Markdown and the rest as plain text", () => {
  const long = `**a**\n${"x".repeat(150_000)}`;
  const blocks = parseMarkdown(long);
  assert.equal(blocks.at(-1).type, "para");
  assert.equal(textOf(renderMarkdown(long)), long.replace("**a**", "a"));
});

test("a line past the line limit has no block syntax and no emphasis", () => {
  const line = `# ${"*a* ".repeat(500)}`;
  assert.equal(parseMarkdown(line)[0].type, "para");
});

test("nesting stops: emphasis in emphasis in a link stays text beyond the limit", () => {
  const deep = `${"*a ".repeat(8)}x${" a*".repeat(8)}`;
  assert.doesNotThrow(() => renderMarkdown(deep));
  assert.equal(textOf(renderMarkdown(deep)).replaceAll("*", ""), deep.replaceAll("*", ""));
});

// ── drawing ───────────────────────────────────────────────────────────────────────────────────────────────────

test("a rendered text: paragraphs are p, emphasis strong/em/del, code is code, lists are ul/ol/li", () => {
  assert.equal(draw("x **b** y"), "p(x |strong(b)| y)");
  assert.equal(draw("x `c` y"), "p(x |code(c)| y)");
  assert.equal(draw("- one\n- two"), "ul(li(one)|li(two))");
  assert.equal(draw("- a\n  - b\n- c"), "ul(li(a|ul(li(b)))|li(c))");
});

test("the plain pieces are drawn by renderText, with their position in the text", () => {
  const seen = [];
  renderMarkdown("ab **cd**\nef", { renderText: (piece, start) => (seen.push([piece, start]), piece) });
  assert.deepEqual(seen, [["ab ", 0], ["cd", 5], ["\n", 9], ["ef", 10]]);
});

test("the pieces of every block kind carry their position; code and the words of a link go to renderLiteral", () => {
  const text = "# h\n> q\n- i\n`c` [l](https://x.test)\n```\nz\n```\n| a |\n|---|\n| b |";
  const plain = [];
  const literal = [];
  renderMarkdown(text, {
    renderText: (piece, start) => (plain.push([piece, start]), piece),
    renderLiteral: (piece, start) => (literal.push([piece, start]), piece),
  });
  for (const [piece, start] of [...plain, ...literal]) assert.equal(text.slice(start, start + piece.length), piece, `${piece} at ${start}`);
  assert.deepEqual(plain.map(([piece]) => piece).filter((piece) => piece.trim()), ["h", "q", "i", "a", "b"]);
  assert.deepEqual(literal.map(([piece]) => piece), ["c", "l", "z"]);
});

test("plain: the lines of a text without block marks, links or tables; bold, italic, strikethrough and code stay", () => {
  const plain = (text) => drawn(renderMarkdown(text, { plain: true }));
  assert.equal(plain("# Title\n\nSome **bold** text"), "Title|\n|Some |strong(bold)| text");
  assert.equal(plain("- a\n- b\n> quote\n1. n"), "a|\n|b|\n|quote|\n|n");
  assert.equal(plain("```js\nx = 1\n```"), "x = 1");
  assert.equal(plain("| a | b |\n|---|---|\n| 1 | 2 |"), "a| · |b|\n|1| · |2");
  assert.equal(plain("[the site](https://x.test) and `c`"), "the site| and |code(c)");
  assert.deepEqual(elements(renderMarkdown("[the site](https://x.test)", { plain: true })), []);
  assert.equal(plain("a\n---\nb"), "a|\n|b");
});

test("a text that is nothing, null or undefined draws nothing", () => {
  assert.equal(draw(""), "");
  assert.equal(draw(null), "");
  assert.equal(draw(undefined), "");
});
