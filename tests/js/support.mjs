/* Unit tests of the pure frontend modules, with Node's built-in runner (no npm packages):
 *   node --test 'tests/js/*.test.mjs'
 * add --experimental-test-coverage for the line coverage. The tests import the modules from
 * openartifact/static/js directly; this file holds the stand-ins for what they need
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

  setAttribute(name, value) {
    this.attributes = { ...this.attributes, [name]: String(value) };
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
    createTextNode: (text) => String(text),
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

import { readFileSync } from "node:fs";

/** What GET /api/node-types answers: the real description of the manifests (tests/fixtures/node-types.json, which
 * tests/test_node_manifests.py keeps equal to the live answer), plus a kind without any manifest-given look. */
export const NODE_TYPES = [
  ...JSON.parse(readFileSync(new URL("../fixtures/node-types.json", import.meta.url), "utf8")),
  {
    kind: "note", label: "Note", scopes: ["action"], fixed: false, addable: true, chain: false, ending: false, inputs: [], outputs: [], settings: [], links_to: null, tool: false, behaviour: "plain", menu: null, ui: {},
  }, // a kind that no behaviour dresses up
];

/** The entries of the "+" menu that are no kinds (what the editor page carries in data-menu-placeholders): the real
 * ones of graph/nodes/_menu.yaml, kept equal to the live answer by tests/test_node_manifests.py. */
export const PLACEHOLDERS = JSON.parse(readFileSync(new URL("../fixtures/menu-placeholders.json", import.meta.url), "utf8"));

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
