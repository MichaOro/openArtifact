/* The settings of a node, in the overlay a double click opens (editor.js): its title and what its kind offers.
 * Every change made in it draws the panel again; the control that had focus is found again by its
 * [data-focus-key], so keyboard users keep their place. */
import { typeOf } from "./node-types.js";
import { previewSelector } from "./reference-preview.js";

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
    const active = document.activeElement;
    const key = this.element.contains(active) ? active.dataset.focusKey : null;
    const caret = key && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd, active.scrollTop] : null;
    this.element.replaceChildren(...this.#content(selection));
    // a node with settings for both columns gets the wide dialog
    this.element.closest("dialog")?.classList.toggle("is-wide", Boolean(this.element.querySelector('.ge-settings[data-columns="2"]')));
    const control = key ? this.element.querySelector(`[data-focus-key="${key}"]`) : null;
    if (!control) return;
    control.focus();
    if (caret && typeof control.setSelectionRange === "function") {
      control.setSelectionRange(caret[0], caret[1]);
      control.scrollTop = caret[2];
    }
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
    const takesReferences = type.ui?.block === "agent" || type.settings?.some((s) => s.references && s.references !== "all");
    return [this.blocks.title(node), ...(takesReferences ? [previewSelector()] : []), ...type.sections(node, this.blocks).filter(Boolean)];
  }
}
