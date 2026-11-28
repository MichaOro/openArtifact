/* The pure part of the form renderer (components/form-view.js): which fields of a form manifest (ADR-062) are there for
 * a set of values, which of them sit in which column of a wide window, which are folded away as advanced, and which
 * values break a limit. No DOM: tests/js/form-plan.test.mjs. */

/** The value at a dotted path ("trigger.type") of a nested object, or undefined. */
export function getPath(values, path) {
  let at = values;
  for (const key of path.split(".")) {
    if (at === null || at === undefined) return undefined;
    at = at[key];
  }
  return at;
}

/** Put a value at a dotted path, making the objects on the way. */
export function setPath(values, path, value) {
  const keys = path.split(".");
  let at = values;
  for (const key of keys.slice(0, -1)) {
    if (at[key] === null || typeof at[key] !== "object") at[key] = {};
    at = at[key];
  }
  at[keys.at(-1)] = value;
}

/** Whether a field is there: it has no `visible_when`, or the other field has the value (`equals`) or one of them (`in`). */
export function isVisible(field, values) {
  const when = field.visible_when;
  if (!when) return true;
  const actual = getPath(values, when.field);
  if (when.in) return when.in.includes(actual);
  return actual === when.equals;
}

/** Whether a field can be changed: it has no `enabled_when`, or the other field has the value (`equals`) or one of them (`in`). A field that
 * cannot is drawn greyed, with its `disabled_help` as the reason. */
export function isEnabled(field, values) {
  const when = field.enabled_when;
  if (!when) return true;
  const actual = getPath(values, when.field);
  if (when.in) return when.in.includes(actual);
  return actual === when.equals;
}

/** Nothing entered: undefined, null, an empty text or an empty list. */
export function isEmpty(value) {
  return value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0);
}

/**
 * Lay a form out. Per section: the fields that are there (`shown` are always drawn, `advanced` only when the section is
 * `expanded`); a section without a visible field is dropped. The sections go in manifest order into blocks: a section
 * with `column: full` is a block of its own across the whole width (a rule builder wants room); the others between two
 * of them form one block with `columns` columns (2 on a wide window): a section with `column` 1 or 2 sits there and one
 * with `auto` goes to the column that has less weight so far (its `weight`, else its visible fields).
 * @returns {{blocks: ({full: object}|{columns: object[][]})[]}} a plan is `{key, title, column, weight, shown, advanced,
 *   folded}`
 */
export function planForm(manifest, values, { columns = manifest.columns ?? 2, expanded = new Set() } = {}) {
  const blocks = [];
  let lanes = null;
  let load = null;
  const flush = () => {
    if (lanes) blocks.push({ columns: lanes });
    lanes = null;
  };
  for (const section of manifest.sections) {
    const visible = section.fields.filter((field) => isVisible(field, values));
    if (!visible.length) continue;
    const advanced = visible.filter((field) => field.advanced);
    const plan = {
      key: section.key,
      title: section.title,
      column: section.column ?? "auto",
      weight: section.weight ?? visible.length,
      shown: visible.filter((field) => !field.advanced),
      advanced,
      folded: advanced.length > 0 && !expanded.has(section.key),
    };
    if (plan.column === "full") {
      flush();
      blocks.push({ full: plan });
      continue;
    }
    if (!lanes) {
      lanes = Array.from({ length: columns }, () => []);
      load = new Array(columns).fill(0);
    }
    let at = 0;
    if (columns > 1) at = plan.column === 1 || plan.column === 2 ? Math.min(plan.column, columns) - 1 : load.indexOf(Math.min(...load));
    lanes[at].push(plan);
    load[at] += plan.weight;
  }
  flush();
  return { blocks };
}

/** The sections of a column and the fields of a plan in the order they are drawn, shown first then the advanced ones. */
export function drawn(plan) {
  return plan.folded ? plan.shown : [...plan.shown, ...plan.advanced];
}

/**
 * What breaks a field's limits, for the fields that are there: `{key: {code: "required"|"min"|"max", limit?}}`.
 * A field that is not there is not checked.
 */
export function problems(manifest, values) {
  const found = {};
  for (const section of manifest.sections) {
    for (const field of section.fields) {
      if (!isVisible(field, values)) continue;
      const value = getPath(values, field.key);
      if (field.required && isEmpty(value)) {
        found[field.key] = { code: "required" };
      } else if (typeof value === "number" && field.min !== undefined && field.min !== null && value < field.min) {
        found[field.key] = { code: "min", limit: field.min };
      } else if (typeof value === "number" && field.max !== undefined && field.max !== null && value > field.max) {
        found[field.key] = { code: "max", limit: field.max };
      }
    }
  }
  return found;
}

/** The keys whose change can change what is drawn: what a `visible_when` looks at and what a field names in
 * `config.depends_on`. A change of one of them draws the form again. */
export function dependencies(manifest) {
  const keys = new Set();
  for (const section of manifest.sections) {
    for (const field of section.fields) {
      if (field.visible_when) keys.add(field.visible_when.field);
      if (field.enabled_when) keys.add(field.enabled_when.field);
      for (const key of field.config?.depends_on ?? []) keys.add(key);
    }
  }
  return keys;
}
