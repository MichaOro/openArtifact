/* The data of a rule builder, without a DOM: a rule is a tree of groups (`all` / `any`) holding conditions and inner
 * groups, exactly the shape the server takes (engine/retention.py). A schema says which fields exist, what each is
 * called, how its value is entered (`choice`: several of some options; `text`; `duration`: seconds; `count`: a whole number) and which
 * operators fit. Every edit returns a new tree, so the builder can compare and the original is never changed. */

const UNITS = [
  ["days", 86400],
  ["hours", 3600],
  ["minutes", 60],
];
const DEFAULT_DURATION = 86400;

export const emptyGroup = (mode = "all") => ({ type: "group", mode, items: [] });

const emptyValue = (field) => (field.kind === "choice" ? [] : field.kind === "duration" ? DEFAULT_DURATION : field.kind === "count" ? (field.default ?? 1) : "");

/** A fresh condition for `key` (the first field of the schema when none is given). */
export function newCondition(schema, key = schema.fields[0].key) {
  const field = schema.fields.find((f) => f.key === key) ?? schema.fields[0];
  return { type: "condition", field: field.key, op: field.operators[0].key, value: emptyValue(field) };
}

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

/** Every condition has what the server needs; an empty rule is complete (it deletes nothing). */
export function isComplete(group) {
  return group.items.every((item) => {
    if (item.type === "group") return isComplete(item);
    if (Array.isArray(item.value)) return item.value.length > 0;
    if (typeof item.value === "string") return item.value.trim() !== "";
    return Number.isInteger(item.value) && item.value > 0;
  });
}

/** Seconds as the largest whole unit: 7 days, 90 minutes. */
export function splitDuration(seconds) {
  for (const [unit, size] of UNITS) if (seconds >= size && seconds % size === 0) return { amount: seconds / size, unit };
  return { amount: Math.max(1, Math.round(seconds / 60)), unit: "minutes" };
}

export const joinDuration = (amount, unit) => Math.round(amount) * (UNITS.find(([name]) => name === unit)?.[1] ?? 60);

export const durationUnits = () => UNITS.map(([name]) => name);

function words(condition, schema) {
  const field = schema.fields.find((f) => f.key === condition.field);
  const op = field?.operators.find((o) => o.key === condition.op)?.label ?? condition.op;
  let value;
  if (field?.kind === "choice") {
    value = condition.value.map((v) => field.options.find((o) => o.value === v)?.label ?? v).join(" or ");
  } else if (field?.kind === "count") {
    value = String(condition.value);
  } else if (field?.kind === "duration") {
    const { amount, unit } = splitDuration(condition.value);
    value = `${amount} ${amount === 1 ? unit.slice(0, -1) : unit}`;
  } else {
    value = `"${condition.value}"`;
  }
  return `${field?.label ?? condition.field} ${op} ${value}`;
}

/** A rule in words ("Status is Done or Failed, and Age is older than 7 days"); "" for an empty one. */
export function describe(group, schema, nested = false) {
  const parts = group.items.map((item) => (item.type === "group" ? describe(item, schema, true) : words(item, schema))).filter(Boolean);
  const glue = group.mode === "all" ? "and" : "or";
  const text = parts.join(nested ? ` ${glue} ` : `, ${glue} `);
  return nested && parts.length > 1 ? `(${text})` : text;
}

/** A new rule: no conditions yet, the first action of the schema. */
export const emptyRule = (schema) => ({ when: emptyGroup(), action: schema.actions[0].key });

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
