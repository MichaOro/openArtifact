/* Pure logic of the artifact fields (no DOM): names, blank fields, what is sent, server messages, what a card shows. */

import { t } from "../i18n.js";
/** The field types the editor offers: a choice is a single or a multi select (ADR-050). */
export const KINDS = [
  { value: "text", label: t("artifact_fields.model.text") },
  { value: "number", label: t("artifact_fields.model.number") },
  { value: "boolean", label: t("artifact_fields.model.yes_no") },
  { value: "single", label: t("artifact_fields.model.single_select") },
  { value: "multi", label: t("artifact_fields.model.multi_select") },
];

const typeOf = (field) => (field.kind === "choice" ? (field.multiple ? "multi" : "single") : field.kind);
export const isSelect = (type) => type === "single" || type === "multi";

/** The words for a field's type in the list ("Single select · 3 options"). */
export function typeText(state) {
  const label = KINDS.find((k) => k.value === state.type)?.label ?? state.type;
  if (!isSelect(state.type)) return label;
  const n = state.options.length;
  return `${label} · ${n} option${n === 1 ? "" : "s"}`;
}

/** A field name from its label: lowercase letters, digits and underscores, starting with a letter, at most 32. */
export function nameFromLabel(label) {
  const folded = label
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const named = /^[a-z]/.test(folded) ? folded : folded ? `f_${folded}` : "";
  return named.slice(0, 32).replace(/_+$/, "");
}

let uid = 0;
const option = (text, original = null) => ({ uid: (uid += 1), text, original });

/** An empty field of a type, as the editor holds it; it is new, so its name may still change. */
export function blankField(type = "text") {
  return { uid: (uid += 1), saved: false, originalName: null, name: "", label: "", type, default: type === "multi" ? [] : "", options: [], max_length: "", min_value: "", max_value: "", integer_only: false, nameEdited: false, artifact_count: 0 };
}

/** A stored field as the editor holds it: options keep their original text, so a rename can be told apart. */
export function editable(field) {
  const text = (value) => (value === null || value === undefined ? "" : String(value));
  const type = typeOf(field);
  return {
    uid: (uid += 1),
    saved: true,
    originalName: field.name,
    name: field.name,
    label: field.label,
    type,
    default: type === "multi" ? [...(field.default ?? [])] : text(field.default),
    options: (field.options ?? []).map((o) => option(o, o)),
    max_length: text(field.max_length),
    min_value: text(field.min_value),
    max_value: text(field.max_value),
    integer_only: Boolean(field.integer_only),
    nameEdited: true,
    artifact_count: field.artifact_count ?? 0,
  };
}

/** A new allowed value of a select. */
export const newOption = (text) => option(text);

const number = (text) => (text === "" || text === null ? null : Number(text));

/** The request body of one field: only what its type uses; a blank default is none; renamed options are named. */
export function toWrite(state) {
  const select = isSelect(state.type);
  const out = { name: state.name.trim(), label: state.label.trim(), kind: select ? "choice" : state.type, default: null, options: [], multiple: state.type === "multi" };
  if (select) {
    out.options = state.options.map((o) => o.text.trim()).filter(Boolean);
    const renamed = Object.fromEntries(state.options.filter((o) => o.original !== null && o.original !== o.text.trim()).map((o) => [o.original, o.text.trim()]));
    if (Object.keys(renamed).length) out.renamed_options = renamed;
  }
  if (state.type === "text") out.max_length = number(state.max_length);
  if (state.type === "number") {
    out.min_value = number(state.min_value);
    out.max_value = number(state.max_value);
    out.integer_only = state.integer_only;
  }
  const dflt = state.default;
  if (state.type === "multi") {
    const kept = dflt.filter((d) => out.options.includes(d));
    out.default = kept.length ? kept : null;
  } else if (dflt !== "" && dflt !== null) {
    if (state.type === "number") out.default = Number(dflt);
    else if (state.type === "boolean") out.default = dflt === "true";
    else out.default = dflt;
  }
  return out;
}

/** Why an option's text cannot be used: empty, or the same as another option of the field (null: fine). */
export function optionProblem(state, text, self = null) {
  const value = text.trim();
  if (!value) return t("artifact_fields.model.option_needs_text");
  if (value.length > 40) return t("artifact_fields.model.option_at_most_40_characters");
  if (state.options.some((o) => o !== self && o.text.trim().toLowerCase() === value.toLowerCase())) return t("artifact_fields.model.value_already_option", { value });
  return null;
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
  if (field.multiple) return Array.isArray(raw) && raw.length ? raw : null;
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
