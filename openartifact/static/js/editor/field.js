/* The markup every labelled control of the editor shares. */
import { infoTip } from "../components/info-tip.js";

let fieldCount = 0;

/**
 * A labelled control (the label is tied to it by id); `row` puts label and control on one line. `help` is the field's
 * explanation: it is not shown, a small (i) after the label opens it (components/info-tip.js) and the control is
 * described by it. `end` is what closes the row of the control (the bin of a removable setting): it sits after the control, in
 * a column of its own, so the control gives way to it and the two never overlap (ADR-074). `labelFor`: the element inside a
 * composite control (a number with its unit) the label belongs to.
 */
export function field(label, control, { row = false, help = null, end = null, labelFor = null } = {}) {
  const wrap = document.createElement("div");
  wrap.className = row ? "field field--row" : "field";
  const head = document.createElement("div");
  head.className = "field__head";
  const text = document.createElement("label");
  text.className = "field__label";
  text.textContent = label;
  const target = labelFor ?? control;
  target.id ||= `ge-field-${(fieldCount += 1)}`;
  text.htmlFor = target.id;
  head.append(text);
  if (help) {
    const tip = infoTip(help, { label });
    head.append(tip.button);
    target.setAttribute("aria-describedby", [target.getAttribute("aria-describedby"), tip.id].filter(Boolean).join(" "));
  }
  if (!end) {
    wrap.append(head, control);
    return wrap;
  }
  const line = document.createElement("div");
  line.className = "field__line";
  line.append(control, end);
  wrap.append(head, line);
  return wrap;
}
