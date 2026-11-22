/* Collapsible icon rail (used by the task dialog). Mirrors the main sidebar: collapsed by
 * default, expands to icon + label. The chosen state is remembered across sessions. */

import { readStorage, writeStorage } from "../storage.js";

export class CollapsibleNav {
  /**
   * @param {HTMLElement} root element with data-state="collapsed|expanded"
   * @param {HTMLElement} toggle button that flips the state
   * @param {string} storageKey key (see storage.js) for persisting the state
   * @param {{expand: string, collapse: string}} labels aria-labels of the toggle
   */
  constructor(root, toggle, storageKey, labels = { expand: "Expand", collapse: "Collapse" }) {
    this.root = root;
    this.toggle = toggle;
    this.key = storageKey;
    this.labels = labels;
    this.set(readStorage(this.key) === "expanded" ? "expanded" : "collapsed", false);
    toggle.addEventListener("click", () => this.set(this.expanded ? "collapsed" : "expanded"));
  }

  get expanded() {
    return this.root.dataset.state === "expanded";
  }

  set(state, persist = true) {
    this.root.dataset.state = state;
    const expanded = state === "expanded";
    this.toggle.setAttribute("aria-expanded", String(expanded));
    this.toggle.setAttribute("aria-label", expanded ? this.labels.collapse : this.labels.expand);
    if (persist) writeStorage(this.key, state);
  }
}
