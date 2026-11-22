/* The inspector next to the canvas: shows the summary, the selected node or the selected connection.
 * Every change made in it draws the panel again; the control that had focus is found again by its
 * [data-focus-key], so keyboard users keep their place. */
import { typeOf } from "./node-types.js";

export class InspectorPanel {
  /** @param {HTMLElement} element the [data-inspector] aside @param {import("./inspector.js").InspectorBlocks} blocks @param {import("./graph-model.js").GraphModel} model */
  constructor(element, blocks, model) {
    this.element = element;
    this.blocks = blocks;
    this.model = model;
  }

  /** @param {{type: "node"|"edge", id: string}|null} selection */
  render(selection) {
    const key = this.element.contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
    this.element.replaceChildren(...this.#content(selection));
    if (key) this.element.querySelector(`[data-focus-key="${key}"]`)?.focus();
  }

  /** Move focus to the first control (Enter on a node). */
  focusFirst() {
    this.element.querySelector("input, select, button")?.focus();
  }

  #content(selection) {
    const { nodes, edges } = this.model;
    if (selection?.type === "node" && nodes.has(selection.id)) {
      const node = nodes.get(selection.id);
      return [this.blocks.title(node), ...typeOf(node).sections(node, this.blocks).filter(Boolean)];
    }
    if (selection?.type === "edge" && edges.has(selection.id)) return this.blocks.connection(edges.get(selection.id));
    return this.blocks.summary();
  }
}
