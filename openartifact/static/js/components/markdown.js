/* The Markdown of the long texts (ADR-077): a card's text, a comment, a prompt. A text is plain text by convention Markdown;
 * the application renders the common Markdown and leaves everything else exactly as written:
 *
 *   # headings (one to six #, a blank after them)      **bold** __bold__   *italic* _italic_   ~~strikethrough~~
 *   `inline code`   ```fenced code blocks``` with an optional language label   > quotes (two levels)
 *   - bullet lists (also * and +) and 1. numbered lists, nested up to three levels below the first
 *   --- or *** a rule   [text](https://address) and bare https:// addresses   GFM tables with | cells | and alignment colons
 *
 * Not drawn on purpose: images, raw HTML, reference style links, footnotes, task lists, escapes (but \| in a table cell). They stay text.
 * An old text (a "1." list, "#117", ${card.x}, snake_case, "2 * 3 * 4", a "-" dash in a sentence) reads as before.
 *
 * Emphasis follows the usual rules and one more: a marker opens only when it is not followed by a blank and stands at the start or
 * after a character that is no letter, digit or underscore; it closes only when it is not preceded by a blank and is followed by the end or
 * by such a character; the text between is not empty; and it never spans a line. "a*b*c", "2*3*4" and "snake_case" are therefore
 * literal. A marker that does not close is literal text.
 *
 * The parser is pure (no DOM) and gives positions in the text, so that the one who draws can mark parts of it (the filled in
 * references, ADR-066). The renderer builds elements and text nodes only: the text of a person is never markup (ADR-069). A link
 * goes only to http, https or mailto; anything else is text. Every limit below keeps a hostile text from costing time. */

const MARKERS = [
  { marker: "**", type: "strong" },
  { marker: "__", type: "strong" },
  { marker: "~~", type: "del" },
  { marker: "*", type: "em" },
  { marker: "_", type: "em" },
];
const WORD = /[\p{L}\p{N}_]/u;
const SPACE = /\s/;
const MAX_TEXT = 100_000; // what is read as Markdown; the rest of a longer text stays a plain paragraph
const MAX_LINE = 1_500; // a longer line is plain text (no block syntax, no emphasis)
const MAX_DEPTH = 3; // levels of a list below the first
const MAX_QUOTE = 2; // levels of a quote
const MAX_INLINE = 4; // emphasis and links inside each other
const MAX_COLUMNS = 20;
const MAX_ROWS = 300;
const ITEM = /^( {0,12})([-*+]|\d{1,9}\.) (\S.*)$/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(\S.*)$/;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)[ \t]*$/;
const QUOTE = /^ {0,3}>/;
const DELIMITER_CELL = /^:?-+:?$/;
const BARE_END = /[.,;:!?'"*_~]$/;

const isWord = (char) => char !== undefined && WORD.test(char);
const isSpace = (char) => char === undefined || SPACE.test(char);

/**
 * The address of a link when it may be one: an http, https or mailto address without blanks or quotes, else null. Anything else
 * (javascript:, data:, a bare "www.x.de") is not a link here.
 */
export function safeHref(address) {
  const text = String(address ?? "").trim();
  if (!text || /[\u0000- \u007f<>"]/u.test(text)) return null;
  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol === "mailto:") return url.pathname ? text : null;
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  return url.hostname ? text : null;
}

/** The marker at `i` that opens an emphasis ending inside [i, end): the node and where it ends, or a literal run, or null. */
function emphasis(text, i, end, ctx) {
  const found = MARKERS.find(({ marker }) => text.startsWith(marker, i) && i + marker.length < end);
  if (!found) return null;
  const { marker, type } = found;
  const char = marker[0];
  const from = i + marker.length;
  if (isSpace(text[from]) || isWord(text[i - 1])) return { literal: marker.length };
  for (let j = from + 1; j + marker.length <= end; j += 1) {
    if (!text.startsWith(marker, j) || isSpace(text[j - 1]) || isWord(text[j + marker.length])) continue;
    const inside = (k) => k >= from && k < end; // what lies beyond the content belongs to an outer marker
    if (marker.length === 1 && ((inside(j - 1) && text[j - 1] === char) || (inside(j + 1) && text[j + 1] === char))) continue; // a piece of ** is no italic end
    if (marker.length === 2 && marker !== "~~" && inside(j + 2) && text[j + 2] === char) continue; // in *** the last two close
    return { node: { type, children: inline(text, from, j, ctx, 1) }, next: j + marker.length };
  }
  return { literal: marker.length };
}

/** A code span at `i`: the node and where it ends, or null when the backticks never close. */
function codeSpan(text, i, end) {
  let size = 0;
  while (i + size < end && text[i + size] === "`") size += 1;
  for (let j = i + size; j < end; j += 1) {
    if (text[j] !== "`") continue;
    let run = 0;
    while (j + run < end && text[j + run] === "`") run += 1;
    if (run === size) {
      let from = i + size;
      let to = j;
      const body = text.slice(from, to);
      if (body.length > 1 && body.startsWith(" ") && body.endsWith(" ") && body.trim()) {
        from += 1;
        to -= 1;
      }
      return to > from ? { node: { type: "code", text: text.slice(from, to), start: from }, next: j + run } : { literal: size };
    }
    j += run - 1;
  }
  return { literal: size };
}

/** A link "[text](address)" at `i`: the node and where it ends, or null. */
function link(text, i, end, ctx) {
  if (ctx.inLink) return null; // a link holds no link
  let depth = 0;
  let close = -1;
  for (let j = i; j < end; j += 1) {
    if (text[j] === "[") depth += 1;
    else if (text[j] === "]") {
      depth -= 1;
      if (depth === 0) {
        close = j;
        break;
      }
    }
  }
  if (close < 0 || close === i + 1 || text[close + 1] !== "(") return null;
  let stop = close + 2;
  for (let level = 1; stop < end; stop += 1) {
    if (text[stop] === "(") level += 1;
    else if (text[stop] === ")" && --level === 0) break;
  }
  if (stop >= end) return null;
  if (text[i - 1] === "!") return { literal: stop + 1 - i }; // an image stays text, address and all: nothing is fetched, nothing is linked
  const href = safeHref(text.slice(close + 2, stop));
  if (!href) return null;
  return { node: { type: "link", href, children: inline(text, i + 1, close, { ...ctx, inLink: true }, 1) }, next: stop + 1 };
}

/** A bare http or https address at `i`: a link node and where it ends, or null. */
function bareAddress(text, i, end, ctx) {
  if (ctx.inLink || isWord(text[i - 1])) return null;
  if (!text.startsWith("http://", i) && !text.startsWith("https://", i)) return null;
  let stop = i;
  while (stop < end && !/[\s<>"]/u.test(text[stop])) stop += 1;
  while (stop > i) {
    const last = text[stop - 1];
    const unbalanced = last === ")" && text.slice(i, stop).split("(").length < text.slice(i, stop).split(")").length;
    if (BARE_END.test(last) || unbalanced) stop -= 1;
    else break;
  }
  const href = safeHref(text.slice(i, stop));
  return href ? { node: { type: "link", href, bare: true, children: [{ type: "text", text: text.slice(i, stop), start: i }] }, next: stop } : null;
}

function inline(text, start, end, ctx, depth) {
  const nodes = [];
  if (ctx.depth + depth > MAX_INLINE) return [{ type: "text", text: text.slice(start, end), start }];
  const inner = { ...ctx, depth: ctx.depth + depth };
  const limit = Math.min(end, start + MAX_LINE);
  let plain = start;
  const flush = (to) => {
    if (to > plain) nodes.push({ type: "text", text: text.slice(plain, to), start: plain });
  };
  let i = start;
  while (i < limit) {
    const char = text[i];
    let found = null;
    if (char === "*" || char === "~" || char === "_") found = emphasis(text, i, limit, inner);
    else if (char === "`") found = codeSpan(text, i, limit);
    else if (char === "[") found = link(text, i, limit, inner);
    else if (char === "h") found = bareAddress(text, i, limit, inner);
    else if (char === "\\" && ctx.cell && text[i + 1] === "|") {
      flush(i); // "\|" in a table cell is a pipe
      plain = i + 1;
      i += 2;
      continue;
    }
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
 * The inline nodes of text[start, end), which is one line: `{type: "text", text, start}`, `{type: "strong"|"em"|"del", children}`,
 * `{type: "code", text, start}` and `{type: "link", href, children}`. `start` is the position of the piece in `text`.
 * `cell` reads "\|" as a pipe (a table cell).
 */
export function parseInline(text, start = 0, end = text.length, { cell = false } = {}) {
  return inline(text, start, end, { cell, inLink: false, depth: 0 }, 0);
}

// ── blocks ───────────────────────────────────────────────────────────────────────────────────────────────────────

const blank = (content) => !content.trim();

/** The unescaped pipes of [from, to) of the text. */
function pipesOf(text, from, to) {
  const found = [];
  for (let i = from; i < to; i += 1) {
    if (text[i] === "\\") i += 1;
    else if (text[i] === "|") found.push(i);
  }
  return found;
}

/** The cells [{s, e}] of a table row [from, to): the pipes at the ends are optional, a cell is trimmed. */
function cellsOf(text, from, to) {
  let a = from;
  let b = to;
  while (a < b && /[ \t]/.test(text[a])) a += 1;
  while (b > a && /[ \t]/.test(text[b - 1])) b -= 1;
  if (text[a] === "|") a += 1;
  if (b > a && text[b - 1] === "|" && pipesOf(text, a, b).includes(b - 1)) b -= 1;
  const cuts = [a - 1, ...pipesOf(text, a, b), b];
  const cells = [];
  for (let k = 0; k + 1 < cuts.length; k += 1) {
    let s = cuts[k] + 1;
    let e = cuts[k + 1];
    while (s < e && /[ \t]/.test(text[s])) s += 1;
    while (e > s && /[ \t]/.test(text[e - 1])) e -= 1;
    cells.push({ s, e });
  }
  return cells;
}

/** The alignments of a table delimiter row, or null when the line is none. */
function delimiterOf(text, line, columns) {
  const content = text.slice(line.s, line.e);
  if (!content.includes("|") || !content.includes("-")) return null;
  const cells = cellsOf(text, line.s, line.e);
  if (cells.length !== columns) return null;
  const aligns = [];
  for (const { s, e } of cells) {
    const cell = text.slice(s, e);
    if (!DELIMITER_CELL.test(cell)) return null;
    aligns.push(cell.startsWith(":") ? (cell.endsWith(":") ? "center" : "left") : cell.endsWith(":") ? "right" : null);
  }
  return aligns;
}

/** Whether `lines[i]` starts a table (a header row and a delimiter row below it). */
function tableAt(text, lines, i) {
  const head = lines[i];
  const below = lines[i + 1];
  if (!below || head.e - head.s > MAX_LINE || below.e - below.s > MAX_LINE) return null;
  if (!text.slice(head.s, head.e).includes("|")) return null;
  const cells = cellsOf(text, head.s, head.e);
  if (cells.length < 1 || cells.length > MAX_COLUMNS) return null;
  const aligns = delimiterOf(text, below, cells.length);
  return aligns ? { cells, aligns } : null;
}

/** The first number of an ordered item "3. x", or 0 for a bullet. */
const numberOf = (marker) => (/^\d/.test(marker) ? Number.parseInt(marker, 10) : 0);

/** Whether a line starts a block that ends a paragraph. */
function interrupts(text, lines, i, lists) {
  const { s, e } = lines[i];
  const content = text.slice(s, e);
  if (content.length > MAX_LINE) return false;
  if (FENCE.test(content) || HEADING.test(content) || RULE.test(content) || QUOTE.test(content)) return true;
  if (lists) {
    const item = ITEM.exec(content);
    if (item && (!/^\d/.test(item[2]) || numberOf(item[2]) === 1)) return true; // a number other than 1 does not break into a paragraph
  }
  return Boolean(tableAt(text, lines, i));
}

function parseBlocks(text, lines, { lists, quote }) {
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const content = text.slice(line.s, line.e);
    if (blank(content)) {
      i += 1;
      continue;
    }
    const long = content.length > MAX_LINE;
    let match;
    if (!long && (match = FENCE.exec(content))) {
      const [, ticks, lang] = match;
      const body = [];
      let j = i + 1;
      while (j < lines.length) {
        const closer = FENCE.exec(text.slice(lines[j].s, lines[j].e));
        if (closer && closer[1][0] === ticks[0] && closer[1].length >= ticks.length && !closer[2]) break;
        body.push(lines[j]);
        j += 1;
      }
      blocks.push({ type: "code", lang, lines: body, start: line.s, end: lines[Math.min(j, lines.length - 1)].e });
      i = j + 1;
      continue;
    }
    if (!long && (match = HEADING.exec(content))) {
      let from = line.s + content.indexOf("#") + match[1].length;
      while (/[ \t]/.test(text[from])) from += 1;
      let to = line.e;
      while (to > from && /[ \t]/.test(text[to - 1])) to -= 1;
      const closing = /[ \t]+#+$/.exec(text.slice(from, to));
      if (closing && closing.index > 0) to = from + closing.index;
      blocks.push({ type: "heading", level: match[1].length, nodes: parseInline(text, from, to), start: from, end: to });
      i += 1;
      continue;
    }
    if (!long && RULE.test(content)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }
    if (!long && QUOTE.test(content) && quote < MAX_QUOTE) {
      const inner = [];
      let j = i;
      while (j < lines.length && lines[j].e - lines[j].s <= MAX_LINE && QUOTE.test(text.slice(lines[j].s, lines[j].e))) {
        const at = lines[j].s + text.slice(lines[j].s, lines[j].e).indexOf(">") + 1;
        inner.push({ s: text[at] === " " ? at + 1 : at, e: lines[j].e });
        j += 1;
      }
      blocks.push({ type: "quote", blocks: parseBlocks(text, inner, { lists, quote: quote + 1 }) });
      i = j;
      continue;
    }
    const table = long ? null : tableAt(text, lines, i);
    if (table) {
      const head = table.cells.map(({ s, e }, k) => ({ nodes: parseInline(text, s, e, { cell: true }), align: table.aligns[k], start: s, end: e }));
      const rows = [];
      let j = i + 2;
      while (j < lines.length && rows.length < MAX_ROWS) {
        const row = lines[j];
        const rowText = text.slice(row.s, row.e);
        if (blank(rowText) || !rowText.includes("|") || rowText.length > MAX_LINE) break;
        const cells = cellsOf(text, row.s, row.e);
        rows.push(
          table.aligns.map((align, k) => {
            const cell = cells[k] ?? { s: row.e, e: row.e };
            return { nodes: parseInline(text, cell.s, cell.e, { cell: true }), align, start: cell.s, end: cell.e };
          }),
        );
        j += 1;
      }
      blocks.push({ type: "table", head, rows });
      i = j;
      continue;
    }
    const item = lists && !long ? ITEM.exec(content) : null;
    if (item) {
      const items = [];
      const stack = [];
      let j = i;
      while (j < lines.length) {
        const rowText = text.slice(lines[j].s, lines[j].e);
        const m = rowText.length > MAX_LINE || RULE.test(rowText) ? null : ITEM.exec(rowText);
        if (!m) break;
        const indent = m[1].length;
        while (stack.length && indent < stack.at(-1)) stack.pop();
        if (!stack.length || indent > stack.at(-1)) {
          if (stack.length - 1 < MAX_DEPTH) stack.push(indent);
        }
        const from = lines[j].e - m[3].length;
        items.push({
          depth: stack.length - 1,
          ordered: /^\d/.test(m[2]),
          number: numberOf(m[2]),
          nodes: parseInline(text, from, lines[j].e),
        });
        j += 1;
      }
      blocks.push({ type: "list", items });
      i = j;
      continue;
    }
    // a paragraph: lines up to a blank line or the start of another block
    const para = { type: "para", lines: [] };
    let j = i;
    while (j < lines.length) {
      const own = text.slice(lines[j].s, lines[j].e);
      if (blank(own) || (j > i && interrupts(text, lines, j, lists))) break;
      para.lines.push({ nodes: parseInline(text, lines[j].s, lines[j].e), start: lines[j].s, end: lines[j].e });
      j += 1;
    }
    blocks.push(para);
    i = j;
  }
  return blocks;
}

/**
 * The blocks of a text: `{type: "para", lines: [{nodes, start, end}]}`, `{type: "heading", level, nodes}`,
 * `{type: "list", items: [{depth, ordered, number, nodes}]}`, `{type: "quote", blocks}`, `{type: "code", lang, lines: [{s, e}]}`,
 * `{type: "table", head: [{nodes, align}], rows: [[{nodes, align}]]}` and `{type: "hr"}`.
 * With `lists` false a "- " line is a line like any other.
 */
export function parseMarkdown(text, { lists = true } = {}) {
  const source = String(text ?? "");
  const head = source.length > MAX_TEXT ? source.slice(0, MAX_TEXT) : source;
  const lines = [];
  let offset = 0;
  for (const line of head.split("\n")) {
    lines.push({ s: offset, e: offset + line.length });
    offset += line.length + 1;
  }
  const blocks = parseBlocks(head, lines, { lists, quote: 0 });
  if (source.length > MAX_TEXT) {
    blocks.push({ type: "para", lines: [{ nodes: [{ type: "text", text: source.slice(MAX_TEXT), start: MAX_TEXT }], start: MAX_TEXT, end: source.length }] });
  }
  return blocks;
}

// ── drawing ──────────────────────────────────────────────────────────────────────────────────────────────────────

function make(tag, className = "") {
  const el = document.createElement(tag);
  if (className) el.className = className;
  return el;
}

function drawInline(nodes, ctx, inLink = false) {
  const out = [];
  for (const node of nodes) {
    if (node.type === "text") out.push(inLink ? ctx.renderLiteral(node.text, node.start) : ctx.renderText(node.text, node.start));
    else if (node.type === "code") {
      const el = make("code", "md-code-inline");
      el.append(ctx.renderLiteral(node.text, node.start));
      out.push(el);
    } else if (node.type === "link") {
      if (ctx.plain) out.push(...drawInline(node.children, ctx, true));
      else {
        const el = make("a", "md-link");
        el.href = node.href;
        el.target = "_blank";
        el.rel = "noopener noreferrer nofollow";
        el.title = node.href; // the address is what a click goes to: shown on hover, so a disguised link shows itself
        el.append(...drawInline(node.children, ctx, true));
        out.push(el);
      }
    } else {
      const el = make(node.type);
      el.append(...drawInline(node.children, ctx, inLink));
      out.push(el);
    }
  }
  return out;
}

function drawList(items, ctx) {
  const tops = [];
  const stack = []; // {list, ordered, last}: the lists open now, one per level
  const open = (ordered, number) => {
    const list = make(ordered ? "ol" : "ul");
    if (ordered && number > 1) list.setAttribute("start", number);
    if (stack.length) stack.at(-1).last.append(list);
    else tops.push(list);
    stack.push({ list, ordered, last: null });
  };
  for (const item of items) {
    while (stack.length - 1 > item.depth) stack.pop();
    if (stack.length - 1 === item.depth && stack.at(-1).ordered !== item.ordered) stack.pop(); // a bullet after a number starts another list
    while (stack.length < item.depth + 1) open(item.ordered, stack.length === item.depth ? item.number : 1);
    const li = make("li");
    li.append(...drawInline(item.nodes, ctx));
    stack.at(-1).list.append(li);
    stack.at(-1).last = li;
  }
  return tops;
}

function drawTable(block, ctx) {
  const wrap = make("div", "md-table");
  const table = make("table");
  const alignClass = (align) => (align ? `md-al-${align}` : "");
  const head = make("thead");
  const headRow = make("tr");
  for (const cell of block.head) {
    const th = make("th", alignClass(cell.align));
    th.setAttribute("scope", "col");
    th.append(...drawInline(cell.nodes, ctx));
    headRow.append(th);
  }
  head.append(headRow);
  const body = make("tbody");
  for (const row of block.rows) {
    const tr = make("tr");
    for (const cell of row) {
      const td = make("td", alignClass(cell.align));
      td.append(...drawInline(cell.nodes, ctx));
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}

function drawCode(block, ctx, text) {
  const wrap = make("div", "md-code");
  if (block.lang) {
    const caption = make("div", "md-code__lang");
    caption.append(document.createTextNode(block.lang));
    wrap.append(caption);
  }
  const pre = make("pre", "md-code__pre");
  const code = make("code");
  block.lines.forEach((line, index) => {
    if (index) code.append(ctx.renderLiteral("\n", block.lines[index - 1].e));
    code.append(ctx.renderLiteral(text.slice(line.s, line.e), line.s));
  });
  pre.append(code);
  wrap.append(pre);
  return wrap;
}

function drawBlocks(blocks, ctx, text) {
  const out = [];
  for (const block of blocks) {
    if (block.type === "para") {
      const p = make("p", "md-p");
      block.lines.forEach((line, index) => {
        if (index) p.append(ctx.renderText("\n", line.start - 1)); // a line break inside a paragraph stays visible
        p.append(...drawInline(line.nodes, ctx));
      });
      out.push(p);
    } else if (block.type === "heading") {
      const h = make(`h${block.level}`, "md-h");
      h.append(...drawInline(block.nodes, ctx));
      out.push(h);
    } else if (block.type === "list") out.push(...drawList(block.items, ctx));
    else if (block.type === "quote") {
      const q = make("blockquote", "md-quote");
      q.append(...drawBlocks(block.blocks, ctx, text));
      out.push(q);
    } else if (block.type === "code") out.push(drawCode(block, ctx, text));
    else if (block.type === "table") out.push(drawTable(block, ctx));
    else if (block.type === "hr") out.push(make("hr", "md-hr"));
  }
  return out;
}

/** The blocks as plain lines (the first words of a card): no block marks, the bold, italic, strikethrough and code of the lines stay. */
function flatten(blocks, ctx, text) {
  const lines = [];
  for (const block of blocks) {
    if (block.type === "para") {
      for (const line of block.lines) lines.push(drawInline(line.nodes, ctx));
    } else if (block.type === "heading") lines.push(drawInline(block.nodes, ctx));
    else if (block.type === "list") for (const item of block.items) lines.push(drawInline(item.nodes, ctx));
    else if (block.type === "quote") lines.push(...flatten(block.blocks, ctx, text));
    else if (block.type === "code") for (const line of block.lines) lines.push([ctx.renderLiteral(text.slice(line.s, line.e), line.s)]);
    else if (block.type === "table") {
      const row = (cells) => cells.flatMap((cell, k) => (k ? [document.createTextNode(" · "), ...drawInline(cell.nodes, ctx)] : drawInline(cell.nodes, ctx)));
      lines.push(row(block.head));
      for (const cells of block.rows) lines.push(row(cells));
    }
  }
  return lines;
}

/**
 * Draw a text.
 * @param {string} text
 * @param {{renderText?: (piece: string, start: number) => Node|string, renderLiteral?: (piece: string, start: number) => Node|string,
 *   lists?: boolean, plain?: boolean}} [options]
 *   `renderText` draws a piece of plain text (its position in `text` is the second argument): the card's body uses it to turn
 *   "#12" into a link and to mark filled in references; the default is the text itself. `renderLiteral` draws text that must stay
 *   text (code, the words of a link): the marks of filled in references, no "#12" link; default is the text itself.
 *   `plain` draws no blocks and no anchors: the lines of a text with bold, italic, strikethrough and code (the preview of a card).
 * @returns {DocumentFragment}
 */
export function renderMarkdown(text, options = {}) {
  const { renderText = (piece) => document.createTextNode(piece), lists = true, plain = false } = options;
  const renderLiteral = options.renderLiteral ?? ((piece) => document.createTextNode(piece));
  const ctx = { renderText, renderLiteral, plain };
  const source = String(text ?? "");
  const blocks = parseMarkdown(source, { lists });
  const fragment = document.createDocumentFragment();
  if (!plain) {
    fragment.append(...drawBlocks(blocks, ctx, source));
    return fragment;
  }
  flatten(blocks, ctx, source).forEach((line, index) => {
    if (index) fragment.append(document.createTextNode("\n"));
    fragment.append(...line);
  });
  return fragment;
}
