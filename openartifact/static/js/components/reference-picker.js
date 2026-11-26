/* "#" references in a textarea: typing "#" (at the start or after whitespace) opens a small menu
 * with the artifacts of the board; typing digits/letters filters it; Enter/Tab inserts "#<number>".
 * Focus stays in the textarea (aria-activedescendant), so typing is never interrupted.
 * Generic: it only gets a function that returns {number, title, hue} items. */

import { placePopover } from "./popover.js";
import { t } from "../i18n.js";

const TRIGGER = /(^|\s)#([^\s#]*)$/;

export class ReferencePicker {
  /**
   * @param {object} options
   * @param {HTMLTextAreaElement} options.textarea
   * @param {HTMLElement} options.container element inside the dialog that hosts the menu
   * @param {() => {number: number, title: string, hue?: string}[]} options.getItems
   */
  constructor({ textarea, container, getItems }) {
    this.textarea = textarea;
    this.getItems = getItems;
    this.active = 0;
    this.matches = [];
    this.start = -1; // index of the "#" being completed

    this.el = document.createElement("div");
    this.el.className = "popover popover--reference";
    this.el.id = `${textarea.id}-references`;
    this.el.setAttribute("role", "listbox");
    this.el.setAttribute("aria-label", t("components.reference_picker.reference_artifact"));
    this.el.hidden = true;
    container.append(this.el);
    textarea.setAttribute("aria-autocomplete", "list");
    textarea.setAttribute("aria-controls", this.el.id);

    textarea.addEventListener("input", () => this.#update());
    textarea.addEventListener("keydown", (event) => this.#onKeydown(event));
    textarea.addEventListener("blur", () => this.close());
    textarea.addEventListener("click", () => this.#update());
    // mousedown (not click): the textarea must not lose focus first
    this.el.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const option = event.target.closest("[data-index]");
      if (option) this.#choose(Number(option.dataset.index));
    });
  }

  get isOpen() {
    return !this.el.hidden;
  }

  close() {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.textarea.removeAttribute("aria-activedescendant");
    this.textarea.setAttribute("aria-expanded", "false");
  }

  #update() {
    const caret = this.textarea.selectionStart;
    const before = this.textarea.value.slice(0, caret);
    const match = TRIGGER.exec(before);
    if (!match || this.textarea.selectionEnd !== caret) return this.close();
    const query = match[2].toLowerCase();
    this.start = caret - query.length - 1;
    this.matches = this.getItems().filter(
      (item) => String(item.number).startsWith(query.replace(/^0+/, "")) || item.title.toLowerCase().includes(query),
    );
    if (this.matches.length === 0) return this.close();
    this.active = 0;
    this.#render();
    this.#position();
  }

  #render() {
    this.el.replaceChildren(
      ...this.matches.map((item, i) => {
        const option = document.createElement("div");
        option.id = `${this.el.id}-${i}`;
        option.className = "popover__option popover__option--reference";
        option.setAttribute("role", "option");
        option.dataset.index = String(i);
        if (item.hue) option.dataset.laneHue = String(item.hue);
        const number = document.createElement("span");
        number.className = "popover__number";
        number.textContent = `#${item.number}`;
        option.append(number, document.createTextNode(item.title));
        option.title = `#${item.number} ${item.title}`;
        return option;
      }),
    );
    this.el.hidden = false;
    this.textarea.setAttribute("aria-expanded", "true");
    this.#highlight();
  }

  #highlight() {
    [...this.el.children].forEach((option, i) => {
      option.setAttribute("aria-selected", String(i === this.active));
      if (i === this.active) {
        this.textarea.setAttribute("aria-activedescendant", option.id);
        option.scrollIntoView({ block: "nearest" });
      }
    });
  }

  #choose(index) {
    const item = this.matches[index];
    if (!item) return;
    const caret = this.textarea.selectionStart;
    const text = `#${item.number} `;
    this.textarea.setRangeText(text, this.start, caret, "end");
    this.close();
    this.textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  #onKeydown(event) {
    if (!this.isOpen) return;
    const last = this.matches.length - 1;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        this.active = this.active >= last ? 0 : this.active + 1;
        this.#highlight();
        break;
      case "ArrowUp":
        event.preventDefault();
        this.active = this.active <= 0 ? last : this.active - 1;
        this.#highlight();
        break;
      case "Enter":
      case "Tab":
        event.preventDefault();
        this.#choose(this.active);
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation(); // close the menu, not the dialog
        this.close();
        break;
      default:
    }
  }

  /** Place the menu under the caret (a hidden mirror of the textarea measures where it is). */
  #position() {
    const ta = this.textarea;
    const style = getComputedStyle(ta);
    const mirror = document.createElement("div");
    for (const prop of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "padding", "border", "boxSizing", "whiteSpace", "wordWrap", "overflowWrap", "tabSize"]) {
      mirror.style[prop] = style[prop];
    }
    mirror.style.cssText += `;position:fixed;visibility:hidden;top:0;left:0;width:${ta.clientWidth + parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth)}px;white-space:pre-wrap;overflow-wrap:break-word`;
    mirror.textContent = ta.value.slice(0, this.start);
    const marker = document.createElement("span");
    marker.textContent = "#";
    mirror.append(marker);
    document.body.append(mirror);
    const markerBox = marker.getBoundingClientRect();
    const mirrorBox = mirror.getBoundingClientRect();
    mirror.remove();
    const box = ta.getBoundingClientRect();
    placePopover(this.el, (menu) => {
      const top = box.top + (markerBox.bottom - mirrorBox.top) - ta.scrollTop + 4;
      return {
        left: box.left + (markerBox.left - mirrorBox.left) - ta.scrollLeft,
        top,
        flipTop: top - menu.height - markerBox.height - 8,
      };
    });
  }
}
