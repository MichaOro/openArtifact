/* The pure part of arranging a window (ADR-063): the structure of a manifest window as the arrange view shows it, the moves
 * of a section or a field (by drop or by key), and the layout document that is saved. No DOM: tests/js/layout-model.test.mjs.
 *
 * Two kinds of window share the model:
 *  - a *form* (ui/forms/*.yaml, form-view.js): sections in one or two columns (a `full` section is a row of its own);
 *    a section's fields are shown or folded away ("More options");
 *  - the settings of a *node* kind (graph/nodes/*.yaml): the two sides Definition and Behaviour, left to right, each with its
 *    settings in order; a group of settings (the rows of one condition) is one entry that moves as a whole.
 *
 * A structure is `{mode: "form"|"node", sections: [{key, title, column, fields: [{key, label, tag, advanced, required}]}],
 * fixed: string[]}`; the moves return a new structure (or null when nothing can move there). */
import { planForm } from "./form-plan.js";

const clone = (value) => JSON.parse(JSON.stringify(value));

// ── building a structure ──────────────────────────────────────────────

/** The structure of a form manifest with every field in it (the ones a `visible_when` hides today too) and every
 * `auto` column resolved to the column the section sits in now. */
export function formStructure(manifest) {
  const everything = {
    ...manifest,
    sections: manifest.sections.map((s) => ({ ...s, fields: s.fields.map((f) => ({ ...f, visible_when: undefined })) })),
  };
  const byKey = new Map(manifest.sections.map((s) => [s.key, s]));
  const sections = [];
  const add = (plan, column) => {
    const source = byKey.get(plan.key);
    sections.push({
      key: source.key,
      title: source.title,
      column,
      fields: source.fields.map((f) => ({
        key: f.key,
        label: f.label,
        tag: f.widget,
        advanced: Boolean(f.advanced),
        required: Boolean(f.required),
        condition: Boolean(f.visible_when),
      })),
    });
  };
  const { blocks } = planForm(everything, {}, { columns: 2, expanded: new Set(manifest.sections.map((s) => s.key)) });
  for (const block of blocks) {
    if (block.full) add(block.full, "full");
    else block.columns.forEach((lane, at) => lane.forEach((plan) => add(plan, at + 1)));
  }
  return { mode: "form", sections, fixed: [] };
}

/** The entries of the settings of a node kind per section, as the server counts them (a run of settings of one group is
 * one entry `group:<name>`). `skip` are the keys the kind draws itself: they are not entries. */
export function nodeEntries(settings, skip = []) {
  const sections = new Map();
  let last = null;
  for (const setting of settings) {
    if (skip.includes(setting.key)) continue;
    const section = setting.section ?? "definition";
    const group = setting.group ?? null;
    const key = group ? `group:${group}` : setting.key;
    const list = sections.get(section) ?? sections.set(section, []).get(section);
    if (group && last === `${section}:${key}`) {
      list.at(-1).count += 1;
      continue;
    }
    list.push({ key, label: group ?? setting.label, tag: group ? "group" : (setting.level ?? "core"), count: 1, advanced: false, required: false });
    last = group ? `${section}:${key}` : null;
  }
  return sections;
}

/**
 * The structure of the window of a node kind: Definition and Behaviour in the order the kind has now (`type.layout.sections`).
 * @param {object} type the description of the kind (GET /api/node-types)
 * @param {{titles: Record<string,string>, skip?: string[], fixed?: string[]}} options `fixed`: names of blocks the kind draws itself
 */
export function nodeStructure(type, { titles, skip = [], fixed = [] }) {
  const entries = nodeEntries(type.settings ?? [], skip);
  const order = (type.layout?.sections ?? ["definition", "behaviour"]).filter((k) => entries.has(k));
  for (const key of ["definition", "behaviour"]) if (entries.has(key) && !order.includes(key)) order.push(key);
  return {
    mode: "node",
    sections: order.map((key, at) => ({ key, title: titles[key] ?? key, column: at + 1, fields: entries.get(key) })),
    fixed,
  };
}

/** The document the server stores (`PUT /api/ui-layouts/...`). */
export function toLayout(structure) {
  if (structure.mode === "node") return { sections: structure.sections.map((s) => ({ key: s.key, fields: s.fields.map((f) => f.key) })) };
  return {
    sections: structure.sections.map((s) => ({
      key: s.key,
      column: s.column,
      fields: s.fields.filter((f) => !f.advanced).map((f) => f.key),
      advanced: s.fields.filter((f) => f.advanced).map((f) => f.key),
    })),
  };
}

export const sameLayout = (a, b) => JSON.stringify(toLayout(a)) === JSON.stringify(toLayout(b));

// ── sections ──────────────────────────────────────────────────────────

/** The blocks of a form: a `full` section is a block of its own, the sections between two of them form a block with two lanes. */
export function blocksOf(structure) {
  const blocks = [];
  for (const section of structure.sections) {
    if (section.column === "full") {
      blocks.push({ full: section });
      continue;
    }
    let block = blocks.at(-1);
    if (!block || block.full) blocks.push((block = { lanes: [[], []] }));
    block.lanes[section.column === 2 ? 1 : 0].push(section);
  }
  return blocks;
}

function flatten(blocks, mode) {
  const sections = [];
  for (const block of blocks) {
    if (block.full) sections.push(block.full);
    else block.lanes.forEach((lane, at) => lane.forEach((s) => sections.push({ ...s, column: mode === "node" ? sections.length + 1 : at + 1 })));
  }
  return sections;
}

const findSection = (structure, key) => structure.sections.find((s) => s.key === key);

/**
 * Put a section into a lane of a block at an index (counted without the section itself). A `full` section stays full and
 * only changes its place among the blocks (`block` is then its new place among them); a node window has no lanes: its sections are
 * its sides, and the section takes the side `lane` (0 = left).
 */
export function placeSection(structure, key, { block = 0, lane = 0, index = 0 }) {
  const section = findSection(structure, key);
  if (!section) return null;
  if (structure.mode === "node") {
    const rest = structure.sections.filter((s) => s.key !== key);
    rest.splice(Math.min(lane, rest.length), 0, section);
    return { ...structure, sections: rest.map((s, at) => ({ ...s, column: at + 1 })) };
  }
  const next = clone(structure);
  const blocks = blocksOf(next);
  const moving = findSection(next, key);
  if (section.column === "full") {
    const at = blocks.findIndex((b) => b.full?.key === key);
    const [row] = blocks.splice(at, 1);
    blocks.splice(Math.min(block, blocks.length), 0, row);
    return { ...next, sections: flatten(blocks, "form") };
  }
  for (const b of blocks) if (b.lanes) b.lanes = b.lanes.map((l) => l.filter((s) => s.key !== key));
  const target = blocks[block]?.lanes;
  if (!target) return null;
  target[lane].splice(Math.min(index, target[lane].length), 0, moving);
  return { ...next, sections: flatten(blocks, "form") };
}

/** Where a section is: `{block, lane, index}` (a node window: `{block: 0, lane: its side, index: 0}`). */
export function sectionPlace(structure, key) {
  if (structure.mode === "node") return { block: 0, lane: structure.sections.findIndex((s) => s.key === key), index: 0 };
  const blocks = blocksOf(structure);
  for (const [block, b] of blocks.entries()) {
    if (b.full?.key === key) return { block, lane: 0, index: 0, full: true };
    for (const [lane, list] of (b.lanes ?? []).entries()) {
      const index = list.findIndex((s) => s.key === key);
      if (index >= 0) return { block, lane, index };
    }
  }
  return null;
}

/** A section one step by the keyboard: `up`/`down` in its lane, `left`/`right` to the other column (a node: to the other side). */
export function moveSectionBy(structure, key, direction) {
  const at = sectionPlace(structure, key);
  if (!at) return null;
  if (structure.mode === "node") {
    const side = at.lane + (direction === "left" || direction === "up" ? -1 : 1);
    if (side < 0 || side >= structure.sections.length) return null;
    return placeSection(structure, key, { lane: side });
  }
  if (at.full) {
    const blocks = blocksOf(structure).length;
    const to = at.block + (direction === "up" ? -1 : direction === "down" ? 1 : 0);
    if (to === at.block || to < 0 || to >= blocks) return null;
    const next = clone(structure);
    const list = blocksOf(next);
    const [moved] = list.splice(at.block, 1);
    list.splice(to, 0, moved);
    return { ...next, sections: flatten(list, "form") };
  }
  if (direction === "up" || direction === "down") {
    const lane = blocksOf(structure)[at.block].lanes[at.lane];
    const index = at.index + (direction === "up" ? -1 : 1);
    if (index < 0 || index >= lane.length) return null;
    return placeSection(structure, key, { ...at, index });
  }
  const other = direction === "left" ? 0 : 1;
  if (other === at.lane) return null;
  return placeSection(structure, key, { block: at.block, lane: other, index: at.index });
}

// ── fields ────────────────────────────────────────────────────────────

/** Put a field of a section into its shown list or its folded list at an index (counted without the field). A required field is
 * never folded away; a node window has one list. */
export function placeField(structure, sectionKey, fieldKey, { advanced = false, index = 0 }) {
  const next = clone(structure);
  const section = findSection(next, sectionKey);
  const field = section?.fields.find((f) => f.key === fieldKey);
  if (!field) return null;
  if (structure.mode === "node") advanced = false;
  if (advanced && field.required) return null;
  const rest = section.fields.filter((f) => f.key !== fieldKey);
  const shown = rest.filter((f) => !f.advanced);
  const folded = rest.filter((f) => f.advanced);
  field.advanced = advanced;
  const list = advanced ? folded : shown;
  list.splice(Math.min(index, list.length), 0, field);
  section.fields = structure.mode === "node" ? list : [...shown, ...folded];
  return next;
}

/** Where a field is: `{advanced, index}` within its list. */
export function fieldPlace(structure, sectionKey, fieldKey) {
  const section = findSection(structure, sectionKey);
  const field = section?.fields.find((f) => f.key === fieldKey);
  if (!field) return null;
  const list = section.fields.filter((f) => Boolean(f.advanced) === Boolean(field.advanced));
  return { advanced: Boolean(field.advanced), index: list.findIndex((f) => f.key === fieldKey) };
}

/** A field one step by the keyboard: up and down in its list; down from the end of the shown fields goes to the folded group
 * (not for a required field, nor in a node window), up from the start of the folded group back to the shown ones. */
export function moveFieldBy(structure, sectionKey, fieldKey, direction) {
  const at = fieldPlace(structure, sectionKey, fieldKey);
  if (!at || (direction !== "up" && direction !== "down")) return null;
  const section = findSection(structure, sectionKey);
  const size = section.fields.filter((f) => Boolean(f.advanced) === at.advanced).length;
  const step = direction === "up" ? -1 : 1;
  const index = at.index + step;
  if (index >= 0 && index < size) return placeField(structure, sectionKey, fieldKey, { advanced: at.advanced, index });
  if (structure.mode === "node") return null;
  if (!at.advanced && direction === "down") return placeField(structure, sectionKey, fieldKey, { advanced: true, index: 0 });
  if (at.advanced && direction === "up") return placeField(structure, sectionKey, fieldKey, { advanced: false, index: Number.MAX_SAFE_INTEGER });
  return null;
}

/** The sentence a screen reader hears after a move. `labels` names the places. */
export function movedText(structure, kind, keys, labels) {
  if (kind === "section") {
    const place = sectionPlace(structure, keys.section);
    const title = findSection(structure, keys.section)?.title ?? keys.section;
    return structure.mode === "node"
      ? labels.side({ title, position: place.lane + 1 })
      : place.full
        ? labels.row({ title, position: place.block + 1 })
        : labels.column({ title, column: place.lane + 1, position: place.index + 1 });
  }
  const at = fieldPlace(structure, keys.section, keys.field);
  const field = findSection(structure, keys.section)?.fields.find((f) => f.key === keys.field);
  return (at.advanced ? labels.folded : labels.field)({ title: field.label, position: at.index + 1 });
}
