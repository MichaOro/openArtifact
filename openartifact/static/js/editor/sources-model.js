/* The list of sources of a Build Context node (ADR-078) as pure functions: nothing here touches the document, so the rules of the list
 * (what a new entry starts with, what is still free to add, what a typed value must be, how the caption reads) are tested on their
 * own. A source is `{source, count?, detail?, names?}`; the specs come from the server (`Setting.describe`: `sources`, `max_sources`)
 * and are the one place that says which sources exist and which options each takes (graph/context_sources.py). The functions return
 * a new list and never change the one they were given. */

/** What a node without a saved list builds from: the setting's default (graph/context_sources.py DEFAULT_SOURCES; a test keeps both equal). */
export const DEFAULT_SOURCES = [{ source: "card" }, { source: "comments", count: 20 }];

/** The spec of a source by its key (undefined: the server does not know it). */
export function specOf(specs, key) {
  return specs.find((spec) => spec.key === key);
}

/** What a source starts with when it is added: every option it takes, at its default. */
export function startEntry(spec) {
  const entry = { source: spec.key };
  if (spec.count) entry.count = spec.count[2];
  if (spec.detail) entry.detail = spec.detail[0];
  if (spec.names) entry.names = [];
  return entry;
}

/** The specs that are not in the list yet, in the order of the menu (a source can be used once). */
export function unused(list, specs) {
  const used = new Set(list.map((entry) => entry.source));
  return specs.filter((spec) => !used.has(spec.key));
}

export function addSource(list, spec) {
  return [...list, startEntry(spec)];
}

export function removeSource(list, index) {
  return list.filter((_, i) => i !== index);
}

/** The entry at `from` moved to place `to` (the others keep their order). */
export function moveSource(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export function setOption(list, index, name, value) {
  return list.map((entry, i) => (i === index ? { ...entry, [name]: value } : entry));
}

/** The node names of a textarea, one per line (blank lines and spaces around a name are dropped). */
export function parseNames(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/**
 * What is wrong with an entry, as `{code, params}` (the control makes the text of it), or null: the count outside its bounds, too many or too long node
 * names, a node named twice. The server checks the same rules; this only tells the user before a request.
 */
export function entryProblem(entry, spec) {
  if (spec.count) {
    const [min, max] = spec.count;
    if (!Number.isInteger(entry.count) || entry.count < min || entry.count > max) {
      return { code: "count_bounds", params: { label: spec.label, min, max } };
    }
  }
  if (spec.names) {
    const names = entry.names ?? [];
    if (names.length > spec.names.max) return { code: "names_many", params: { label: spec.label, max: spec.names.max } };
    if (names.some((name) => name.length > spec.names.max_chars)) return { code: "names_long", params: { label: spec.label, max: spec.names.max_chars } };
    if (new Set(names).size !== names.length) return { code: "names_twice", params: { label: spec.label } };
  }
  return null;
}

/** The first problem of the list (an unknown source is the server's to refuse), or null. */
export function listProblem(list, specs) {
  for (const entry of list) {
    const spec = specOf(specs, entry.source);
    const problem = spec ? entryProblem(entry, spec) : null;
    if (problem) return problem;
  }
  return null;
}

/** The caption of a node's card: the names of its first sources ("Card, Comments +1 more"); `label(source)` is the short name. */
export function summarize(list, label, say) {
  if (!Array.isArray(list) || !list.length) return say.empty;
  const names = list.map((entry) => label(entry.source));
  return names.length > 2 ? `${names.slice(0, 2).join(", ")} ${say.more(names.length - 2)}` : names.join(", ");
}

/** A size for reading, not for typing: "812 B", "5.1 KiB", "1.5 MiB" (one decimal; the exact bytes are in the step's data). */
export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "0 B";
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
}
