/* The logic of the suggestions for ${...} references, without a DOM: where a reference is open at the
 * caret, which completions exist for a graph, which of them fit what was typed, and the text with a
 * completion put in. reference-suggest.js draws the popup. Hints only: nothing here validates a text
 * (the server does), and a name it does not know is simply not offered. */

import { t, tn } from "../i18n.js";
/* Which kinds leave a result in the run context, which keys of `data` they always leave and which run variables they set is
 * DATA of the kind (its manifest: `produces_result`, `result_data`, `variables`, ADR-054), handed in as `kinds`; there is no
 * list of kinds here. */
const NODE_FIELDS = [
  ["output", t("editor.reference_completion.text_node_wrote")],
  ["exit_code", t("editor.reference_completion.exit_code")],
  ["outcome", t("editor.reference_completion.pass_fail")],
  ["success", t("editor.reference_completion.true_or_false")],
  ["reason", t("editor.reference_completion.why_failed")],
  ["attempts", t("editor.reference_completion.tries")],
  ["duration_ms", t("editor.reference_completion.milliseconds")],
  ["data.", t("editor.reference_completion.its_data_then_key")],
];
const MAX_SUGGESTIONS = 40;
/* What every artifact is as `${card.NAME}` by itself (engine/context.py BUILT_IN_CARD, ADR-064), offered before its own fields. */
const CARD_BUILT_INS = ["title", "body", "text", "number"];

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
  if (query.startsWith("(")) {
    // a node by its name: the name may hold blanks until its parenthesis closes
    const close = query.indexOf(")");
    return /[}\n]/.test(query) || (close >= 0 && /\s/.test(query.slice(close + 1))) ? null : { start, query };
  }
  return /[}\s]/.test(query) ? null : { start, query };
}

/**
 * Every completion a graph offers.
 * @param {{id: string, kind: string, name: string, config?: object}[]} nodes the nodes of the graph being edited
 * @param {{exceptId?: string, secrets?: string[], allowSecrets?: boolean, cardFields?: {name: string, label: string}[], kinds?: (kind: string) => object|undefined}} options
 *   `exceptId`: the node being edited (it cannot read its own result); `secrets`: names only;
 *   `answers`: the names of the fields of the answer format an agent node reports (ADR-085), offered as its `data.NAME`;
 *   `cardFields`: the artifact fields, offered as `card.NAME` (ADR-044); `kinds`: the description of a kind (what the server
 *   says: `produces_result`, `result_data`, `variables`); a node of a kind that is not described or leaves no result is not offered
 * @returns {{insert: string, detail: string, complete: boolean, head: string, kind?: string}[]} `insert` is what goes between
 *   "${" and "}"; `complete` is false when the user continues typing (a data path); `head` is the group it belongs to
 *   ("card.", "var.", "secret:", or the node as "(Name)."), see `suggestionsFor`
 */
export function candidatesFor(nodes, { exceptId = null, secrets = [], allowSecrets = false, cardFields = [], kinds = () => undefined, contracts = () => null, answers = () => [] } = {}) {
  const out = [];
  for (const name of CARD_BUILT_INS) out.push({ insert: `card.${name}`, detail: t(`editor.reference_completion.card_${name}`), complete: true, head: "card." });
  for (const field of cardFields) out.push({ insert: `card.${field.name}`, detail: t("editor.reference_completion.label_field_artifact", { label: field.label }), complete: true, head: "card." });
  // the declared inputs of the graph being edited (its Trigger): `${input.NAME}` (ADR-083)
  for (const trigger of nodes.filter((n) => n.kind === "trigger")) {
    for (const spec of trigger.config?.inputs ?? []) out.push({ insert: `input.${spec.name}`, detail: spec.description ? `${t("editor.reference_completion.an_input")}: ${spec.description}` : t("editor.reference_completion.an_input"), complete: true, head: "input." });
  }
  for (const node of nodes) {
    if (node.id === exceptId || !node.id) continue;
    // a node that leaves a result by its kind, or an action/pipeline node whose definition declares inputs or outputs (ADR-083)
    const contract = contracts(node);
    if (!kinds(node.kind)?.produces_result && !contract) continue;
    // a node is named by its id (ADR-082): a rename changes no reference. The list shows its name as the editor shows it.
    const name = nodeLabel(node);
    const head = `node:${node.id}.`;
    const headLabel = /[()}\r\n]/.test(name) || !name ? head : `(${name}).`;
    const label = (field) => `${headLabel}${field}`;
    for (const [field, detail] of NODE_FIELDS) {
      if (contract && ["exit_code", "output"].includes(field)) continue; // an action leaves its outputs as data, not text or an exit code
      out.push({ insert: `${head}${field}`, label: label(field), detail: `${name}: ${detail}`, complete: !field.endsWith("."), head, headLabel, kind: node.kind });
    }
    // an agent node with an answer format also leaves the fields of the format as data (ADR-085)
    const paths = [...(contract ? contract.outputs : (kinds(node.kind).result_data ?? [])), ...(answers(node) ?? [])];
    for (const path of paths) out.push({ insert: `${head}data.${path}`, label: label(`data.${path}`), detail: `${name}: ${t("editor.reference_completion.its_data_path", { path })}`, complete: true, head, headLabel, kind: node.kind });
  }
  const variables = new Set();
  for (const node of nodes) {
    const spec = kinds(node.kind)?.variables;
    const text = spec ? node.config?.[spec.setting] : "";
    const declared = !spec ? [] : spec.format === "assignments" ? fieldNames(text) : String(text ?? "").split("\n");
    for (const line of declared) {
      const name = line.trim();
      if (name && !variables.has(name)) {
        variables.add(name);
        out.push({ insert: `var.${name}`, detail: t("editor.reference_completion.set_by_name", { name: node.name }), complete: true, head: "var." });
      }
    }
  }
  if (allowSecrets) for (const name of secrets) out.push({ insert: `secret:${name}`, detail: t("editor.reference_completion.stored_secret"), complete: true, head: "secret:" });
  return out;
}

/** What the editor calls a node in the list: its name (an action or pipeline node the name of what it runs, with its number when that
 * is placed more than once, ADR-082). */
export function nodeLabel(node) {
  const base = String(node.definition_name ?? node.name ?? "").trim();
  return node.placement_number ? `${base} #${node.placement_number}` : base;
}

/** `text` with every `${node:ID.field}` shown by the node's current name, `${(Name).field}`: what a reader sees under a field whose
 * text holds ids. A reference to a node that is not there says so. */
export function readableReferences(text, nodes) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return String(text ?? "").replace(/\$\{node:([0-9a-f-]{36})\.([^}\r\n]{1,200})\}/g, (_, id, rest) => {
    const found = byId.get(id);
    return found ? `\${(${nodeLabel(found)}).${rest}}` : `\${(${t("editor.reference_completion.gone")}).${rest}}`;
  });
}

/**
 * The suggestions for what was typed, in steps so that a long list never opens at once: first the groups
 * (card fields, variables, secrets) and the nodes, each one choice that goes on; once one is chosen (its head is
 * typed), what is behind it. Typing a part of a name finds the node at once.
 * @param {ReturnType<typeof candidatesFor>} all
 */
export function suggestionsFor(all, query) {
  const typed = (c) => (c.head && query.startsWith(c.head)) || (c.headLabel && query.startsWith(c.headLabel));
  const opened = all.filter(typed).sort((a, b) => b.head.length - a.head.length)[0]?.head;
  if (opened) return filterCandidates(all.filter((c) => c.head === opened), query);
  const heads = new Map();
  for (const c of all) {
    const group = heads.get(c.head) ?? { head: c.head, headLabel: c.headLabel, count: 0, kind: c.kind };
    group.count += 1;
    heads.set(c.head, group);
  }
  const labels = { "card.": () => t("editor.reference.card_of_run"), "var.": (n) => tn("editor.reference.variables", n), "secret:": (n) => tn("editor.reference.secrets", n), "input.": (n) => tn("editor.reference.inputs", n) };
  const groups = [...heads.values()].map((g) => ({ insert: g.head, label: g.headLabel, detail: labels[g.head]?.(g.count) ?? `${g.kind} node`, complete: false, head: "", icon: g.head === "card." ? "card" : undefined }));
  const order = (g) => ["card.", "input.", "var.", "secret:"].indexOf(g.insert);
  const fixed = groups.filter((g) => order(g) >= 0).sort((a, b) => order(a) - order(b));
  return filterCandidates([...fixed, ...groups.filter((g) => order(g) < 0)], query);
}

/** The candidates that fit what was typed: those that start with it first, then those that contain it. */
export function filterCandidates(candidates, query) {
  const wanted = query.toLowerCase();
  const starts = [];
  const contains = [];
  for (const candidate of candidates) {
    // what is typed matches the name form the list shows as well as the text that is inserted
    const at = [candidate.insert, candidate.label].filter(Boolean).map((text) => text.toLowerCase().indexOf(wanted)).filter((i) => i >= 0);
    if (!at.length) continue;
    (at.includes(0) ? starts : contains).push(candidate);
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
