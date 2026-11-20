/* Collapsible icon rail (used by the task dialog). Mirrors the main sidebar: collapsed by
 * default, expands to icon + label. The chosen state is remembered across sessions. */

const STORAGE_PREFIX = "openartifact-";

function read(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable */
  }
}

export class CollapsibleNav {
  /**
   * @param {HTMLElement} root element with data-state="collapsed|expanded"
   * @param {HTMLElement} toggle button that flips the state
   * @param {string} storageKey key suffix for persisting the state
   * @param {{expand: string, collapse: string}} labels aria-labels of the toggle
   */
  constructor(root, toggle, storageKey, labels = { expand: "Expand", collapse: "Collapse" }) {
    this.root = root;
    this.toggle = toggle;
    this.key = STORAGE_PREFIX + storageKey;
    this.labels = labels;
    this.set(read(this.key) === "expanded" ? "expanded" : "collapsed", false);
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
    if (persist) write(this.key, state);
  }
}
