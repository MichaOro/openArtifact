/* Pure logic of the artifact types page (no DOM): names, blank fields, what is sent, server messages. */

export const KINDS = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes / no" },
  { value: "choice", label: "Choice" },
];

/** A parameter name from its label: lowercase letters, digits and underscores, starting with a letter, at most 32. */
export function nameFromLabel(label) {
  const folded = label
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const named = /^[a-z]/.test(folded) ? folded : folded ? `p_${folded}` : "";
  return named.slice(0, 32).replace(/_+$/, "");
}

/** An empty parameter of a kind, as the editor holds it (every value a string or boolean, as the controls give them). */
export function blankField(kind = "text") {
  return { name: "", label: "", kind, required: false, default: "", options: "", max_length: "", min_value: "", max_value: "", integer_only: false, nameEdited: false };
}

/** A stored parameter as the editor holds it. */
export function editable(field) {
  const text = (value) => (value === null || value === undefined ? "" : String(value));
  return {
    name: field.name,
    label: field.label,
    kind: field.kind,
    required: field.required,
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
  const out = { name: field.name.trim(), label: field.label.trim(), kind: field.kind, required: field.required, default: null, options: [] };
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
 * The server's refusal of a type: lines `Field NAME: message`, `Name: message`, or something else.
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

/** "3 parameters · 2 artifacts" */
export function summary(type) {
  const n = type.fields.length;
  const used = type.artifact_count;
  return `${n} parameter${n === 1 ? "" : "s"} · ${used} artifact${used === 1 ? "" : "s"}`;
}
