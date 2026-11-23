/* Pure logic of the artifact fields (no DOM): names, blank fields, what is sent, server messages, what a card shows. */

export const KINDS = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes / no" },
  { value: "choice", label: "Choice" },
];

/** A field name from its label: lowercase letters, digits and underscores, starting with a letter, at most 32. */
export function nameFromLabel(label) {
  const folded = label
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const named = /^[a-z]/.test(folded) ? folded : folded ? `f_${folded}` : "";
  return named.slice(0, 32).replace(/_+$/, "");
}

/** An empty field of a kind, as the editor holds it (every value a string or boolean, as the controls give them). */
export function blankField(kind = "text") {
  return { name: "", label: "", kind, default: "", options: "", max_length: "", min_value: "", max_value: "", integer_only: false, nameEdited: false };
}

/** A stored field as the editor holds it. */
export function editable(field) {
  const text = (value) => (value === null || value === undefined ? "" : String(value));
  return {
    name: field.name,
    label: field.label,
    kind: field.kind,
    default: text(field.default),
    options: (field.options ?? []).join("\n"),
    max_length: text(field.max_length),
    min_value: text(field.min_value),
    max_value: text(field.max_value),
    integer_only: Boolean(field.integer_only),
    nameEdited: true,
  };
}

const number = (text) => (text === "" || text === null ? null : Number(text));

/** The request body for one editor field: only what its kind uses; a blank default is none. */
export function toWrite(field) {
  const out = { name: field.name.trim(), label: field.label.trim(), kind: field.kind, default: null, options: [] };
  const dflt = field.default;
  if (field.kind === "choice") out.options = field.options.split("\n").map((o) => o.trim()).filter(Boolean);
  if (field.kind === "text") out.max_length = number(field.max_length);
  if (field.kind === "number") {
    out.min_value = number(field.min_value);
    out.max_value = number(field.max_value);
    out.integer_only = field.integer_only;
  }
  if (dflt !== "" && dflt !== null) {
    if (field.kind === "number") out.default = Number(dflt);
    else if (field.kind === "boolean") out.default = dflt === "true";
    else out.default = dflt;
  }
  return out;
}

/**
 * The server's refusal: lines `Field NAME: message`, `Name: message`, or something else.
 * @returns {{byField: Map<string, string>, name: string, other: string[]}}
 */
export function parseProblems(detail) {
  const byField = new Map();
  const other = [];
  let name = "";
  for (const line of String(detail ?? "").split("\n")) {
    const text = line.trim();
    const field = /^Field ([^:]{1,40}): (.+)$/.exec(text);
    if (field) {
      byField.set(field[1], [byField.get(field[1]), field[2]].filter(Boolean).join(" "));
    } else if (text.startsWith("Name: ")) {
      name = text.slice(6);
    } else if (text) {
      other.push(text);
    }
  }
  return { byField, name, other };
}

/** What a card shows for a field: its stored value, else its default, else nothing (null). */
export function effectiveValue(field, values) {
  const stored = values?.[field.name];
  if (stored !== undefined && stored !== null && stored !== "") return stored;
  return field.default ?? null;
}

/** The value a control gives for a field: a number, true/false, a text or null (cleared). */
export function valueOf(field, raw) {
  if (field.kind === "boolean") return raw === true || raw === "true";
  const text = String(raw ?? "").trim();
  if (text === "") return null;
  return field.kind === "number" ? Number(text) : text;
}

/** Which fields lose stored values when the editor's list is saved: [{label, count}] of removed fields that have any. */
export function removedWithValues(before, afterNames) {
  const kept = new Set(afterNames);
  return before.filter((f) => !kept.has(f.name) && f.artifact_count > 0).map((f) => ({ label: f.label, count: f.artifact_count }));
}
