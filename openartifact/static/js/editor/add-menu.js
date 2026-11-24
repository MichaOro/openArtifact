/* The "+" menu on the canvas: a search field and the kinds that can be added here. Without a search the kinds are in
 * clusters (AI, Agent tools, Core, Flow, ...) that open one at a time, which only help to find your way; typing searches
 * the kinds themselves (name or kind), as one list that says each one's cluster. Arrow keys move, Enter adds the first
 * match, Escape closes. */
import { icon } from "../components/icons.js";
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
    this.toggle = root.querySelector("[data-add-menu]");
    this.list = root.querySelector("[data-add-list]");
    this.types = [...addableIn(scope), ...placeholdersIn(scope)];
    this.open = null; // the cluster that is open
    this.search = Object.assign(document.createElement("input"), { type: "search", className: "field__control ge-add__search", placeholder: t("editor.add_menu.search_nodes"), autocomplete: "off", spellcheck: false });
    this.search.setAttribute("aria-label", t("editor.add_menu.search_nodes_2"));
    this.items = document.createElement("div");
    this.items.className = "ge-add__items";
    this.empty = Object.assign(document.createElement("p"), { className: "ge-add__empty", textContent: t("editor.add_menu.no_node_matches"), hidden: true });
    this.list.append(this.search, this.items, this.empty);
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
      this.#setOpen(false);
      onPick(item.dataset.add);
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
    if (type.placeholder) name.append(icon(type.icon), Object.assign(document.createElement("span"), { textContent: type.label }));
    else name.textContent = type.label;
    item.append(name);
    if (type.placeholder && type.soon) item.append(Object.assign(document.createElement("span"), { className: "tag", textContent: t("editor.add_menu.soon") }));
    if (group) item.append(Object.assign(document.createElement("span"), { className: "ge-add__tag", textContent: group }));
    return item;
  }

  /** Draw what the search says: the clusters (one open), or the matching kinds as one list. */
  #fill() {
    const query = this.search.value.trim();
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
    this.list.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      this.search.value = "";
      this.open = null;
      this.#fill();
    }
  }
}
