/* The logic of the suggestions for ${...} references, without a DOM: where a reference is open at the
 * caret, which completions exist for a graph, which of them fit what was typed, and the text with a
 * completion put in. reference-suggest.js draws the popup. Hints only: nothing here validates a text
 * (the server does), and a name it does not know is simply not offered. */

/** Kinds of nodes that leave a result in the run context (the others have nothing to reference). */
export const RESULT_KINDS = ["code", "http", "timer", "if", "switch", "agent", "set"];
const NODE_FIELDS = [
  ["output", "text the node wrote"],
  ["exit_code", "exit code"],
  ["outcome", "pass or fail"],
  ["reason", "why it failed"],
  ["data.", "its data, then .key"],
];
const MAX_SUGGESTIONS = 40;

/** The names an Edit Fields node sets (mirror of engine/fields.py: the part before "=" of each line). */
export function fieldNames(text) {
  return String(text ?? "")
    .split("\n")
    .map((line) => (line.includes("=") ? line.slice(0, line.indexOf("=")).trim().replace(/^var\./, "") : ""))
    .filter((name) => /^[a-z][a-z0-9_]{0,63}$/.test(name));
}

/** The key of a node in the run context (engine/context.py `node_key`): its name with other characters as `_`. */
export function nodeKey(name) {
  return name.trim().replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 255) || "_";
}

/**
 * The reference being typed at the caret: the last "${" before it with nothing after it that
 * ends or breaks a reference. `{start, query}`: `start` is the index of the "$", `query` the text
 * between "${" and the caret. Null when the caret is not inside an open reference.
 */
export function openReference(text, caret) {
  const before = text.slice(0, caret);
  const start = before.lastIndexOf("${");
  if (start < 0) return null;
  const query = before.slice(start + 2);
  return /[}\s]/.test(query) ? null : { start, query };
}

/**
 * Every completion a graph offers.
 * @param {{id: string, kind: string, name: string, config?: object}[]} nodes the nodes of the graph being edited
 * @param {{exceptId?: string, secrets?: string[], allowSecrets?: boolean, cardFields?: {name: string, label: string}[]}} options
 *   `exceptId`: the node being edited (it cannot read its own result); `secrets`: names only;
 *   `cardFields`: the artifact fields, offered as `card.NAME` (ADR-044)
 * @returns {{insert: string, detail: string, complete: boolean}[]} `insert` is what goes between "${" and "}";
 *   `complete` is false when the user continues typing (a data path)
 */
export function candidatesFor(nodes, { exceptId = null, secrets = [], allowSecrets = false, cardFields = [] } = {}) {
  const out = [];
  for (const field of cardFields) out.push({ insert: `card.${field.name}`, detail: `${field.label}: field of the artifact`, complete: true });
  const seen = new Set();
  for (const node of nodes) {
    if (node.id === exceptId || !RESULT_KINDS.includes(node.kind)) continue;
    const key = nodeKey(node.name);
    if (seen.has(key)) continue; // two nodes with one name: the reference would be ambiguous, so it is not offered
    seen.add(key);
    for (const [field, detail] of NODE_FIELDS) out.push({ insert: `node.${key}.${field}`, detail: `${node.name}: ${detail}`, complete: !field.endsWith(".") });
  }
  const variables = new Set();
  for (const node of nodes) {
    const declared =
      node.kind === "code" ? String(node.config?.sets_variables ?? "").split("\n") : node.kind === "set" ? fieldNames(node.config?.fields) : [];
    for (const line of declared) {
      const name = line.trim();
      if (name && !variables.has(name)) {
        variables.add(name);
        out.push({ insert: `var.${name}`, detail: `set by ${node.name}`, complete: true });
      }
    }
  }
  if (allowSecrets) for (const name of secrets) out.push({ insert: `secret:${name}`, detail: "stored secret", complete: true });
  return out;
}

/** The candidates that fit what was typed: those that start with it first, then those that contain it. */
export function filterCandidates(candidates, query) {
  const wanted = query.toLowerCase();
  const starts = [];
  const contains = [];
  for (const candidate of candidates) {
    const at = candidate.insert.toLowerCase().indexOf(wanted);
    if (at === 0) starts.push(candidate);
    else if (at > 0) contains.push(candidate);
  }
  return [...starts, ...contains].slice(0, MAX_SUGGESTIONS);
}

/**
 * `text` with the completion put in place of what was typed after "${", and the new caret. A closing
 * "}" is added unless one follows already or the user has to go on typing (a data path).
 */
export function applyCompletion(text, caret, reference, candidate) {
  const rest = text.slice(caret);
  const tail = candidate.complete && rest.startsWith("}") ? rest.slice(1) : rest; // an existing "}" is taken over
  const head = `${text.slice(0, reference.start + 2)}${candidate.insert}${candidate.complete ? "}" : ""}`;
  return { text: head + tail, caret: head.length };
}
