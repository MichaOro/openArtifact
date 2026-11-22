/* The "+" menu on the canvas: a disclosure list with every kind that can be added here. */
import { addableIn } from "./node-types.js";

export class AddMenu {
  /**
   * @param {HTMLElement} root the editor element, containing [data-add-menu] and [data-add-list]
   * @param {"pipeline"|"action"} scope
   * @param {(kind: string) => void} onPick
   */
  constructor(root, scope, onPick) {
    this.toggle = root.querySelector("[data-add-menu]");
    this.list = root.querySelector("[data-add-list]");
    for (const type of addableIn(scope)) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "ge-add__item";
      item.dataset.add = type.kind;
      item.textContent = type.label;
      this.list.append(item);
    }
    this.toggle.addEventListener("click", () => {
      this.#setOpen(this.list.hidden);
      if (!this.list.hidden) this.list.querySelector("button")?.focus();
    });
    this.list.addEventListener("click", (event) => {
      const item = event.target.closest("[data-add]");
      if (!item) return;
      this.#setOpen(false);
      onPick(item.dataset.add);
    });
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

  #setOpen(open) {
    this.list.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
  }
}
