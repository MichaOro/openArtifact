/* A combobox: one text field with a list of choices under it. Typing narrows the list (name, then description; see
 * combobox-model.js), the arrow keys move through it, Enter takes the highlighted choice, Escape closes the list (and
 * only the list), a click on a choice takes it. The list is a popup next to the field, so a dialog does not clip it. It is
 * the ARIA 1.2 combobox with a listbox: the field has role=combobox and names the highlighted option with
 * aria-activedescendant. One component for every "choose one of many by typing" (the attach dialog of the guards).
 *
 *   const box = new Combobox(host, {label: "Guard", options: [{value, label, description?, keywords?}], placeholder, onChange});
 *   box.selected  // the chosen option or null (typing again clears it)
 */
import { icon } from "./icons.js";
import { placePopover } from "./popover.js";
import { t } from "../i18n.js";
import { filterOptions, moveHighlight } from "./combobox-model.js";

let count = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class Combobox {
  /**
   * @param {HTMLElement} host where the field goes
   * @param {{label: string, options: {value: string, label: string, description?: string, keywords?: string}[], placeholder?: string,
   *   onChange?: (option: object|null) => void, emptyText?: string}} config
   */
  constructor(host, { label, options, placeholder = "", onChange = () => {}, emptyText = "" }) {
    this.options = options;
    this.onChange = onChange;
    this.emptyText = emptyText;
    this.selected = null;
    this.shown = [];
    this.active = -1;
    count += 1;
    this.id = `combobox-${count}`;
    this.el = make("div", "combobox");
    const field = make("div", "combobox__field");
    this.input = Object.assign(make("input", "field__control combobox__input"), { type: "text", placeholder, autocomplete: "off", spellcheck: false });
    this.input.id = `${this.id}-input`;
    this.input.setAttribute("role", "combobox");
    this.input.setAttribute("aria-autocomplete", "list");
    this.input.setAttribute("aria-expanded", "false");
    this.input.setAttribute("aria-controls", `${this.id}-list`);
    this.input.setAttribute("aria-label", label);
    this.toggle = make("button", "icon-button icon-button--sm combobox__toggle");
    this.toggle.type = "button";
    this.toggle.tabIndex = -1;
    this.toggle.setAttribute("aria-label", t("components.combobox.show_all"));
    this.toggle.append(icon("chevron-down"));
    field.append(this.input, this.toggle);
    this.list = make("ul", "popover combobox__list");
    this.list.id = `${this.id}-list`;
    this.list.setAttribute("role", "listbox");
    this.list.setAttribute("aria-label", label);
    this.list.hidden = true;
    this.el.append(field);
    host.append(this.el);
    this.input.addEventListener("input", () => {
      this.#select(null);
      this.#open();
    });
    this.input.addEventListener("focus", () => this.input.select());
    this.input.addEventListener("keydown", (event) => this.#onKeydown(event));
    this.input.addEventListener("blur", () => this.close());
    this.toggle.addEventListener("pointerdown", (event) => event.preventDefault()); // keep the focus in the field
    this.toggle.addEventListener("click", () => (this.isOpen ? this.close() : (this.input.focus(), this.#open(true))));
    window.addEventListener("resize", () => this.close());
  }

  get isOpen() {
    return !this.list.hidden;
  }

  focus() {
    this.input.focus();
  }

  /** Replace the choices (the chosen one stays if it is still there). */
  setOptions(options) {
    this.options = options;
    if (this.selected && !options.some((o) => o.value === this.selected.value)) this.#select(null);
    if (this.isOpen) this.#open();
  }

  close() {
    if (!this.isOpen) return;
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.active = -1;
  }

  /** @param {boolean} all show every choice, whatever the text says (the arrow button) */
  #open(all = false) {
    this.shown = filterOptions(this.options, all || this.selected ? "" : this.input.value);
    const host = this.el.closest("dialog[open]") ?? document.body; // a dialog is in the top layer: the list goes in it
    if (this.list.parentElement !== host) host.append(this.list);
    this.list.replaceChildren(
      ...(this.shown.length ? this.shown.map((option, i) => this.#row(option, i)) : [make("li", "combobox__empty", this.emptyText || t("components.combobox.no_match"))]),
    );
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    this.active = this.selected ? this.shown.findIndex((o) => o.value === this.selected.value) : this.shown.length ? 0 : -1;
    this.#highlight();
    const rect = this.input.getBoundingClientRect();
    this.list.style.width = `${rect.width}px`;
    placePopover(this.list, (size) => ({ left: rect.left, top: rect.bottom + 4, flipTop: rect.top - size.height - 4 }));
  }

  #row(option, index) {
    const row = make("li", "popover__option combobox__option");
    row.id = `${this.id}-option-${index}`;
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(this.selected?.value === option.value));
    row.dataset.value = option.value;
    row.append(make("span", "combobox__name", option.label));
    if (option.description) row.append(make("span", "combobox__description", option.description));
    row.addEventListener("mousedown", (event) => event.preventDefault()); // a click must not blur the field first
    row.addEventListener("click", () => {
      this.#select(option);
      this.close();
      this.input.focus();
    });
    return row;
  }

  #highlight() {
    [...this.list.querySelectorAll('[role="option"]')].forEach((row, i) => {
      row.classList.toggle("is-active", i === this.active);
      if (i === this.active) {
        this.input.setAttribute("aria-activedescendant", row.id);
        row.scrollIntoView({ block: "nearest" });
      }
    });
    if (this.active < 0) this.input.removeAttribute("aria-activedescendant");
  }

  #select(option) {
    const changed = (this.selected?.value ?? null) !== (option?.value ?? null);
    this.selected = option;
    if (option) this.input.value = option.label;
    if (changed) this.onChange(option);
  }

  #onKeydown(event) {
    if (["ArrowDown", "ArrowUp"].includes(event.key) && !this.isOpen) {
      event.preventDefault();
      this.#open(true);
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) && this.isOpen) {
      if ((event.key === "Home" || event.key === "End") && !event.ctrlKey) return; // the caret in the text
      event.preventDefault();
      this.active = moveHighlight(this.active, event.key, this.shown.length);
      this.#highlight();
      return;
    }
    if (event.key === "Enter" && this.isOpen && this.active >= 0) {
      event.preventDefault(); // takes the choice, does not submit the dialog's form
      this.#select(this.shown[this.active]);
      this.close();
      return;
    }
    if (event.key === "Escape" && this.isOpen) {
      event.preventDefault();
      event.stopPropagation(); // only the list closes, not the dialog it is in
      this.close();
    }
  }
}
