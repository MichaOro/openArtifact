/* The markup every labelled control of the editor shares. */

let fieldCount = 0;

/** A labelled control (the label is tied to it by id); `row` puts label and control on one line. */
export function field(label, control, { row = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = row ? "field field--row" : "field";
  const text = document.createElement("label");
  text.className = "field__label";
  text.textContent = label;
  control.id ||= `ge-field-${(fieldCount += 1)}`;
  text.htmlFor = control.id;
  wrap.append(text, control);
  return wrap;
}
