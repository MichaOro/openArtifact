/* Small listbox popover to pick a lane. Generic: it only gets a list of {status, title} and a
 * callback, so user-defined lanes later need no change here. It is appended to `container`
 * (the open <dialog>), because only elements inside the dialog are above it (top layer). */

export class LanePicker {
  /** @param {{container: HTMLElement}} options */
  constructor({ container }) {
    this.container = container;
    this.trigger = null;
    this.onSelect = null;

    this.el = document.createElement("div");
    this.el.className = "popover";
    this.el.setAttribute("role", "listbox");
    this.el.setAttribute("aria-label", "Move to lane");
    this.el.hidden = true;
    container.append(this.el);

    this.el.addEventListener("click", (event) => {
      const option = event.target.closest("[data-status]");
      if (!option) return;
      const select = this.onSelect;
      this.close();
      select?.(option.dataset.status);
    });
    this.el.addEventListener("keydown", (event) => this.#onKeydown(event));
    // Pointer down anywhere else closes the menu (the trigger toggles it itself).
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.isOpen && !this.el.contains(event.target) && !this.trigger?.contains(event.target)) {
          this.close({ restoreFocus: false });
        }
      },
      true,
    );
    container.addEventListener("close", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return !this.el.hidden;
  }

  /**
   * Open (or close, if already open for the same trigger).
   * @param {object} options
   * @param {HTMLElement} options.trigger
   * @param {{status: string, title: string}[]} options.lanes all lanes in board order
   * @param {string} options.current status of the current lane (not offered)
   * @param {(status: string) => void} options.onSelect
   * @param {"below"|"left"} [options.placement]
   */
  toggle({ trigger, lanes, current, onSelect, placement = "below" }) {
    if (this.isOpen && this.trigger === trigger) {
      this.close();
      return;
    }
    const others = lanes.filter((lane) => lane.status !== current);
    if (others.length === 0) return;

    this.close({ restoreFocus: false });
    this.trigger = trigger;
    this.onSelect = onSelect;

    const caption = document.createElement("p");
    caption.className = "popover__caption";
    caption.textContent = "Move to";
    caption.setAttribute("aria-hidden", "true");
    const options = others.map((lane) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "popover__option";
      option.setAttribute("role", "option");
      option.dataset.status = lane.status;
      option.textContent = lane.title;
      return option;
    });
    this.el.replaceChildren(caption, ...options);
    this.el.hidden = false;
    this.#position(trigger, placement);
    trigger.setAttribute("aria-expanded", "true");
    options[0].focus();
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.trigger?.setAttribute("aria-expanded", "false");
    if (restoreFocus) this.trigger?.focus();
    this.onSelect = null;
  }

  #position(trigger, placement) {
    const margin = 8;
    const t = trigger.getBoundingClientRect();
    const p = this.el.getBoundingClientRect();
    let left = placement === "left" ? t.left - p.width - margin : t.left;
    let top = placement === "left" ? t.top : t.bottom + 6;
    if (top + p.height > window.innerHeight - margin) top = Math.max(margin, t.top - p.height - 6);
    left = Math.min(Math.max(margin, left), window.innerWidth - p.width - margin);
    this.el.style.left = `${left}px`;
    this.el.style.top = `${top}px`;
  }

  #onKeydown(event) {
    const options = [...this.el.querySelectorAll("[data-status]")];
    const index = options.indexOf(document.activeElement);
    const focus = (i) => options[(i + options.length) % options.length]?.focus();
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focus(index + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focus(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focus(0);
        break;
      case "End":
        event.preventDefault();
        focus(options.length - 1);
        break;
      case "Enter":
      case " ":
        // Handled here (and the native activation suppressed) so a selection fires exactly once.
        if (index >= 0) {
          event.preventDefault();
          options[index].click();
        }
        break;
      case "Escape":
        // Close only the menu, not the dialog around it.
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
