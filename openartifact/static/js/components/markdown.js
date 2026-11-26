/* The Markdown of the long texts (ADR-077): a card's text, a comment, a prompt. A text is plain text by convention
 * Markdown; the application renders a deliberately small part of it and leaves everything else exactly as written:
 *
 *   **bold**   *italic*   ~~strikethrough~~   and bullet lists ("- item", two more spaces for a sub list, three levels)
 *
 * Nothing else: no headings, code, links, numbered lists, checklists, images, underscores, escapes or HTML. An old text
 * (a "1." list, "#117", ${card.x}, snake_case, "2 * 3 * 4", a "-" dash in a sentence) therefore reads as before.
 *
 * Emphasis follows the usual rules and one more: a marker opens only when it is not followed by a blank and stands at the start or
 * after a character that is no letter, digit or underscore; it closes only when it is not preceded by a blank and is followed by the end or
 * by such a character; the text between is not empty; and it never spans a line. "a*b*c" and "2*3*4" are therefore
 * literal. A marker that does not close is literal text.
 *
 * The parser is pure (no DOM) and gives positions in the text, so that the one who draws can mark parts of it (the filled in
 * references, ADR-066). The renderer builds elements and text nodes only: the text of a person is never markup (ADR-069). */

const MARKERS = [
  { marker: "**", type: "strong" },
  { marker: "~~", type: "del" },
  { marker: "*", type: "em" },
];
const WORD = /[\p{L}\p{N}_]/u;
const SPACE = /\s/;
const MAX_DEPTH = 3; // levels of a list below the first
const ITEM = /^( {0,8})- (\S.*)$/;

const isWord = (char) => char !== undefined && WORD.test(char);
const isSpace = (char) => char === undefined || SPACE.test(char);

/** The marker at `i` that opens an emphasis ending inside [i, end): the node and where it ends, or null. */
function emphasis(text, i, end, parse) {
  const found = MARKERS.find(({ marker }) => text.startsWith(marker, i) && i + marker.length < end);
  if (!found) return null;
  const { marker, type } = found;
  const from = i + marker.length;
  if (isSpace(text[from]) || isWord(text[i - 1])) return { literal: marker.length };
  for (let j = from + 1; j + marker.length <= end; j += 1) {
    if (!text.startsWith(marker, j) || isSpace(text[j - 1]) || isWord(text[j + marker.length])) continue;
    const inside = (k) => k >= from && k < end; // what lies beyond the content belongs to an outer marker
    if (marker === "*" && ((inside(j - 1) && text[j - 1] === "*") || (inside(j + 1) && text[j + 1] === "*"))) continue; // a piece of ** is no italic end
    if (marker === "**" && inside(j + 2) && text[j + 2] === "*") continue; // in *** the last two stars close
    return { node: { type, children: parse(text, from, j) }, next: j + marker.length };
  }
  return { literal: marker.length };
}

/**
 * The inline nodes of text[start, end), which is one line: `{type: "text", text, start}` and `{type: "strong"|"em"|"del", children}`.
 * `start` is the position of the piece in `text`.
 */
export function parseInline(text, start = 0, end = text.length) {
  const nodes = [];
  let plain = start;
  const flush = (to) => {
    if (to > plain) nodes.push({ type: "text", text: text.slice(plain, to), start: plain });
  };
  let i = start;
  while (i < end) {
    if (text[i] !== "*" && text[i] !== "~") {
      i += 1;
      continue;
    }
    const found = emphasis(text, i, end, parseInline);
    if (!found) i += 1;
    else if (found.literal) i += found.literal;
    else {
      flush(i);
      nodes.push(found.node);
      i = plain = found.next;
    }
  }
  flush(end);
  return nodes;
}

/**
 * The blocks of a text: `{type: "para", lines: [{nodes, start, end}]}` and `{type: "list", items: [{depth, nodes}]}`.
 * With `lists` false a "- " line is a line like any other (the first words of a card on the board).
 */
export function parseMarkdown(text, { lists = true } = {}) {
  const blocks = [];
  let offset = 0;
  for (const line of String(text ?? "").split("\n")) {
    const start = offset;
    const end = start + line.length;
    offset = end + 1;
    const item = lists ? ITEM.exec(line) : null;
    if (item) {
      const previous = blocks.at(-1);
      const run = previous?.type === "list" ? previous : null;
      const wanted = Math.min(Math.floor(item[1].length / 2), MAX_DEPTH);
      const depth = Math.min(wanted, run ? run.items.at(-1).depth + 1 : 0);
      const from = end - item[2].length;
      const entry = { depth, nodes: parseInline(text, from, end) };
      if (run) run.items.push(entry);
      else blocks.push({ type: "list", items: [entry] });
    } else {
      const entry = { nodes: parseInline(text, start, end), start, end };
      const previous = blocks.at(-1);
      if (previous?.type === "para") previous.lines.push(entry);
      else blocks.push({ type: "para", lines: [entry] });
    }
  }
  return blocks;
}

function drawInline(nodes, renderText) {
  const out = [];
  for (const node of nodes) {
    if (node.type === "text") out.push(renderText(node.text, node.start));
    else {
      const el = document.createElement(node.type);
      el.append(...drawInline(node.children, renderText));
      out.push(el);
    }
  }
  return out;
}

function drawList(items, renderText) {
  const root = document.createElement("ul");
  const stack = [root];
  let lastItem = null;
  for (const item of items) {
    while (stack.length - 1 > item.depth) stack.pop();
    while (stack.length - 1 < item.depth) {
      const nested = document.createElement("ul");
      lastItem.append(nested);
      stack.push(nested);
    }
    const li = document.createElement("li");
    li.append(...drawInline(item.nodes, renderText));
    stack.at(-1).append(li);
    lastItem = li;
  }
  return root;
}

/**
 * Draw a text.
 * @param {string} text
 * @param {{renderText?: (piece: string, start: number) => Node|string, lists?: boolean}} [options]
 *   `renderText` draws a piece of plain text (its position in `text` is the second argument): the card's body uses it to turn
 *   "#12" into a link and to mark filled in references; the default is the text itself
 * @returns {DocumentFragment}
 */
export function renderMarkdown(text, { renderText = (piece) => document.createTextNode(piece), lists = true } = {}) {
  const fragment = document.createDocumentFragment();
  for (const block of parseMarkdown(text, { lists })) {
    if (block.type === "list") {
      fragment.append(drawList(block.items, renderText));
      continue;
    }
    block.lines.forEach((line, index) => {
      if (index) fragment.append(renderText("\n", line.start - 1));
      fragment.append(...drawInline(line.nodes, renderText));
    });
  }
  return fragment;
}
