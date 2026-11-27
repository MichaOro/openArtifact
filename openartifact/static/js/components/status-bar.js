/* The status bar in the corner of the editor's canvas: ONE small list of entries (the eye of the observe mode, the shield of the guards, the
 * "+" menu), each with a fixed place in the order and shown only while it is active. The "+" is always the last, at the right edge; an entry
 * that is not shown takes no room, so the others close up, and one that appears takes its own place in the order. More entries are one line
 * of `add`. The order of the elements in the page is the order on the screen (so the keyboard follows the eye). The arrangement is
 * status-bar-model.js. */
import { icon } from "./icons.js";
import { arrange, shownKeys } from "./status-bar-model.js";

export class StatusBar {
  /** @param {HTMLElement} row the element holding the entries */
  constructor(row) {
    this.row = row;
    this.entries = new Map();
  }

  /**
   * Add an entry. Give the `element` it already has in the page (the "+" and the shield are in the markup), or an `icon` and a `label` and the
   * bar makes a quiet icon button for it.
   * @param {{key: string, order: number, element?: HTMLElement, icon?: string, label?: string, onClick?: (button: HTMLElement) => void,
   *   visible?: boolean}} entry
   * @returns {HTMLElement} the element of the entry
   */
  add({ key, order, element = null, icon: name = null, label = "", onClick = null, visible = false }) {
    let el = element;
    if (!el) {
      el = document.createElement("button");
      el.type = "button";
      el.className = "icon-button status-bar__entry";
      el.setAttribute("aria-haspopup", "dialog");
      el.setAttribute("aria-expanded", "false");
      el.append(icon(name));
      el.addEventListener("pointerdown", (event) => event.stopPropagation());
      if (onClick) el.addEventListener("click", () => onClick(el));
    }
    el.dataset.statusEntry = key;
    this.entries.set(key, { key, order, visible, element: el });
    this.label(key, label);
    this.#apply();
    return el;
  }

  /** Show or hide an entry (a hidden one takes no room). */
  set(key, visible) {
    const entry = this.entries.get(key);
    if (!entry || entry.visible === Boolean(visible)) return;
    entry.visible = Boolean(visible);
    this.#apply();
  }

  /** The text of an entry's tooltip and accessible name. */
  label(key, text) {
    const entry = this.entries.get(key);
    if (!entry || !text) return;
    entry.element.title = text;
    entry.element.setAttribute("aria-label", text);
  }

  /** The keys of the entries shown, left to right. */
  get shown() {
    return shownKeys([...this.entries.values()]);
  }

  #apply() {
    const sorted = arrange([...this.entries.values()]);
    for (const entry of sorted) {
      entry.element.hidden = !entry.visible;
      entry.element.style.order = String(entry.order);
    }
    this.row.append(...sorted.map((entry) => entry.element)); // the order in the page is the order on the screen
  }
}
