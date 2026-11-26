/* The markup every labelled control of the editor shares. */
import { infoTip } from "../components/info-tip.js";

let fieldCount = 0;

/**
 * A labelled control (the label is tied to it by id); `row` puts label and control on one line. `help` is the field's
 * explanation: it is not shown, a small (i) after the label opens it (components/info-tip.js) and the control is
 * described by it.
 */
export function field(label, control, { row = false, help = null } = {}) {
  const wrap = document.createElement("div");
  wrap.className = row ? "field field--row" : "field";
  const head = document.createElement("div");
  head.className = "field__head";
  const text = document.createElement("label");
  text.className = "field__label";
  text.textContent = label;
  control.id ||= `ge-field-${(fieldCount += 1)}`;
  text.htmlFor = control.id;
  head.append(text);
  if (help) {
    const tip = infoTip(help, { label });
    head.append(tip.button);
    control.setAttribute("aria-describedby", [control.getAttribute("aria-describedby"), tip.id].filter(Boolean).join(" "));
  }
  wrap.append(head, control);
  return wrap;
}
