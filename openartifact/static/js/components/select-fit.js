/* A select that is as wide as its longest choice, so its text is never cut ("Title and Body", "Artifact"): the browser sizes a
 * select by its widest option only when nothing narrows it, and a grid column or a narrow window does. `fitSelect` measures the
 * longest text the select can hold (its options, and `extra` for choices it may get later) with the select's own font and sets the
 * custom property `--select-min` that `select.field__control[data-fit]` uses as its minimum width (css/forms.css). `fitColumn` does the
 * same for a column of selects (a table of rows): the widest of them is the width of the column, a `--name` on the table.
 *
 *   fitSelect(select, { extra: ["string", "number"] });
 *   fitColumn(table, "--ag-col-type", table.querySelectorAll('select[data-input="type"]'), { extra });
 */

let canvas = null;

/** The width in px of the widest of `texts` in the font of `element`, plus its padding (the chevron's room is in the padding). */
export function widestText(element, texts) {
  canvas ??= document.createElement("canvas").getContext("2d");
  const style = getComputedStyle(element);
  canvas.font = style.font || `${style.fontSize} ${style.fontFamily}`;
  const widest = Math.max(0, ...texts.map((text) => canvas.measureText(text).width));
  return Math.ceil(widest + parseFloat(style.paddingLeft || "0") + parseFloat(style.paddingRight || "0") + 2);
}

/** Every text the select holds now, and `extra` ones it may hold later. */
const textsOf = (select, extra) => [...[...select.options].map((o) => o.text), ...extra];

/** Make a select as wide as its longest choice. */
export function fitSelect(select, { extra = [] } = {}) {
  select.dataset.fit = "";
  select.style.setProperty("--select-min", `${widestText(select, textsOf(select, extra))}px`);
}

/** Set `property` on `host` to the width of the widest select of a column (so a column of rows lines up and fits all of them). */
export function fitColumn(host, property, selects, { extra = [] } = {}) {
  const list = [...selects];
  if (!list.length) return;
  const width = Math.max(...list.map((select) => widestText(select, textsOf(select, extra))));
  host.style.setProperty(property, `${width}px`);
}

/** Do it again when the fonts are there (the first measure may have used a fallback font). */
export function refitWhenFontsLoad(again) {
  document.fonts?.ready?.then(again);
}
