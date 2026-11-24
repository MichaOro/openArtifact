/* One setting that has a parent supplying its value (ADR-053): the row says whether the value is *inherited* (shown
 * with where it comes from), *overridden* (the node's own, with the control) or *not set* (the parent has none), and
 * lets the user take over and give back.
 *
 * Overriding is additive: pressing "Override" only opens the control, with the parent's value as what it starts with;
 * nothing is stored until the user commits a value (Enter, or leaving a changed field). Giving back deletes the node's
 * value, which restores inheritance. The row stores nothing itself: `makeControl`'s control saves, `remove` clears.
 * Chips and the bin are the application's own (`ag-chip`, `icon-button`). */
import { chip, el } from "../agents/view.js";
import { icon } from "./icons.js";
import { t } from "../i18n.js";

/**
 * @param {object} options
 * @param {string} options.key the setting's key
 * @param {string} options.label
 * @param {string} options.source who supplies the value ("Agent")
 * @param {string|null} options.inheritedText the parent's value as shown, null when it has none
 * @param {boolean} options.overridden the node stores its own value
 * @param {boolean} options.editing the control is open without a stored value (an override being made)
 * @param {(options: {unsaved: boolean}) => {input: HTMLElement, error: HTMLElement, status: HTMLElement}} options.makeControl
 * @param {() => void} options.begin "Override" was pressed
 * @param {() => void} options.cancel an override being made was abandoned
 * @param {() => Promise<string|null>} options.remove delete the node's value; resolves to a refusal or null
 * @param {boolean} [options.wide] a long control (a prompt) takes the whole row
 */
export function overrideRow({ key, label, source, inheritedText, overridden, editing, makeControl, begin, cancel, remove, wide = false }) {
  const state = overridden ? "overridden" : editing ? "editing" : inheritedText === null ? "not-set" : "inherited";
  const row = el("div", "ov");
  row.dataset.setting = key;
  row.dataset.state = state;
  if (wide) row.classList.add("ov--wide");
  const head = el("div", "ov__head");
  const chipText = { overridden: t("components.override_row.overridden"), editing: t("components.override_row.new_override"), "not-set": t("components.override_row.not_set"), inherited: t("components.override_row.inherited") }[state];
  const tone = state === "overridden" ? "accent" : state === "editing" ? "warn" : "";
  head.append(el("span", "ov__label", label), chip(chipText, tone));

  const action = (glyph, text, aria, className) => {
    const button = el("button", className);
    button.type = "button";
    button.dataset.focusKey = `override-${key}`;
    button.title = aria;
    button.setAttribute("aria-label", aria);
    if (glyph) button.append(icon(glyph));
    if (text) button.append(document.createTextNode(text));
    return button;
  };
  const note = (text) => {
    const line = el("p", "ov__value", text);
    line.title = text; // a long value is cut to one line by the style; the whole of it stays in the tooltip
    return line;
  };

  if (state === "inherited" || state === "not-set") {
    const button = action(null, state === "not-set" ? "Set a value" : "Override", state === "not-set" ? `Set ${label}` : `Override ${label} in this node`, "button button--ghost button--sm");
    button.addEventListener("click", begin);
    head.append(button);
    row.append(head, note(inheritedText === null ? t("components.override_row.not_set") : `${source}: ${inheritedText}`));
    return row;
  }

  const control = makeControl({ unsaved: state === "editing" });
  control.input.setAttribute("aria-label", label);
  control.input.dataset.focusKey = `override-input-${key}`;
  if (state === "editing") {
    const stop = action("x", null, t("components.override_row.cancel_overriding_label", { label }), "icon-button icon-button--sm");
    stop.addEventListener("click", cancel);
    head.append(stop);
    window.requestAnimationFrame(() => control.input.focus());
  } else {
    const bin = action("trash", null, t("components.override_row.use_source_value", { source: source.toLowerCase(), label }), "icon-button icon-button--sm is-danger");
    bin.addEventListener("click", async () => {
      const message = await remove();
      if (message) {
        control.error.textContent = message;
        control.error.hidden = false;
      }
    });
    head.append(bin);
  }
  row.append(head, control.input, control.error, control.status);
  if (inheritedText !== null) row.append(note(`${source}: ${inheritedText}`));
  return row;
}
