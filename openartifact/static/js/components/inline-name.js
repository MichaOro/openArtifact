/* A text that is edited in place, the one inline editing of the application (lane names, graph names, the
 * identity of an agent): click it (or press Enter on it) to get a field with a check and a cross; Enter or the
 * check saves, Escape or the cross discards. A `multiline` text (a description) gets a text area: Enter saves,
 * Shift+Enter starts a new line. With `allowEmpty` an empty text is a value (else it discards); `emptyText` is
 * what an empty one shows.
 *
 * Normally the editor closes at once and onCommit runs on its own. With `keepOpenOnError`, onCommit
 * returns a promise: the editor stays open while it runs, and if it rejects the typed text stays and
 * the error message is shown under the field. */

import { icon } from "./icons.js";
import { t } from "../i18n.js";

let nextErrorId = 0;

export class InlineName {
  /**
   * @param {HTMLElement} element shows the name; becomes the editor while editing
   * @param {{label: string, onCommit: (name: string) => void|Promise<unknown>, maxLength?: number, keepOpenOnError?: boolean, multiline?: boolean, allowEmpty?: boolean, emptyText?: string}} options
   *   label: what the text is called, for assistive technology
   */
  constructor(element, { label, onCommit, maxLength = 255, keepOpenOnError = false, multiline = false, allowEmpty = false, emptyText = "" }) {
    this.element = element;
    this.onCommit = onCommit;
    this.maxLength = maxLength;
    this.keepOpenOnError = keepOpenOnError;
    this.multiline = multiline;
    this.allowEmpty = allowEmpty;
    this.emptyText = emptyText;
    this.text = element.textContent;
    element.classList.add("inline-name");
    element.dataset.ui = "custom"; // not a catalog button: it reads as the heading until it is hovered or focused
    element.dataset.uiReason = "inline rename";
    element.tabIndex = 0;
    element.setAttribute("role", "button");
    this.label = label;
    this.#show();
    element.addEventListener("click", () => this.edit());
    element.addEventListener("keydown", (event) => {
      if (event.target === element && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        this.edit();
      }
    });
  }

  /** Show another name (after a rename that happened elsewhere). */
  setText(text) {
    this.text = text;
    if (!this.editing) this.#show();
  }

  #show() {
    this.editing = false;
    const empty = !this.text && this.emptyText;
    this.element.replaceChildren(document.createTextNode(empty ? this.emptyText : this.text));
    this.element.classList.toggle("inline-name--empty", Boolean(empty));
    this.element.classList.remove("inline-name--editing");
    this.element.tabIndex = 0;
    this.element.setAttribute("role", "button");
    this.element.setAttribute("aria-label", t("components.inline_name.click_to_edit", { label: this.label, value: this.text || t("common.none") }));
  }

  /** Start editing (also what a click on the name does). */
  edit() {
    if (this.editing) return;
    this.editing = true;
    const input = document.createElement(this.multiline ? "textarea" : "input");
    input.className = `inline-name__input${this.multiline ? " inline-name__input--lines" : ""}`;
    if (this.multiline) input.rows = 3;
    else input.type = "text";
    input.maxLength = this.maxLength;
    input.value = this.text;
    input.autocomplete = "off";
    input.setAttribute("aria-label", this.label);
    const button = (name, label, onClick) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `icon-button icon-button--sm inline-name__${name}`;
      el.setAttribute("aria-label", label);
      el.title = label;
      el.append(icon(name));
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        onClick();
      });
      return el;
    };
    const error = document.createElement("p");
    error.className = "inline-name__error";
    error.id = `inline-name-error-${(nextErrorId += 1)}`;
    error.setAttribute("role", "alert");
    error.hidden = true;
    let saving = false;
    const commit = async () => {
      const name = input.value.trim();
      const discard = !name && !this.allowEmpty;
      if (!this.keepOpenOnError || discard || name === this.text) {
        this.#show();
        this.element.focus(); // the field that had focus is gone
        if (!discard && name !== this.text) this.onCommit(name); // the caller shows the saved text (setText)
        return;
      }
      if (saving) return;
      saving = true;
      try {
        await this.onCommit(name);
        this.text = name;
        this.#show();
        this.element.focus();
      } catch (failure) {
        error.textContent = failure.detail ?? (failure.message || t("components.action_dialog.did_not_work_please_try"));
        error.hidden = false;
        input.setAttribute("aria-invalid", "true");
        input.setAttribute("aria-describedby", error.id);
        input.focus();
      } finally {
        saving = false;
      }
    };
    input.addEventListener("input", () => {
      error.hidden = true;
      input.removeAttribute("aria-invalid");
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !(this.multiline && event.shiftKey)) {
        event.preventDefault();
        commit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        this.#show();
        this.element.focus();
      }
    });
    this.element.classList.add("inline-name--editing");
    this.element.removeAttribute("role");
    this.element.removeAttribute("tabindex");
    this.element.removeAttribute("aria-label");
    this.element.replaceChildren(input, button("check", t("common.save"), commit), button("x", t("index.discard"), () => {
        this.#show();
        this.element.focus();
      }), error);
    input.focus();
    input.select();
  }
}
