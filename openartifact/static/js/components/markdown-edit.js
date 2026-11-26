/* What the buttons of the Markdown bar do to a text (ADR-077). Pure: a text and a selection go in, an edit comes out
 *   {from, to, insert, selStart, selEnd}
 * "replace text[from, to) by `insert`, then select [selStart, selEnd)". The bar applies it through the browser's own editing (so the
 * undo of the textarea keeps working); the tests read it as it is. */

import { safeHref } from "./markdown.js";

const BLANK = /\s/;

/** How many `char` stand in a row, going from `index` to the right (step 1) or to the left (step -1). */
function run(text, index, step, char) {
  let n = 0;
  while (text[index + n * step] === char) n += 1;
  return n;
}

/** Whether the text around the selection [start, end) already carries the marker (outside of it). */
function wrappedOutside(text, start, end, marker) {
  const size = marker.length;
  if (marker === "*") {
    const left = run(text, start - 1, -1, "*");
    const right = run(text, end, 1, "*");
    return Math.min(left, right) % 2 === 1; // ** is bold, *** is bold and italic
  }
  if (marker === "**") return Math.min(run(text, start - 1, -1, "*"), run(text, end, 1, "*")) >= 2;
  return text.slice(start - size, start) === marker && text.slice(end, end + size) === marker;
}

/** Whether the selected text itself starts and ends with the marker (the selection took the markers along). */
function wrappedInside(selected, marker) {
  if (marker === "*" || marker === "**") {
    const left = run(selected, 0, 1, "*");
    const right = run(selected, selected.length - 1, -1, "*");
    if (left + right >= selected.length) return false;
    return marker === "*" ? Math.min(left, right) % 2 === 1 : Math.min(left, right) >= 2;
  }
  return selected.length > 2 * marker.length && selected.startsWith(marker) && selected.endsWith(marker);
}

/**
 * Put `marker` around the selection, or take it away when the selection is wrapped already. Blanks at the ends of the
 * selection stay outside of the markers (an emphasis may not open or close at a blank). Nothing selected: the markers go in at the
 * caret, which ends between them.
 * @param {string} text
 * @param {number} start
 * @param {number} end
 * @param {string} marker "**", "*" or "~~"
 */
export function toggleWrap(text, start, end, marker) {
  const size = marker.length;
  const selected = text.slice(start, end);
  if (selected && wrappedInside(selected, marker)) {
    const inner = selected.slice(size, selected.length - size);
    return { from: start, to: end, insert: inner, selStart: start, selEnd: start + inner.length };
  }
  if (wrappedOutside(text, start, end, marker) && selected.trim()) {
    return { from: start - size, to: end + size, insert: selected, selStart: start - size, selEnd: start - size + selected.length };
  }
  if (!selected.trim()) {
    return { from: start, to: end, insert: marker + marker, selStart: start + size, selEnd: start + size };
  }
  let from = start;
  let to = end;
  while (BLANK.test(text[from])) from += 1;
  while (BLANK.test(text[to - 1])) to -= 1;
  const insert = marker + text.slice(from, to) + marker;
  return { from, to, insert, selStart: from + size, selEnd: from + size + (to - from) };
}

/** The lines the selection touches: where they start and stop in the text, and the lines themselves. */
function lineRange(text, start, end) {
  const from = text.lastIndexOf("\n", start - 1) + 1;
  let stop = end > start && text[end - 1] === "\n" ? end - 1 : end; // a selection that ends at the start of a line leaves that line out
  const next = text.indexOf("\n", stop);
  stop = next === -1 ? text.length : next;
  return { from, stop, lines: text.slice(from, stop).split("\n") };
}

/** The edit that replaces the lines [from, stop) by `lines`: the selection covers them, or the caret keeps its place on one line. */
function lineEdit(text, start, end, { from, stop, lines }, changed) {
  const insert = changed.join("\n");
  if (start !== end || lines.length > 1) return { from, to: stop, insert, selStart: from, selEnd: from + insert.length };
  const caret = Math.min(Math.max(start + insert.length - (stop - from), from), from + insert.length); // one line: the caret moves with the marker
  return { from, to: stop, insert, selStart: caret, selEnd: caret };
}

const BULLET = /^( *)[-*+] /;
const NUMBER = /^( *)\d{1,9}\. /;
const QUOTED = /^ {0,3}> ?/;
const HEADED = /^ {0,3}#{1,6} +/;

/**
 * Make the lines the selection touches a bullet list ("- "), or take the bullets away when every one of them is an item. Empty lines are left
 * alone, except that the caret on an empty line starts an item there. A numbered line becomes a bullet.
 */
export function toggleList(text, start, end) {
  const range = lineRange(text, start, end);
  const filled = range.lines.filter((line) => line.trim());
  const allItems = filled.length > 0 && filled.every((line) => BULLET.test(line));
  const changed = range.lines.map((line) => {
    if (allItems) return line.replace(BULLET, "$1");
    if (!line.trim() && range.lines.length > 1) return line;
    if (BULLET.test(line)) return line;
    return NUMBER.test(line) ? line.replace(NUMBER, "$1- ") : `- ${line}`;
  });
  return lineEdit(text, start, end, range, changed);
}

/** The same for a numbered list ("1. ", "2. " ...): the number counts the lines that are filled in. A bullet line becomes a numbered one. */
export function toggleOrdered(text, start, end) {
  const range = lineRange(text, start, end);
  const filled = range.lines.filter((line) => line.trim());
  const allItems = filled.length > 0 && filled.every((line) => NUMBER.test(line));
  let n = 0;
  const changed = range.lines.map((line) => {
    if (allItems) return line.replace(NUMBER, "$1");
    if (!line.trim() && range.lines.length > 1) return line;
    n += 1;
    if (NUMBER.test(line)) return line;
    return BULLET.test(line) ? line.replace(BULLET, `$1${n}. `) : `${n}. ${line}`;
  });
  return lineEdit(text, start, end, range, changed);
}

/** A quote ("> ") before the lines of the selection, or not any more when every line is quoted. */
export function toggleQuote(text, start, end) {
  const range = lineRange(text, start, end);
  const filled = range.lines.filter((line) => line.trim());
  const allQuoted = filled.length > 0 && filled.every((line) => QUOTED.test(line));
  const changed = range.lines.map((line) => {
    if (allQuoted) return line.replace(QUOTED, "");
    if (!line.trim()) return range.lines.length > 1 ? ">" : "> ";
    return QUOTED.test(line) ? line : `> ${line}`;
  });
  return lineEdit(text, start, end, range, changed);
}

/** The level of the heading the first line of the selection has (0: none): one click goes none, #, ##, ###, none again. */
export function headingLevel(text, start) {
  const line = text.slice(text.lastIndexOf("\n", start - 1) + 1).split("\n")[0];
  const match = /^ {0,3}(#{1,6})[ \t]/.exec(line);
  return match ? match[1].length : 0;
}

/** The next heading level for the lines of the selection: none, #, ##, ###, none (a deeper heading starts the cycle again at none). */
export function cycleHeading(text, start, end) {
  const range = lineRange(text, start, end);
  const level = headingLevel(text, start);
  const next = level >= 3 ? 0 : level + 1;
  const changed = range.lines.map((line) => {
    if (!line.trim() && range.lines.length > 1) return line;
    const bare = line.replace(HEADED, "");
    return next ? `${"#".repeat(next)} ${bare}` : bare;
  });
  return lineEdit(text, start, end, range, changed);
}

const FENCE_LINE = /^ {0,3}(`{3,}|~{3,})[ \t]*[^\s`]*[ \t]*$/;

/** The lines of the selection inside a code fence, or the fence taken away when they are inside one (or the selection holds it). */
export function toggleCodeBlock(text, start, end) {
  const range = lineRange(text, start, end);
  const { from, stop, lines } = range;
  const before = from > 0 ? text.slice(text.lastIndexOf("\n", from - 2) + 1, from - 1) : null;
  const afterStart = stop < text.length ? stop + 1 : -1;
  const after = afterStart >= 0 ? text.slice(afterStart, text.indexOf("\n", afterStart) === -1 ? text.length : text.indexOf("\n", afterStart)) : null;
  if (lines.length >= 2 && FENCE_LINE.test(lines[0]) && FENCE_LINE.test(lines.at(-1))) {
    const inner = lines.slice(1, -1).join("\n");
    return { from, to: stop, insert: inner, selStart: from, selEnd: from + inner.length };
  }
  if (before !== null && after !== null && FENCE_LINE.test(before) && FENCE_LINE.test(after)) {
    const open = from - 1 - before.length;
    const closeEnd = afterStart + after.length;
    const inner = lines.join("\n");
    return { from: Math.max(open, 0), to: closeEnd, insert: inner, selStart: Math.max(open, 0), selEnd: Math.max(open, 0) + inner.length };
  }
  const body = lines.join("\n");
  const insert = `\`\`\`\n${body}\n\`\`\``;
  return body.trim()
    ? { from, to: stop, insert, selStart: from + 4, selEnd: from + 4 + body.length }
    : { from, to: stop, insert, selStart: from + 4, selEnd: from + 4 };
}

/** The link `[label](address)` the caret (or the start of the selection) is in, on its line: where it is and what it holds, or null. */
export function findLink(text, caret) {
  const lineStart = text.lastIndexOf("\n", caret - 1) + 1;
  const nl = text.indexOf("\n", caret);
  const lineEnd = nl === -1 ? text.length : nl;
  const line = text.slice(lineStart, lineEnd);
  if (line.length > 1500) return null;
  for (const match of line.matchAll(/\[([^\]\n]*)\]\(([^)\s]*)\)/g)) {
    const from = lineStart + match.index;
    const to = from + match[0].length;
    if (caret >= from && caret <= to) return { from, to, label: match[1], address: match[2] };
  }
  return null;
}

/**
 * What a person typed as an address, made a usable one: `{href}`, or `{error}` ("empty" or "invalid"). A bare "www.x.de" or "x.de/y" gets
 * https://, "a@b.de" gets mailto:; only http, https and mailto are links.
 */
export function normalizeAddress(input) {
  const typed = String(input ?? "").trim();
  if (!typed) return { error: "empty" };
  let candidate = typed;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(typed)) {
    if (/^[^\s@/]+@[^\s@/]+\.[^\s@/]+$/.test(typed)) candidate = `mailto:${typed}`;
    else if (/^[^\s/@]+\.[^\s/@]+/.test(typed)) candidate = `https://${typed}`;
  }
  const href = safeHref(candidate);
  return href ? { href } : { error: "invalid" };
}

/**
 * The edit that writes `[label](href)`: in place of the link the caret is in (`existing`, from findLink), else of the selection [start, end).
 * An empty label shows the address; brackets in the label become parentheses (a label never closes the link).
 */
export function linkEdit(text, start, end, label, href, existing = null) {
  const shown = String(label ?? "").replace(/\s*\n\s*/g, " ").replace(/\[/g, "(").replace(/\]/g, ")").trim() || href;
  const insert = `[${shown}](${href})`;
  const from = existing ? existing.from : start;
  const to = existing ? existing.to : end;
  return { from, to, insert, selStart: from + insert.length, selEnd: from + insert.length };
}
