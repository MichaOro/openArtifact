/* Copy and paste of nodes, without a DOM: what a copy holds, and the plan of what a paste creates. The editor
 * (editor.js) keeps the clipboard (localStorage, so another action or pipeline editor can paste it) and makes the
 * calls the plan describes.
 *
 * A copy is the chosen nodes and the connections between them (a stage takes its actions along); the fixed nodes
 * (trigger, output, complete) belong to the graph and are never copied. A paste gives every node a new name that
 * stays unique ("Fetch copy", "Fetch copy 2"), because a reference finds a node by its name. */

import { t } from "../i18n.js";
const FIXED = new Set(["trigger", "output", "complete"]);
const COPY_SUFFIX = / copy( \d+)?$/;

/** A name for a copy that is not in `taken`. */
export function uniqueName(name, taken) {
  const base = name.replace(COPY_SUFFIX, "");
  let candidate = `${base} copy`;
  for (let n = 2; taken.has(candidate); n += 1) candidate = `${base} copy ${n}`;
  return candidate;
}

/**
 * What a copy of these nodes holds (null when none can be copied).
 * @param {object[]} nodes every node of the graph @param {object[]} edges every edge @param {string[]} ids the chosen ones
 * @param {"pipeline"|"action"} scope where the copy was made
 */
export function copyOf(nodes, edges, ids, scope) {
  const chosen = new Set(ids);
  const picked = nodes.filter((n) => !FIXED.has(n.kind) && (chosen.has(n.id) || chosen.has(n.stage_id)));
  if (!picked.length) return null;
  const inside = new Set(picked.map((n) => n.id));
  const ordered = [...picked.filter((n) => !n.stage_id || !inside.has(n.stage_id)), ...picked.filter((n) => n.stage_id && inside.has(n.stage_id))];
  return {
    version: 1,
    scope,
    nodes: ordered.map((n) => ({
      key: n.id,
      kind: n.kind,
      name: n.name,
      x: n.x,
      y: n.y,
      width: n.width,
      height: n.height,
      stage: n.stage_id && inside.has(n.stage_id) ? n.stage_id : null,
      originalStage: n.stage_id ?? null,
      seconds: n.seconds ?? null,
      config: structuredClone(n.config ?? {}),
      definition_id: n.definition_id ?? null,
    })),
    edges: edges
      .filter((e) => inside.has(e.source_id) && inside.has(e.target_id))
      .map((e) => ({ source: e.source_id, source_port: e.source_port, source_slot: e.source_slot, target: e.target_id, target_port: e.target_port, target_slot: e.target_slot, style: e.style })),
    // a tool copied without its agent remembers the agent it hung on (a paste in the same graph attaches it again)
    attached: Object.fromEntries(edges.filter((e) => e.target_port === "tools" && inside.has(e.source_id) && !inside.has(e.target_id)).map((e) => [e.source_id, e.target_id])),
  };
}

/**
 * What pasting a copy creates.
 * @param {object} copy from `copyOf` @param {{offset: number, names: Set<string>, stageFor: (oldStageId: string|null) => string|null, allowed?: Set<string>}} options
 *   `offset`: how far top-level nodes move; `names`: the names in the graph now; `stageFor`: the stage a lone action
 *   goes to (given the one it came from); `allowed`: the kinds this editor may add (all when not given)
 * @returns {{items: object[], edges: object[], skipped: string[], error?: string}}
 */
export function pastePlan(copy, { offset, names, stageFor, allowed = null }) {
  const taken = new Set(names);
  const skipped = [];
  const items = [];
  for (const node of copy.nodes) {
    if (allowed && !allowed.has(node.kind)) {
      skipped.push(node.kind);
      continue;
    }
    const item = { ...node, config: structuredClone(node.config) };
    if (node.stage) {
      // inside a stage that is pasted too: the place inside it stays
    } else if (node.originalStage) {
      const stage = stageFor(node.originalStage);
      if (!stage) return { items: [], edges: [], skipped, error: t("editor.clipboard.select_stage_paste_actions_into") };
      item.existingStage = stage;
      item.x = node.x + offset;
      item.y = node.y + offset;
    } else {
      item.x = node.x + offset;
      item.y = node.y + offset;
    }
    item.name = uniqueName(node.name, taken);
    taken.add(item.name);
    items.push(item);
  }
  const made = new Set(items.map((i) => i.key));
  return { items, skipped, edges: copy.edges.filter((e) => made.has(e.source) && made.has(e.target)) };
}

/**
 * `value` (a setting, any depth) with every `node:OLD` of a reference (`${node:OLD.output}`, ADR-082) turned into `node:NEW` for the nodes
 * of `idMap` (old id to new id): what a paste makes of the references between the nodes it copies, so the copy reads its own copy, not the
 * original. A reference to a node that was not copied stays as it is.
 */
export function remapReferences(value, idMap) {
  if (typeof value === "string") return value.replace(/node:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g, (all, id) => (idMap.has(id) ? `node:${idMap.get(id)}` : all));
  if (Array.isArray(value)) return value.map((item) => remapReferences(item, idMap));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, remapReferences(item, idMap)]));
  return value;
}

/** The settings of `config` that a paste changes (`{key: new value}`), or null when it changes none. */
export function remappedConfig(config, idMap) {
  const changed = {};
  for (const [key, value] of Object.entries(config ?? {})) {
    const next = remapReferences(value, idMap);
    if (JSON.stringify(next) !== JSON.stringify(value)) changed[key] = next;
  }
  return Object.keys(changed).length ? changed : null;
}
