/* The "+" menu on the canvas: a search field and every kind that can be added here, in clusters (AI, Agent tools,
 * Core, Flow, ...). Typing narrows the list; Arrow keys move, Enter adds the first match, Escape closes. */
import { addableIn, groupAddable } from "./node-types.js";

export class AddMenu {
  /**
   * @param {HTMLElement} root the editor element, containing [data-add-menu] and [data-add-list]
   * @param {"pipeline"|"action"} scope
   * @param {(kind: string) => void} onPick
   */
  constructor(root, scope, onPick) {
    this.toggle = root.querySelector("[data-add-menu]");
    this.list = root.querySelector("[data-add-list]");
    this.types = addableIn(scope);
    this.search = Object.assign(document.createElement("input"), { type: "search", className: "field__control ge-add__search", placeholder: "Search nodes…", autocomplete: "off", spellcheck: false });
    this.search.setAttribute("aria-label", "Search nodes");
    this.items = document.createElement("div");
    this.items.className = "ge-add__items";
    this.empty = Object.assign(document.createElement("p"), { className: "ge-add__empty", textContent: "No node matches.", hidden: true });
    this.list.append(this.search, this.items, this.empty);
    this.#fill("");

    this.search.addEventListener("input", () => this.#fill(this.search.value));
    this.toggle.addEventListener("click", () => {
      this.#setOpen(this.list.hidden);
      if (!this.list.hidden) this.search.focus();
    });
    this.list.addEventListener("click", (event) => {
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
    return [...this.items.querySelectorAll("[data-add]")];
  }

  /** Draw the clusters that match `query`. */
  #fill(query) {
    const groups = groupAddable(this.types, query);
    this.items.replaceChildren(
      ...groups.flatMap(({ group, types }) => [
        Object.assign(document.createElement("p"), { className: "ge-add__group", textContent: group }),
        ...types.map((type) => {
          const item = document.createElement("button");
          item.type = "button";
          item.className = "ge-add__item";
          item.dataset.add = type.kind;
          item.textContent = type.label;
          return item;
        }),
      ]),
    );
    this.empty.hidden = groups.length > 0;
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
      buttons[0]?.click();
    }
  }

  #setOpen(open) {
    this.list.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
    if (open) {
      this.search.value = "";
      this.#fill("");
    }
  }
}
