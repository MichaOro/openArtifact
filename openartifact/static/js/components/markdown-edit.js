/* What the buttons of the Markdown bar do to a text (ADR-077). Pure: a text and a selection go in, an edit comes out
 *   {from, to, insert, selStart, selEnd}
 * "replace text[from, to) by `insert`, then select [selStart, selEnd)". The bar applies it through the browser's own editing (so the
 * undo of the textarea keeps working); the tests read it as it is. */

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

/**
 * Make the lines the selection touches a bullet list ("- "), or take the bullets away when every one of them is an item. Empty lines are left
 * alone, except that the caret on an empty line starts an item there.
 */
export function toggleList(text, start, end) {
  const from = text.lastIndexOf("\n", start - 1) + 1;
  let stop = end > start && text[end - 1] === "\n" ? end - 1 : end; // a selection that ends at the start of a line leaves that line out
  const next = text.indexOf("\n", stop);
  stop = next === -1 ? text.length : next;
  const lines = text.slice(from, stop).split("\n");
  const filled = lines.filter((line) => line.trim());
  const allItems = filled.length > 0 && filled.every((line) => /^ *- /.test(line));
  const changed = lines.map((line) => {
    if (allItems) return line.replace(/^( *)- /, "$1");
    if (!line.trim() && lines.length > 1) return line;
    return /^ *- /.test(line) ? line : `- ${line}`;
  });
  const insert = changed.join("\n");
  if (start !== end) return { from, to: stop, insert, selStart: from, selEnd: from + insert.length };
  const caret = Math.min(Math.max(start + insert.length - (stop - from), from), from + insert.length); // one line: the caret moves with the bullet
  return { from, to: stop, insert, selStart: caret, selEnd: caret };
}
