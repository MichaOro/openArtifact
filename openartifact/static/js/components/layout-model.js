/* The pure part of arranging a window (ADR-063): the structure of a manifest window as the arrange view shows it, the moves
 * of a section or a field (by drop or by key), and the layout document that is saved. No DOM: tests/js/layout-model.test.mjs.
 *
 * Two kinds of window share the model:
 *  - a *form* (ui/forms/*.yaml, form-view.js): sections in one or two columns (a `full` section is a row of its own);
 *    a section's fields are shown or folded away ("More options");
 *  - the settings of a *node* kind (graph/nodes/*.yaml): the areas Definition and Behaviour (and areas of the user's own) in
 *    order, each with its settings in order; a group of settings (the rows of one condition) is one entry that moves as a whole.
 *
 * In both a field (a setting) may sit in ANY area: moving it changes its place only. The user may add areas of their own
 * (`custom: true`, a plain title of 1 to 40 characters, at most 12): an area is a container and may be deleted while it is empty.
 *
 * A structure is `{mode: "form"|"node", sections: [{key, title, custom, column, fields: [{key, label, tag, advanced, required}]}],
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
        ...(f.visible_when ? { when: whenText(f.visible_when) } : {}),
      })),
    });
  };
  const { blocks } = planForm(everything, {}, { columns: manifest.columns ?? 2, expanded: new Set(manifest.sections.map((s) => s.key)) });
  for (const block of blocks) {
    if (block.full) add(block.full, "full");
    else block.columns.forEach((lane, at) => lane.forEach((plan) => add(plan, at + 1)));
  }
  // the areas of a saved layout: which ones are the user's own, and the empty ones (the form does not draw those)
  const areas = manifest.layout?.areas ?? [];
  const custom = new Set(areas.filter((a) => a.custom).map((a) => a.key));
  for (const section of sections) section.custom = custom.has(section.key);
  for (const [at, area] of areas.entries()) {
    if (sections.some((x) => x.key === area.key)) continue;
    const previous = areas.slice(0, at).reverse().find((a) => sections.some((x) => x.key === a.key));
    const place = previous ? sections.findIndex((x) => x.key === previous.key) + 1 : 0;
    sections.splice(place, 0, { key: area.key, title: area.title, custom: Boolean(area.custom), column: area.column === 2 ? 2 : 1, fields: [] });
  }
  return { mode: "form", sections, fixed: [], columns: manifest.columns ?? 2 };
}

/** What a conditional field waits for, as a short text for its tag: "type: github_pat" or "type: a, b". */
function whenText(when) {
  const values = when.in ?? (when.equals !== undefined && when.equals !== null ? [when.equals] : []);
  return values.length ? `${when.field}: ${values.join(", ")}` : when.field;
}

/** The entries of the settings of a node kind per section, as the server counts them (a run of settings of one group is
 * one entry `group:<name>`). `skip` are the keys the kind draws itself: they are not entries. */
export function nodeEntries(settings, skip = []) {
  const sections = new Map();
  const seen = new Map();
  for (const setting of settings) {
    if (skip.includes(setting.key)) continue;
    const section = setting.section ?? "definition"; // the area it sits in now (the server puts the saved placement in)
    const group = setting.group ?? null;
    const key = group ? `group:${group}` : setting.key;
    if (seen.has(key)) {
      seen.get(key).count += 1;
      continue;
    }
    const entry = { key, label: group ?? setting.label, tag: group ? "group" : (setting.level ?? "core"), count: 1, advanced: false, required: false };
    seen.set(key, entry);
    (sections.get(section) ?? sections.set(section, []).get(section)).push(entry);
  }
  return sections;
}

/**
 * The structure of the window of a node kind: its areas in the order the kind has now (`type.layout.sections`; the user's
 * own with their titles in `type.layout.titles`). Definition and Behaviour are always there, even when empty, so a setting
 * can be dropped into either.
 * @param {object} type the description of the kind (GET /api/node-types)
 * @param {{titles: Record<string,string>, skip?: string[], fixed?: string[]}} options `fixed`: names of blocks the kind draws itself
 */
export function nodeStructure(type, { titles, skip = [], fixed = [] }) {
  const entries = nodeEntries(type.settings ?? [], skip);
  const order = [...(type.layout?.sections ?? [])];
  for (const key of ["definition", "behaviour"]) if (!order.includes(key)) order.push(key);
  const own = type.layout?.titles ?? {};
  return {
    mode: "node",
    sections: order.map((key, at) => ({
      key,
      title: titles[key] ?? own[key] ?? key,
      custom: !(key in titles),
      column: at + 1,
      fields: entries.get(key) ?? [],
    })),
    fixed,
  };
}

/** The document the server stores (`PUT /api/ui-layouts/...`). */
export function toLayout(structure) {
  const own = (s) => (s.custom ? { title: s.title } : {});
  if (structure.mode === "node") return { sections: structure.sections.map((s) => ({ key: s.key, fields: s.fields.map((f) => f.key), ...own(s) })) };
  return {
    sections: structure.sections.map((s) => ({
      key: s.key,
      column: s.column,
      fields: s.fields.filter((f) => !f.advanced).map((f) => f.key),
      advanced: s.fields.filter((f) => f.advanced).map((f) => f.key),
      ...own(s),
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

/**
 * Put a field into the shown list or the folded list of a section at an index (counted without the field). `toSection`
 * names another section (an area): a field may sit in any of them. A required field is never folded away; a node window has
 * one list per area.
 */
export function placeField(structure, sectionKey, fieldKey, { advanced = false, index = 0, toSection = sectionKey }) {
  const next = clone(structure);
  const from = findSection(next, sectionKey);
  const to = findSection(next, toSection);
  const field = from?.fields.find((f) => f.key === fieldKey);
  if (!field || !to) return null;
  if (structure.mode === "node") advanced = false;
  if (advanced && field.required) return null;
  from.fields = from.fields.filter((f) => f.key !== fieldKey);
  const rest = to.fields;
  const shown = rest.filter((f) => !f.advanced);
  const folded = rest.filter((f) => f.advanced);
  field.advanced = advanced;
  const list = advanced ? folded : shown;
  list.splice(Math.min(index, list.length), 0, field);
  to.fields = structure.mode === "node" ? list : [...shown, ...folded];
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

/** The key of the section (area) that holds a field now, or null. */
export function sectionOfField(structure, fieldKey) {
  return structure.sections.find((s) => s.fields.some((f) => f.key === fieldKey))?.key ?? null;
}

/**
 * A field one step by the keyboard. Up and down move inside its list; down from the end of the shown fields goes to the
 * folded group (not for a required field, nor in a node window), up from the start of the folded group back to the shown
 * ones; past the end of the last list it goes on into the next area (up: the previous one). Left and right go to the
 * previous or next area at the same position.
 */
export function moveFieldBy(structure, sectionKey, fieldKey, direction) {
  const at = fieldPlace(structure, sectionKey, fieldKey);
  if (!at || !["up", "down", "left", "right"].includes(direction)) return null;
  const order = structure.sections.map((s) => s.key);
  const here = order.indexOf(sectionKey);
  const section = findSection(structure, sectionKey);
  const sizeOf = (sec, advanced) => sec.fields.filter((f) => Boolean(f.advanced) === advanced).length;
  const crossTo = (to, advanced, index) => {
    const target = structure.sections[to];
    if (!target) return null;
    return placeField(structure, sectionKey, fieldKey, { toSection: target.key, advanced, index });
  };
  if (direction === "left" || direction === "right") {
    const to = here + (direction === "left" ? -1 : 1);
    if (to < 0 || to >= order.length) return null;
    const shown = sizeOf(structure.sections[to], false);
    return crossTo(to, false, Math.min(at.index, shown));
  }
  const step = direction === "up" ? -1 : 1;
  const index = at.index + step;
  if (index >= 0 && index < sizeOf(section, at.advanced)) return placeField(structure, sectionKey, fieldKey, { advanced: at.advanced, index });
  if (structure.mode !== "node") {
    if (!at.advanced && direction === "down" && !section.fields.find((f) => f.key === fieldKey)?.required) {
      return placeField(structure, sectionKey, fieldKey, { advanced: true, index: 0 });
    }
    if (at.advanced && direction === "up") return placeField(structure, sectionKey, fieldKey, { advanced: false, index: Number.MAX_SAFE_INTEGER });
  }
  const to = here + step;
  if (to < 0 || to >= order.length) return null;
  return crossTo(to, false, direction === "down" ? 0 : Number.MAX_SAFE_INTEGER);
}

// ── areas of the user's own ───────────────────────────────────────────

export const MAX_CUSTOM = 12;
export const TITLE_MAX = 40;

export const customCount = (structure) => structure.sections.filter((s) => s.custom).length;

/** A new area key: `custom_` and a few lower-case letters or digits (the server's pattern). */
export function newAreaKey(random = Math.random) {
  let id = "";
  while (id.length < 6) id += Math.floor(random() * 36).toString(36);
  return `custom_${id}`;
}

/** Add an empty area of one's own at the end; null at the limit or with a title that is not 1 to 40 characters. */
export function addArea(structure, title, key = newAreaKey()) {
  const clean = String(title ?? "").trim();
  if (!clean || clean.length > TITLE_MAX || customCount(structure) >= MAX_CUSTOM) return null;
  if (structure.sections.some((s) => s.key === key)) return null;
  const next = clone(structure);
  next.sections.push({ key, title: clean, custom: true, column: next.mode === "node" ? next.sections.length + 1 : 1, fields: [] });
  return next;
}

/** Give an area of one's own another title; null for a shipped area or a title that is not 1 to 40 characters. */
export function renameArea(structure, key, title) {
  const clean = String(title ?? "").trim();
  const section = findSection(structure, key);
  if (!section?.custom || !clean || clean.length > TITLE_MAX) return null;
  const next = clone(structure);
  findSection(next, key).title = clean;
  return next;
}

/** Take away an area of one's own while it is empty; null for a shipped one or one that still holds something. */
export function deleteArea(structure, key) {
  const section = findSection(structure, key);
  if (!section?.custom || section.fields.length) return null;
  const next = clone(structure);
  next.sections = next.sections.filter((s) => s.key !== key);
  if (next.mode === "node") next.sections.forEach((s, at) => (s.column = at + 1));
  return next;
}

// ── dropping ──────────────────────────────────────────────────────────

/**
 * How many of `rects` come before the pointer in reading order: the slot a drop there takes among them. A box is before the
 * pointer when the pointer is below it, or level with it (inside its rows) and right of its middle. Works for boxes in a row
 * and for boxes stacked in one column.
 * @param {{left: number, right: number, top: number, bottom: number}[]} rects
 */
export function slotAmong(rects, x, y) {
  return rects.filter((r) => {
    if (y > r.bottom) return true; // the pointer is below it
    if (y < r.top) return false; // above it
    // level with it: a box that shares its rows with another is before the pointer once the pointer is right of its middle;
    // one that stands alone in its rows (a stacked column) once the pointer is below its middle
    const shares = rects.some((o) => o !== r && o.top < r.bottom && o.bottom > r.top);
    return shares ? x > (r.left + r.right) / 2 : y > (r.top + r.bottom) / 2;
  }).length;
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
  const area = findSection(structure, keys.section);
  const field = area?.fields.find((f) => f.key === keys.field);
  if (keys.from && keys.from !== keys.section) return labels.fieldArea({ title: field.label, area: area.title, position: at.index + 1 });
  return (at.advanced ? labels.folded : labels.field)({ title: field.label, position: at.index + 1 });
}
