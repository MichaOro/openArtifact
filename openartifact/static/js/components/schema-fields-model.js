/* The list of fields of a schema (ADR-080) as pure functions: nothing here touches the document, so the rules of the list (what a new field
 * starts with, which names are free, what a typed value must be) are tested on their own. A field is `{name, type, required, description,
 * choices?}`; the same rules are the server's (graph/field_schema.py), this only tells the user before a request. The functions return a
 * new list and never change the one they were given. */

export const NAME_PATTERN = /^[a-z][a-z0-9_]{0,31}$/;

/** The types and bounds when the server has not said (it does: `Setting.describe`, `field_types`, `field_limits`). */
export const TYPES = ["text", "number", "boolean", "choice", "list"];
export const LIMITS = { name_chars: 32, description_chars: 300, choices: [2, 20], choice_chars: 60 };
export const MAX_FIELDS = 30;

/** A name no field of the list has: `field`, `field_2`, `field_3` ... */
export function freeName(list, base = "field") {
  const used = new Set(list.map((field) => field.name));
  if (!used.has(base)) return base;
  let n = 2;
  while (used.has(`${base}_${n}`)) n += 1;
  return `${base}_${n}`;
}

/** What a field starts with when it is added. */
export function startField(list) {
  return { name: freeName(list), type: "text", required: false, description: "" };
}

export function addField(list) {
  return [...list, startField(list)];
}

export function removeField(list, index) {
  return list.filter((_, i) => i !== index);
}

/** The field at `from` moved to place `to` (the others keep their order). */
export function moveField(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** One property of one field changed; a field that is no choice has no values, a choice starts with none. */
export function setProp(list, index, key, value) {
  return list.map((field, i) => {
    if (i !== index) return field;
    const next = { ...field, [key]: value };
    if (key === "type") {
      if (value === "choice") next.choices = field.choices ?? [];
      else delete next.choices;
    }
    return next;
  });
}

/** The values of a choice as typed: one per line or separated by commas; spaces around a value and empty values are dropped. */
export function parseChoices(text) {
  return text
    .split(/[\n,]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** What is wrong with the field at `index` as `{code, params}` (the component makes the text of it), or null. */
export function fieldProblem(list, index, limits = LIMITS) {
  const field = list[index];
  const place = index + 1;
  if (!NAME_PATTERN.test(field.name)) return { code: "name_format", params: { n: place } };
  if (list.findIndex((other) => other.name === field.name) !== index) return { code: "name_twice", params: { name: field.name } };
  if ((field.description ?? "").length > limits.description_chars) return { code: "description_long", params: { name: field.name, max: limits.description_chars } };
  if (field.type === "choice") {
    const values = field.choices ?? [];
    const [low, high] = limits.choices;
    if (values.length < low || values.length > high) return { code: "choice_count", params: { name: field.name, min: low, max: high } };
    if (values.some((value) => value.length > limits.choice_chars)) return { code: "choice_long", params: { name: field.name, max: limits.choice_chars } };
    if (new Set(values).size !== values.length) return { code: "choice_twice", params: { name: field.name } };
  }
  return null;
}

/** The first problem of the list, or null. */
export function listProblem(list, limits = LIMITS, max = MAX_FIELDS) {
  if (list.length > max) return { code: "too_many", params: { max } };
  for (let i = 0; i < list.length; i += 1) {
    const problem = fieldProblem(list, i, limits);
    if (problem) return problem;
  }
  return null;
}
