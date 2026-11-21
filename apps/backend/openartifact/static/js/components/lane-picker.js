/* Lane picker. Generic: it only gets a list of {status, title, hue} and a callback, so
 * user-defined lanes later need no change here. Two presentations:
 *
 *  - "list":  a small listbox popover (positioned next to a trigger);
 *  - "chips": the other lanes as coloured chips in an inline row that unrolls inside the dialog
 *             (the lane-chip easter egg); the content below slides down to make room.
 *
 * Both live inside the open <dialog>: only elements inside it are above it (top layer). */

export class LanePicker {
  /**
   * @param {object} options
   * @param {HTMLElement} options.container the dialog that hosts the popover
   * @param {HTMLElement} [options.inline] the `.lane-chips` row for the "chips" variant
   */
  constructor({ container, inline = null }) {
    this.container = container;
    this.inline = inline;
    this.inner = inline?.querySelector(".lane-chips__inner") ?? null;
    this.trigger = null;
    this.onSelect = null;
    this.mode = null; // "list" | "chips" while open

    this.el = document.createElement("div");
    this.el.className = "popover";
    this.el.setAttribute("role", "listbox");
    this.el.setAttribute("aria-label", "Move to lane");
    this.el.hidden = true;
    container.append(this.el);

    for (const host of [this.el, this.inner].filter(Boolean)) {
      host.addEventListener("click", (event) => {
        const option = event.target.closest("[data-value]");
        if (!option) return;
        const select = this.onSelect;
        this.close();
        select?.(option.dataset.value);
      });
      host.addEventListener("keydown", (event) => this.#onKeydown(event, host));
    }
    // Pointer down anywhere else closes it (the trigger toggles it itself).
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (!this.isOpen) return;
        const host = this.mode === "chips" ? this.inline : this.el;
        if (!host.contains(event.target) && !this.trigger?.contains(event.target)) {
          this.close({ restoreFocus: false });
        }
      },
      true,
    );
    container.addEventListener("close", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return this.mode !== null;
  }

  /**
   * Open (or close, if already open for the same trigger).
   * @param {object} options
   * @param {HTMLElement} options.trigger
   * @param {{status: string, title: string, hue?: number|string}[]} [options.lanes] lanes in board order
   * @param {string} [options.current] with `lanes`: status of the current lane (not offered)
   * @param {{value: string, label: string, hue?: number|string, selected?: boolean}[]} [options.items]
   *   generic choices (instead of `lanes`), e.g. the possible parents
   * @param {string} [options.caption] heading of the list variant
   * @param {(value: string) => void} options.onSelect
   * @param {"below"|"left"} [options.placement] for the "list" variant
   * @param {"list"|"chips"} [options.variant]
   */
  toggle({ trigger, lanes = [], current, items = null, caption = "Move to", onSelect, placement = "below", variant = "list" }) {
    if (this.isOpen && this.trigger === trigger) {
      this.close();
      return;
    }
    const choices =
      items ??
      lanes
        .filter((lane) => lane.status !== current)
        .map((lane) => ({ value: lane.status, label: lane.title, hue: lane.hue, lane: true }));
    if (choices.length === 0) return;

    this.close({ restoreFocus: false });
    this.trigger = trigger;
    this.onSelect = onSelect;
    const chips = variant === "chips" && this.inline !== null;
    this.mode = chips ? "chips" : "list";

    const options = choices.map((item, i) => {
      const option = document.createElement("button");
      option.type = "button";
      option.setAttribute("role", "option");
      option.dataset.value = item.value;
      if (item.lane) option.dataset.status = item.value; // lane options keep the status hook
      option.textContent = item.label;
      option.title = item.label;
      option.setAttribute("aria-selected", String(Boolean(item.selected)));
      if (item.hue) option.dataset.laneHue = String(item.hue);
      option.style.setProperty("--i", String(i));
      option.className = chips ? "lane-chip" : "popover__option";
      return option;
    });

    if (chips) {
      this.inner.replaceChildren(...options);
      this.inline.removeAttribute("inert");
      this.inline.removeAttribute("aria-hidden");
      this.inline.setAttribute("data-open", "");
    } else {
      const caption_el = document.createElement("p");
      caption_el.className = "popover__caption";
      caption_el.textContent = caption;
      caption_el.setAttribute("aria-hidden", "true");
      this.el.replaceChildren(caption_el, ...options);
      this.el.hidden = false;
      this.#position(trigger, placement);
    }
    trigger.setAttribute("aria-expanded", "true");
    options[0].focus({ preventScroll: true });
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    if (this.mode === "chips") {
      this.inline.removeAttribute("data-open");
      this.inline.setAttribute("inert", "");
      this.inline.setAttribute("aria-hidden", "true");
    } else {
      this.el.hidden = true;
    }
    this.mode = null;
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

  #onKeydown(event, host) {
    const options = [...host.querySelectorAll("[data-value]")];
    const index = options.indexOf(document.activeElement);
    const step = (delta) => options[(index + delta + options.length) % options.length]?.focus();
    switch (event.key) {
      case "ArrowDown":
      case "ArrowRight":
        event.preventDefault();
        step(1);
        break;
      case "ArrowUp":
      case "ArrowLeft":
        event.preventDefault();
        step(-1);
        break;
      case "Home":
        event.preventDefault();
        options[0]?.focus();
        break;
      case "End":
        event.preventDefault();
        options[options.length - 1]?.focus();
        break;
      case "Enter":
      case " ":
        // Handled here (native activation suppressed) so a selection fires exactly once.
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
