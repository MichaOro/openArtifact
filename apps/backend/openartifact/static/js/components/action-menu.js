/* A menu button's menu (ARIA menu button pattern): the trigger has aria-haspopup="menu" and
 * aria-expanded; the menu has role="menu" with role="menuitem" entries. Arrow keys, Home/End move,
 * Enter/Space choose, Escape closes and returns focus to the trigger, a click elsewhere closes.
 *
 * An entry can be disabled with a reason: it stays in the menu and focusable (aria-disabled), does
 * nothing, and shows the reason on hover and on keyboard focus (also its aria-describedby).
 * One instance serves every trigger of a page; the menu lives in <body>. */
import { icon } from "./icons.js";
import { placePopover } from "./popover.js";

let nextId = 0;

export class ActionMenu {
  constructor() {
    this.trigger = null;
    this.el = document.createElement("div");
    this.el.className = "menu";
    this.el.setAttribute("role", "menu");
    this.el.hidden = true;
    this.hint = document.createElement("p");
    this.hint.className = "menu__hint";
    this.hint.id = `menu-hint-${(nextId += 1)}`;
    this.hint.setAttribute("role", "tooltip");
    this.hint.hidden = true;
    document.body.append(this.el);

    this.el.addEventListener("keydown", (event) => this.#onKeydown(event));
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.isOpen && !this.el.contains(event.target) && !this.trigger.contains(event.target)) {
          this.close({ restoreFocus: false });
        }
      },
      true,
    );
    window.addEventListener("resize", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return !this.el.hidden;
  }

  /**
   * Open under `trigger`, or close if it is already open for it.
   * @param {HTMLElement} trigger
   * @param {{label: string, icon: string, onSelect: () => void, disabledReason?: string}[]} items
   *   `disabledReason` set: the entry is disabled and shows that text as its hint
   * @param {string} label what assistive technology calls the menu
   */
  toggle(trigger, items, label) {
    if (this.isOpen && this.trigger === trigger) {
      this.close();
      return;
    }
    this.close({ restoreFocus: false });
    this.trigger = trigger;
    this.el.setAttribute("aria-label", label);
    const entries = items.map((item) => this.#entry(item));
    this.el.replaceChildren(...entries, this.hint);
    this.hint.hidden = true;
    this.el.hidden = false;
    const t = trigger.getBoundingClientRect();
    placePopover(this.el, (size) => ({
      left: t.right - size.width,
      top: t.bottom + 6,
      flipTop: t.top - size.height - 6,
    }));
    trigger.setAttribute("aria-expanded", "true");
    entries[0].focus({ preventScroll: true });
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus) this.trigger.focus();
  }

  #entry({ label, icon: iconName, onSelect, disabledReason }) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "menu__item";
    button.setAttribute("role", "menuitem");
    button.append(icon(iconName), label);
    if (disabledReason) {
      button.setAttribute("aria-disabled", "true");
      button.setAttribute("aria-describedby", this.hint.id);
      const show = () => {
        this.hint.textContent = disabledReason;
        this.hint.hidden = false;
      };
      const hide = () => (this.hint.hidden = true);
      button.addEventListener("pointerenter", show);
      button.addEventListener("focus", show);
      button.addEventListener("pointerleave", hide);
      button.addEventListener("blur", hide);
    } else {
      button.addEventListener("click", () => {
        this.close(); // focus goes back to the trigger first: a dialog opened next returns there
        onSelect();
      });
    }
    return button;
  }

  #onKeydown(event) {
    const items = [...this.el.querySelectorAll('[role="menuitem"]')];
    const index = items.indexOf(document.activeElement);
    const go = (target) => {
      event.preventDefault();
      target?.focus();
    };
    switch (event.key) {
      case "ArrowDown":
        go(items[(index + 1) % items.length]);
        break;
      case "ArrowUp":
        go(items[(index - 1 + items.length) % items.length]);
        break;
      case "Home":
        go(items[0]);
        break;
      case "End":
        go(items.at(-1));
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        this.close();
        break;
      case "Tab":
        this.close({ restoreFocus: false });
        break;
      default:
    }
  }
}
