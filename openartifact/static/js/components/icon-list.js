/* The base of every flexible icon list: the canvas corner's status bar (status-bar.js) and the icons in the corner of a node card
 * (card-icons.js) are variants of it. One rule for all of them: every entry has a fixed place in the order, only an active entry is drawn, the
 * drawn ones sit next to each other with no gap (never a placeholder for an inactive one), the list is anchored at the right edge and grows to
 * the left (the host's CSS does the anchoring; this class only owns the order of the children), and an entry is declared with one line of
 * `add`. The order of the elements in the page is the order on the screen, so the keyboard follows the eye. What differs is a variant
 * (`defineVariant` in icon-list-model.js): the whitelist of keys, the order table, the size and the host. */
import { icon } from "./icons.js";
import { arrange, placeOf, shownKeys } from "./icon-list-model.js";

export class IconList {
  /**
   * @param {HTMLElement|null} row the element holding the entries (a variant whose host appears later sets `row` when it has one)
   * @param {ReturnType<typeof import("./icon-list-model.js").defineVariant>} variant
   */
  constructor(row, variant) {
    this.row = row;
    this.variant = variant;
    this.entries = new Map();
  }

  /**
   * Add an entry (a second call with the same key replaces it). Give the `element` it already has, or an `icon` and a `label` and the list
   * makes a quiet icon button for it.
   * @param {{key: string, order?: number, element?: HTMLElement|null, icon?: string|null, label?: string,
   *   onClick?: ((button: HTMLElement) => void)|null, visible?: boolean}} entry
   * @returns {HTMLElement} the element of the entry
   */
  add({ key, order, element = null, icon: name = null, label = "", onClick = null, visible = false }) {
    const place = placeOf(this.variant, key, order);
    const old = this.entries.get(key);
    if (old && old.element !== element) old.element.remove();
    let el = element;
    if (!el) {
      el = document.createElement("button");
      el.type = "button";
      el.className = `${this.variant.buttonClass} icon-list__entry`;
      el.setAttribute("aria-haspopup", "dialog");
      el.setAttribute("aria-expanded", "false");
      el.append(icon(name));
      el.addEventListener("pointerdown", (event) => event.stopPropagation());
      if (onClick) el.addEventListener("click", () => onClick(el));
    }
    const { attrs } = this.variant;
    el.dataset[attrs.key] = key;
    if (attrs.order) el.dataset[attrs.order] = String(place);
    this.entries.set(key, { key, order: place, visible, element: el });
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

  /** Take an entry away altogether: the others close up. */
  remove(key) {
    const entry = this.entries.get(key);
    if (!entry) return;
    entry.element.remove();
    this.entries.delete(key);
    this.#apply();
  }

  /** The element of an entry, if it is in the list. */
  element(key) {
    return this.entries.get(key)?.element ?? null;
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
    const detach = this.variant.inactive === "detach";
    for (const entry of sorted) {
      if (!detach) entry.element.hidden = !entry.visible;
      if (this.variant.cssOrder) entry.element.style.order = String(entry.order);
    }
    if (!this.row) return;
    if (detach) for (const entry of sorted) if (!entry.visible) entry.element.remove();
    const drawn = detach ? sorted.filter((entry) => entry.visible) : sorted;
    this.row.append(...drawn.map((entry) => entry.element)); // the order in the page is the order on the screen
  }
}
