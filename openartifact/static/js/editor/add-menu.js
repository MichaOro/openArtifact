/* The "+" menu on the canvas: a search field and the kinds that can be added here. Without a search the kinds are in
 * clusters (AI, Agent tools, Core, Flow, ...) that open one at a time, which only help to find your way; typing searches
 * the kinds themselves (name or kind), as one list that says each one's cluster. Arrow keys move, Enter adds the first
 * match, Escape closes. */
import { icon } from "../components/icons.js";
import { placePopover } from "../components/popover.js";
import { addableIn, groupAddable, placeholdersIn, searchAddable } from "./node-types.js";
import { t } from "../i18n.js";

export class AddMenu {
  /**
   * @param {HTMLElement} root the editor element, containing [data-add-menu] and [data-add-list]
   * @param {"pipeline"|"action"} scope
   * @param {(kind: string) => void} onPick
   * @param {(key: string) => void} [onPlaceholder] a place held for something that is coming was chosen (nothing is added)
   */
  constructor(root, scope, onPick, onPlaceholder = () => {}) {
    this.scope = scope;
    this.toggle = root.querySelector("[data-add-menu]");
    this.list = root.querySelector("[data-add-list]");
    this.types = [...addableIn(scope), ...placeholdersIn(scope)];
    this.baseTypes = this.types;
    this.anchored = null; // set while the menu is open at a point for a line released on the canvas (openFrom)
    this.open = null; // the cluster that is open
    this.search = Object.assign(document.createElement("input"), { type: "search", className: "field__control ge-add__search", placeholder: t("editor.add_menu.search_nodes"), autocomplete: "off", spellcheck: false });
    this.search.setAttribute("aria-label", t("editor.add_menu.search_nodes_2"));
    this.items = document.createElement("div");
    this.items.className = "ge-add__items";
    this.empty = Object.assign(document.createElement("p"), { className: "ge-add__empty", textContent: t("editor.add_menu.no_node_matches"), hidden: true });
    this.from = Object.assign(document.createElement("p"), { className: "ge-add__from", hidden: true });
    this.list.append(this.from, this.search, this.items, this.empty);
    this.#fill();
    this.search.addEventListener("input", () => this.#fill());
    this.toggle.addEventListener("click", () => {
      this.#setOpen(this.list.hidden);
      if (!this.list.hidden) this.search.focus();
    });
    this.list.addEventListener("click", (event) => {
      const group = event.target.closest("[data-group]");
      if (group) {
        this.open = this.open === group.dataset.group ? null : group.dataset.group;
        this.#fill();
        this.items.querySelector(`[data-group="${group.dataset.group}"]`)?.focus();
        return;
      }
      const held = event.target.closest("[data-placeholder]");
      if (held) {
        this.#setOpen(false);
        this.toggle.focus();
        onPlaceholder(held.dataset.placeholder);
        return;
      }
      const item = event.target.closest("[data-add]");
      if (!item) return;
      const pick = this.anchored?.onPick ?? onPick; // read before closing: closing ends the anchored mode
      this.#setOpen(false);
      pick(item.dataset.add);
    });
    this.list.addEventListener("keydown", (event) => this.#key(event));
    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".ge-add")) this.#setOpen(false);
    });
    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !this.list.hidden) {
        this.#setOpen(false);
        this.toggle.focus();
      }
    });
  }

  #buttons() {
    return [...this.items.querySelectorAll("button")];
  }

  #item(type, group = null) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "ge-add__item";
    if (type.placeholder) item.dataset.placeholder = type.kind;
    else item.dataset.add = type.kind;
    const name = document.createElement("span");
    name.className = "ge-add__name";
    // every entry has the glyph of its kind (the manifest's `menu_icon`, else its card icon): one column of icons, then the names
    const glyph = type.menu_icon ?? type.icon;
    const label = Object.assign(document.createElement("span"), { textContent: type.label });
    name.append(...(glyph ? [icon(glyph), label] : [label]));
    item.append(name);
    if (type.placeholder && type.soon) item.append(Object.assign(document.createElement("span"), { className: "tag", textContent: t("editor.add_menu.soon") }));
    if (group) item.append(Object.assign(document.createElement("span"), { className: "ge-add__tag", textContent: group }));
    return item;
  }

  /**
   * Open the same menu at a point instead of under the "+": for a line that was released on the empty canvas. It offers the
   * given kinds only, says where the line comes from, and closes (cancelling everything) on Escape or a click elsewhere.
   * @param {{x: number, y: number}} point where the pointer was released (page coordinates)
   * @param {{types: object[], header: string, emptyText: string, onPick: (kind: string) => void}} options
   */
  openFrom({ x, y }, { types, header, emptyText, onPick }) {
    this.#setOpen(false);
    this.anchored = { onPick, emptyText };
    this.types = types;
    this.from.textContent = header;
    this.from.hidden = false;
    this.list.classList.add("is-anchored");
    this.#setOpen(true);
    placePopover(this.list, (size) => ({ left: x, top: y, flipTop: y - size.height }));
    this.search.focus();
  }

  /** The action this menu adds to is for pipelines or for guards (known once the graph is loaded, ADR-067): only the kinds that
   * may be used there are offered. */
  setPurpose(purpose) {
    this.types = [...addableIn(this.scope, purpose), ...placeholdersIn(this.scope)];
    this.baseTypes = this.types;
    this.#fill();
  }

  /** Draw what the search says: the clusters (one open), or the matching kinds as one list. */
  #fill() {
    const query = this.search.value.trim();
    if (this.anchored && !this.types.length) {
      this.items.replaceChildren();
      this.empty.textContent = this.anchored.emptyText;
      this.empty.hidden = false;
      return;
    }
    if (query) {
      const found = searchAddable(this.types, query);
      this.items.replaceChildren(...found.map((t) => this.#item(t, t.group)));
      this.empty.hidden = found.length > 0;
      return;
    }
    this.empty.hidden = true;
    this.items.replaceChildren(
      ...groupAddable(this.types).flatMap(({ group, types }) => {
        const open = this.open === group;
        const head = document.createElement("button");
        head.type = "button";
        head.className = "ge-add__group";
        head.dataset.group = group;
        head.setAttribute("aria-expanded", String(open));
        head.append(icon("chevron-down"), Object.assign(document.createElement("span"), { textContent: group }), Object.assign(document.createElement("span"), { className: "ge-add__count", textContent: String(types.length) }));
        return [head, ...(open ? types.map((t) => this.#item(t)) : [])];
      }),
    );
  }

  #key(event) {
    const buttons = this.#buttons();
    const at = buttons.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!buttons.length) return;
      const next = event.key === "ArrowDown" ? at + 1 : at - 1;
      if (next < 0) this.search.focus();
      else buttons[Math.min(next, buttons.length - 1)].focus();
    } else if (event.key === "Enter" && event.target === this.search) {
      event.preventDefault();
      this.items.querySelector("[data-add], [data-placeholder]")?.click();
    }
  }

  #setOpen(open) {
    if (!open && this.anchored) {
      this.anchored = null;
      this.types = this.baseTypes;
      this.from.hidden = true;
      this.list.classList.remove("is-anchored");
      this.list.style.left = this.list.style.top = "";
      this.empty.textContent = t("editor.add_menu.no_node_matches");
    }
    this.list.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      this.search.value = "";
      this.open = null;
      this.#fill();
    }
  }
}
