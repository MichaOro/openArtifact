/* What the user sees in a field that takes references is never an id (ADR-082 addendum 1). In storage, in the API and in MCP a reference to a
 * node is `${node:<uuid>.field}`; in the editor the user reads and writes `${node:<name>.field}`, the name as the card shows it (an action with
 * its number: `Test: Code und HTTP #4`). It is only a way of showing text, nothing is resolved here: two pure conversions, tested on their own.
 *
 *   const names = new ReferenceNames(() => nodes);
 *   names.display(stored)    stored text -> what the field shows     names.stored(shown)    what the field shows -> stored text
 *
 * Names that nodes share get ` (1)`, ` (2)` ... after them, in the order of the nodes, so the way back is unambiguous. An id that no node has
 * any more is shown as `(deleted node)` (`(deleted node 2)` for a second one) and goes back to its own id when the field is saved: a reference to a
 * deleted node is not destroyed by a save, the publish check reports it. A readable form that names no node stays as written (text the user
 * typed that the check will report). The old form `${(Name).field}` is neither shown differently nor changed. */
import { t } from "../i18n.js";
import { labelsFor } from "./reference-completion.js";

export { labelsFor };

const ID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const STORED_HEAD = new RegExp(`\\$\\{node:(${ID})\\.`, "g");
const ANY_HEAD = /\$\{node:([^}\r\n]*)/g;
const STARTS_WITH_ID = new RegExp(`^${ID}\\.`);

export class ReferenceNames {
  /** @param {() => object[]} nodes the nodes of the graph being edited (read at every conversion: a rename shows at once) */
  constructor(nodes) {
    this.nodes = nodes;
    this.goneByLabel = new Map();
    this.goneById = new Map();
  }

  #gone(id) {
    let label = this.goneById.get(id);
    if (!label) {
      const word = t("editor.reference_completion.gone");
      label = this.goneById.size ? `(${word} ${this.goneById.size + 1})` : `(${word})`;
      this.goneById.set(id, label);
      this.goneByLabel.set(label, id);
    }
    return label;
  }

  /** Stored text -> the text a field shows: `${node:<uuid>.` becomes `${node:<name>.`. */
  display(text) {
    const value = String(text ?? "");
    if (!value.includes("${node:")) return value;
    const labels = labelsFor(this.nodes());
    return value.replace(STORED_HEAD, (_, id) => `\${node:${labels.get(id) ?? this.#gone(id)}.`);
  }

  /** The text a field shows -> stored text: `${node:<name>.` becomes `${node:<uuid>.`; what names no node (or two) is left as written. */
  stored(text) {
    const value = String(text ?? "");
    if (!value.includes("${node:")) return value;
    const byLabel = new Map();
    for (const [id, label] of labelsFor(this.nodes())) byLabel.set(label, id);
    for (const [label, id] of this.goneByLabel) byLabel.set(label, id);
    const known = [...byLabel.keys()].sort((a, b) => b.length - a.length); // the longest name first: "Check #1" before "Check"
    return value.replace(ANY_HEAD, (whole, rest) => {
      if (STARTS_WITH_ID.test(rest)) return whole; // an id already: nothing to do
      const label = known.find((candidate) => rest.startsWith(`${candidate}.`));
      return label ? `\${node:${byLabel.get(label)}.${rest.slice(label.length + 1)}` : whole;
    });
  }
}
