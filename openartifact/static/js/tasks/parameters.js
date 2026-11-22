/* Pure logic of the artifact's typed parameters (no DOM): what a control shows and sends, how the server's
 * messages map to fields, and what a change of type drops. The form is tasks/parameter-form.js. */

/** Whether a stored or typed value counts as "not set". */
export const isBlank = (value) => value === null || value === undefined || (typeof value === "string" && value.trim() === "");

/**
 * What a control starts with: the stored value, else (for a new artifact or an unset value) the default.
 * A boolean is always a switch, so it starts off at the least.
 */
export function initialValue(field, stored) {
  const value = isBlank(stored) ? field.default : stored;
  if (field.kind === "boolean") return value === true;
  return isBlank(value) ? "" : value;
}

/** What a control's raw value (text of an input, checked state of a switch) means as a parameter: a value or null. */
export function parameterOf(field, raw) {
  if (field.kind === "boolean") return Boolean(raw);
  if (isBlank(raw)) return null;
  if (field.kind === "number") {
    const number = Number(raw);
    return Number.isFinite(number) ? number : String(raw); // the server names the wrong value
  }
  return String(raw);
}

/** How a stored value is shown in the read-only view. */
export function displayValue(field, value) {
  if (isBlank(value)) return "";
  if (field.kind === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * The server's refusal of parameters: one line per problem, `Parameter NAME: message`.
 * @returns {{byField: Map<string, string>, other: string[]}} messages by parameter name, and every other line
 */
export function parseProblems(detail) {
  const byField = new Map();
  const other = [];
  for (const line of String(detail ?? "").split("\n")) {
    const match = /^Parameter ([^:]{1,40}): (.+)$/.exec(line.trim());
    if (match) {
      if (!byField.has(match[1])) byField.set(match[1], match[2]);
    } else if (line.trim()) {
      other.push(line.trim());
    }
  }
  return { byField, other };
}

/**
 * What changing from `from` to `to` does to the values: those of parameters the new type does not have are dropped.
 * @param {{fields: object[]}|null} from @param {{fields: object[]}|null} to @param {Record<string, unknown>} values by name
 * @returns {string[]} the labels of the dropped values (only values that are set)
 */
export function droppedBy(from, to, values) {
  const kept = new Set((to?.fields ?? []).map((f) => f.name));
  return (from?.fields ?? []).filter((f) => !kept.has(f.name) && !isBlank(values[f.name]) && values[f.name] !== false).map((f) => f.label);
}
