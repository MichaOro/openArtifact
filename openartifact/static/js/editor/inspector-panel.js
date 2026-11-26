/* The settings of a node, in the overlay a double click opens (editor.js): its title and what its kind offers.
 * A change made in it draws the panel again; the control that had focus is found again by its
 * [data-focus-key], so keyboard users keep their place. While a text field has the focus nothing is drawn: the draw waits
 * until the field is left (persist-policy.js), so the caret never moves while typing. */
import { typeOf } from "./node-types.js";
import { whenFieldFree } from "./persist-policy.js";

export class InspectorPanel {
  /** @param {HTMLElement} element the [data-inspector] aside @param {import("./inspector.js").InspectorBlocks} blocks @param {import("./graph-model.js").GraphModel} model */
  constructor(element, blocks, model) {
    this.element = element;
    this.blocks = blocks;
    this.model = model;
    // a block that fills itself after the panel is drawn (the agent block, once its agents are fetched) brings its two areas
    // later: the dialog becomes wide when they appear. Only ever wider here; render() below also takes it back.
    new MutationObserver(() => this.#widen()).observe(element, { childList: true, subtree: true });
  }

  #widen() {
    if (this.element.querySelector('.ge-settings[data-columns="2"]')) this.element.closest("dialog")?.classList.add("is-wide");
  }

  /** @param {{type: "node"|"edge", id: string}|null} selection a node (anything else shows nothing) */
  render(selection) {
    this.latest = selection; // a draw that had to wait shows the latest selection
    whenFieldFree(this.element, () => this.#draw(this.latest));
  }

  #draw(selection) {
    const active = document.activeElement;
    const key = this.element.contains(active) ? active.dataset.focusKey : null;
    const caret = key && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd, active.scrollTop] : null;
    this.element.closest("dialog")?.querySelector("[data-node-version]")?.remove(); // an agent node brings its own badge
    this.element.replaceChildren(...this.#content(selection));
    // a node with settings for both columns gets the wide dialog
    this.element.closest("dialog")?.classList.toggle("is-wide", Boolean(this.element.querySelector('.ge-settings[data-columns="2"]')));
    const control = key ? this.element.querySelector(`[data-focus-key="${key}"]`) : null;
    // a block that draws itself later (the agent's settings) puts the focus back when it is there: remember where it was
    // (a second draw while the focus is already gone keeps it: it is forgotten once used or after three seconds)
    if (key && !control) {
      this.element.dataset.refocus = key;
      this.element.dataset.refocusAt = String(Date.now());
    } else if (control) {
      delete this.element.dataset.refocus;
    }
    if (!control) return this.onDrawn?.();
    control.focus();
    if (caret && typeof control.setSelectionRange === "function") {
      control.setSelectionRange(caret[0], caret[1]);
      control.scrollTop = caret[2];
    }
    this.onDrawn?.();
  }

  /** Move focus to the first control (Enter on a node). */
  focusFirst() {
    this.element.querySelector("input, select, textarea, button:not(.info-tip)")?.focus(); // a field, not the (i) in front of it
  }

  #content(selection) {
    const { nodes } = this.model;
    if (selection?.type !== "node" || !nodes.has(selection.id)) return [];
    const node = nodes.get(selection.id);
    const type = typeOf(node);
    return [this.blocks.title(node), ...type.sections(node, this.blocks).filter(Boolean)];
  }
}
