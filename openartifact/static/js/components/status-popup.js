/* The small popup of an entry of the status bar (the eye, the refused starts): a title, lines of facts, a note and buttons, placed next
 * to its trigger by placePopover (popover.js). A click elsewhere or Escape closes it and gives the focus back. One popup at a time. */
import { placePopover } from "./popover.js";

const make = (tag, className = "", text = null) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
};

export class StatusPopup {
  constructor() {
    this.el = make("div", "popover status-popup");
    this.el.setAttribute("role", "dialog");
    this.el.hidden = true;
    this.trigger = null;
    this.el.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        this.close();
      }
    });
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.isOpen && !this.el.contains(event.target) && !this.trigger?.contains(event.target)) this.close({ restoreFocus: false });
      },
      true,
    );
    window.addEventListener("resize", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return !this.el.hidden;
  }

  /**
   * Open next to `trigger`, or close when it is open for that trigger.
   * @param {HTMLElement} trigger
   * @param {{title: string, lines?: string[], note?: string, error?: string, actions?: {label: string, primary?: boolean, danger?: boolean,
   *   onClick: () => (void|Promise<unknown>)}[]}} what
   */
  toggle(trigger, what) {
    if (this.isOpen && this.trigger === trigger) {
      this.close();
      return;
    }
    this.close({ restoreFocus: false });
    this.trigger = trigger;
    const host = trigger.closest("dialog[open]") ?? document.body;
    if (this.el.parentElement !== host) host.append(this.el);
    this.what = what;
    this.#render();
    this.el.hidden = false;
    this.#place();
    trigger.setAttribute("aria-expanded", "true");
    (this.el.querySelector("button") ?? this.el).focus({ preventScroll: true });
  }

  /** Draw it again with new facts (the state changed while it was open). */
  update(what) {
    if (!this.isOpen) return;
    this.what = { ...this.what, ...what };
    this.#render();
    this.#place();
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.trigger?.setAttribute("aria-expanded", "false");
    if (restoreFocus && this.trigger?.isConnected) this.trigger.focus({ preventScroll: true });
  }

  #place() {
    const rect = this.trigger.getBoundingClientRect();
    placePopover(this.el, (size) => ({ left: rect.right - size.width, top: rect.bottom + 6, flipTop: rect.top - size.height - 6 }));
  }

  #render() {
    const { title, lines = [], note = "", error = "", actions = [] } = this.what;
    this.el.setAttribute("aria-label", title);
    const parts = [make("p", "popover__caption", title)];
    if (lines.length) {
      const list = make("ul", "status-popup__facts");
      for (const line of lines) list.append(make("li", "", line));
      parts.push(list);
    }
    if (note) parts.push(make("p", "status-popup__note", note));
    const problem = make("p", "status-popup__error", error);
    problem.hidden = !error;
    problem.setAttribute("role", "alert");
    parts.push(problem);
    const row = make("div", "status-popup__actions");
    for (const action of actions) {
      const button = make("button", `button button--sm ${action.primary ? "button--primary" : "button--ghost"}${action.danger ? " button--danger" : ""}`, action.label);
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await action.onClick();
        } finally {
          button.disabled = false;
        }
      });
      row.append(button);
    }
    parts.push(row);
    this.el.replaceChildren(...parts);
  }
}
