/* The data of a rule builder, without a DOM: a rule is a tree of groups (`all` / `any`) holding conditions and inner
 * groups, exactly the shape the server takes (engine/retention.py). A schema says which fields exist, what each is
 * called, how its value is entered (`choice`: several of some options; `text`; `duration`: seconds, in the field's
 * `units`; `count`: a whole number; `number`: any number) and which operators fit. A field with a `prefix` stands for
 * many (`var.` + a name: a result field); its conditions name it as `prefix + name`. The schemas are the server's
 * (GET /api/rules/schemas, rules/catalog.py). Every edit returns a new tree, so the builder can compare and the original is never changed. */

import { t, tn } from "../i18n.js";

const UNITS = [
  ["days", 86400],
  ["hours", 3600],
  ["minutes", 60],
  ["seconds", 1],
];
const DEFAULT_UNITS = ["days", "hours", "minutes"];
const DEFAULT_DURATION = 86400;

export const emptyGroup = (mode = "all") => ({ type: "group", mode, items: [] });

const emptyValue = (field) =>
  field.kind === "choice" ? [] : field.kind === "duration" ? (field.default ?? DEFAULT_DURATION) : field.kind === "count" ? (field.default ?? 1) : field.kind === "number" ? (field.default ?? 0) : "";

/** The field of the schema a condition's `key` names (`var.gain` names the field with the prefix `var.`). */
export function fieldOf(schema, key) {
  return schema.fields.find((f) => f.key === key) ?? schema.fields.find((f) => f.prefix && key?.startsWith(f.prefix));
}

/** The name after a field's prefix (`gain` of `var.gain`); "" for a field without one. */
export const nameOf = (field, key) => (field?.prefix && key.startsWith(field.prefix) ? key.slice(field.prefix.length) : "");

/** A fresh condition for `key` (the first field of the schema when none is given). */
export function newCondition(schema, key = schema.fields[0].key) {
  const field = fieldOf(schema, key) ?? schema.fields[0];
  return { type: "condition", field: field.prefix ?? field.key, op: field.operators[0].key, value: emptyValue(field) };
}

/** The same condition naming another result field (`prefix + name`). */
export const withName = (field, condition, name) => ({ ...condition, field: field.prefix + name });

/** The same condition on another field: operator and value start over (they belong to the field). */
export const withField = (schema, condition, key) => newCondition(schema, key);

export const withOperator = (condition, op) => ({ ...condition, op });

export const withValue = (condition, value) => ({ ...condition, value });

const at = (group, path) => path.reduce((node, index) => node.items[index], group);

/** `tree` with `change(group)` applied to the group at `path` (a list of item indexes from the root). */
function editGroup(tree, path, change) {
  if (!path.length) return change(tree);
  const [head, ...rest] = path;
  return { ...tree, items: tree.items.map((item, i) => (i === head ? editGroup(item, rest, change) : item)) };
}

export const addItem = (tree, path, item) => editGroup(tree, path, (group) => ({ ...group, items: [...group.items, item] }));

export const setMode = (tree, path, mode) => editGroup(tree, path, (group) => ({ ...group, mode }));

/** Remove the item at `path` (the last index is the item, the rest leads to its group). */
export const removeItem = (tree, path) => editGroup(tree, path.slice(0, -1), (group) => ({ ...group, items: group.items.filter((_, i) => i !== path.at(-1)) }));

/** Replace the item at `path`. */
export const replaceItem = (tree, path, item) => editGroup(tree, path.slice(0, -1), (group) => ({ ...group, items: group.items.map((old, i) => (i === path.at(-1) ? item : old)) }));

export const itemAt = (tree, path) => at(tree, path);

export function countConditions(group) {
  return group.items.reduce((sum, item) => sum + (item.type === "group" ? countConditions(item) : 1), 0);
}

/** How many levels of groups the tree has (a root without inner groups is 1). */
export function depthOf(group) {
  return 1 + Math.max(0, ...group.items.filter((i) => i.type === "group").map(depthOf));
}

/** Whether the group at `path` may hold another group without exceeding `maxDepth` levels. */
export function canNest(tree, path, maxDepth) {
  return path.length + 1 < maxDepth;
}

const NAME = /^[a-z][a-z0-9_]{0,63}$/;

/** Every condition has what the server needs; an empty rule is complete (it deletes nothing). With a schema, a
 * number may be any number, a count or a duration down to the field's minimum, and a result field needs a name. */
export function isComplete(group, schema = null) {
  return group.items.every((item) => {
    if (item.type === "group") return isComplete(item, schema);
    const field = schema ? fieldOf(schema, item.field) : null;
    if (field?.prefix && !NAME.test(nameOf(field, item.field))) return false;
    if (field?.kind === "number") return typeof item.value === "number" && Number.isFinite(item.value);
    if (field && (field.kind === "count" || field.kind === "duration")) return Number.isInteger(item.value) && item.value >= (field.minimum ?? 1);
    if (Array.isArray(item.value)) return item.value.length > 0;
    if (typeof item.value === "string") return item.value.trim() !== "";
    return Number.isInteger(item.value) && item.value > 0;
  });
}

/** Seconds as the largest whole unit of `units`: 7 days, 90 minutes (with seconds offered: 90 seconds). */
export function splitDuration(seconds, units = DEFAULT_UNITS) {
  for (const [unit, size] of UNITS) if (units.includes(unit) && seconds >= size && seconds % size === 0) return { amount: seconds / size, unit };
  if (units.includes("seconds")) return { amount: seconds, unit: "seconds" };
  return { amount: Math.max(1, Math.round(seconds / 60)), unit: "minutes" };
}

export const joinDuration = (amount, unit) => Math.round(amount) * (UNITS.find(([name]) => name === unit)?.[1] ?? 60);

/** The units a duration field offers (days, hours, minutes unless the field says otherwise). */
export const durationUnits = (field = null) => (field?.units?.length ? field.units : DEFAULT_UNITS);

function words(condition, schema) {
  const field = fieldOf(schema, condition.field);
  const op = field?.operators.find((o) => o.key === condition.op)?.label ?? condition.op;
  let value;
  if (field?.kind === "choice") {
    value = condition.value.map((v) => field.options.find((o) => o.value === v)?.label ?? v).join(` ${t("components.rule_model.or")} `);
  } else if (field?.kind === "count" || field?.kind === "number") {
    value = String(condition.value);
  } else if (field?.kind === "duration") {
    const { amount, unit } = splitDuration(condition.value, durationUnits(field));
    value = tn(`components.rule_model.duration.${unit}`, amount);
  } else {
    value = `"${condition.value}"`;
  }
  const label = field?.prefix ? `${field.label} ${nameOf(field, condition.field)}` : field?.label;
  return `${label ?? condition.field} ${op} ${value}`;
}

/** A rule in words ("Status is Done or Failed, and Age is older than 7 days"); "" for an empty one. */
export function describe(group, schema, nested = false) {
  const parts = group.items.map((item) => (item.type === "group" ? describe(item, schema, true) : words(item, schema))).filter(Boolean);
  const glue = group.mode === "all" ? t("components.rule_model.and") : t("components.rule_model.or");
  const text = parts.join(nested ? ` ${glue} ` : `, ${glue} `);
  return nested && parts.length > 1 ? `(${text})` : text;
}

/** A new rule: no conditions yet, the first action of the schema. */
export const emptyRule = (schema) => ({ when: emptyGroup(), action: schema.actions[0].key, ...(schema.actions[0].defaults ? { params: { ...schema.actions[0].defaults } } : {}) });

/** A rule in a sentence: its action's phrase and its conditions ("Delete finished executions where Status is Failed."). */
export function describeRule(rule, schema) {
  const conditions = describe(rule.when, schema);
  if (!conditions) return "";
  const action = schema.actions.find((a) => a.key === rule.action) ?? schema.actions[0];
  return `${action.phrase} ${conditions}.`;
}

/** What saving does to the executions the rules match now ("deletes", "deletes or archives"); "" when nothing matches. */
export function effectOf(schema, rules, perRule) {
  const used = new Set(rules.filter((_, i) => perRule[i] > 0).map((r) => r.action));
  return schema.actions.filter((a) => used.has(a.key)).map((a) => a.effect).join(" or ");
}
