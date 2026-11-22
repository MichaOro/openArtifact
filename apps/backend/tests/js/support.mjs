/* Unit tests of the pure frontend modules, with Node's built-in runner (no npm packages):
 *   node --test 'apps/backend/tests/js/*.test.mjs'
 * add --experimental-test-coverage for the line coverage. The tests import the modules from
 * apps/backend/openartifact/static/js directly; this file holds the stand-ins for what they need
 * from a browser. */

/* A minimal stand-in for the few DOM calls the pure modules make (createElement, fragments,
 * the icon template). Not a browser: just enough to assert on what was built. */

export class FakeNode {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.classes = new Set();
    this.classList = { add: (...names) => names.forEach((n) => this.classes.add(n)) };
    this.textContent = "";
  }

  append(...items) {
    this.children.push(...items);
  }

  replaceChildren(...items) {
    this.children = items;
  }

  cloneNode() {
    const copy = new FakeNode(this.tagName);
    copy.children = [...this.children];
    copy.iconName = this.iconName;
    return copy;
  }

  querySelector(selector) {
    const attribute = /^\[(data-[a-z-]+)\]$/.exec(selector)?.[1];
    const found = (node) => {
      for (const child of node.children) {
        if (!(child instanceof FakeNode)) continue;
        if (attribute && child.attributes?.[attribute] !== undefined) return child;
        const deeper = found(child);
        if (deeper) return deeper;
      }
      return null;
    };
    return found(this);
  }
}

/** Text of a node tree, e.g. a fragment holding strings and elements. */
export function textOf(node) {
  if (typeof node === "string") return node;
  return node.children.map(textOf).join("") + (node.textContent ?? "");
}

/** Install `document` with the icon template for the given names (every icon is an <svg>). */
export function installDocument(iconNames = []) {
  const icons = new Map(iconNames.map((name) => [name, Object.assign(new FakeNode("svg"), { iconName: name })]));
  globalThis.document = {
    createElement: (tag) => new FakeNode(tag),
    createDocumentFragment: () => new FakeNode("#fragment"),
    getElementById: (id) =>
      id === "icons" ? { content: { querySelector: (selector) => icons.get(/data-icon="([^"]+)"/.exec(selector)[1]) ?? null } } : null,
  };
}

export function uninstallDocument() {
  delete globalThis.document;
}

/** A chip as the history markup has it: [data-chip-icon] and [data-chip-text] inside. */
export function chip() {
  const root = new FakeNode("span");
  const iconSlot = new FakeNode("span");
  iconSlot.attributes = { "data-chip-icon": "" };
  const textSlot = new FakeNode("span");
  textSlot.attributes = { "data-chip-text": "" };
  root.append(iconSlot, textSlot);
  return { root, iconSlot, textSlot };
}

const port = (name, label = name) => ({ name, label });
const kind = (name, label, fields) => ({
  kind: name, label, scopes: ["pipeline"], fixed: false, addable: false, chain: false, ending: false, inputs: [], outputs: [], settings: [], links_to: null, ...fields,
});

/** What GET /api/node-types answers (the parts the editor uses). */
export const NODE_TYPES = [
  kind("trigger", "Trigger", { fixed: true, chain: true, scopes: ["pipeline", "action"], outputs: [port("out", "Next")] }),
  kind("complete", "Complete", { fixed: true, ending: true, inputs: [port("in")] }),
  kind("stage", "Stage", { addable: true, chain: true, inputs: [port("start")], outputs: [port("end")] }),
  kind("action", "Action", { scopes: ["pipeline"], links_to: "action", inputs: [port("in")], outputs: [port("out"), port("pass", "On Pass"), port("error", "On Error")] }),
  kind("pipeline", "Pipeline", { addable: true, chain: true, links_to: "pipeline", inputs: [port("in")], outputs: [port("out")] }),
  kind("timer", "Timer", { addable: true, chain: true, inputs: [port("in")], outputs: [port("out")] }),
  kind("output", "Output", { fixed: true, scopes: ["action"], ending: true, inputs: [port("pass", "On Pass"), port("fail", "On Fail")] }),
  kind("code", "Code", { addable: true, chain: true, scopes: ["action"], inputs: [port("in")], outputs: [port("pass", "On Pass"), port("fail", "On Fail")] }),
  kind("http", "HTTP request", { addable: true, chain: true, scopes: ["action"], inputs: [port("in")], outputs: [port("pass", "On Pass"), port("fail", "On Fail")] }),
  kind("note", "Note", { addable: true, scopes: ["action"] }), // a kind without a view of its own
];

/** Load the kinds into node-types.js through a stubbed fetch. */
export async function loadTypes(loadNodeTypes) {
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({ status: 200, ok: true, json: async () => NODE_TYPES });
  try {
    await loadNodeTypes();
  } finally {
    globalThis.fetch = real;
  }
}
