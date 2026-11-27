/* The data of a list of rules, without a DOM (rule-list.js draws it): a rule is `{when, action, name, enabled}` plus,
 * while a dialog is open, `removed` (taken out of the list but still there, so Undo can reach it until it is saved).
 * Every change returns a new list, the original is never changed. The shape that is saved is `kept(rules)`. */
import { t } from "../i18n.js";
import * as model from "./rule-model.js";

/** What a dialog holds for stored rules: a rule from before names and switches reads as unnamed and on. */
export const normalize = (rules) =>
  (rules ?? []).map((r) => ({ when: r.when, action: r.action, name: r.name ?? "", enabled: r.enabled !== false, ...(r.params ? { params: r.params } : {}) }));

/** A rule is called by its name, else "Rule N" (N counted from one in the list). */
export const labelOf = (rule, index) => rule.name?.trim() || t("components.rule_set.rule", { number: index + 1 });

export const patch = (rules, index, change) => rules.map((r, i) => (i === index ? { ...r, ...change } : r));
export const setEnabled = (rules, index, enabled) => patch(rules, index, { enabled });
export const setName = (rules, index, name) => patch(rules, index, { name });

/** The list with one more rule (a new one is on and has no conditions); a full list takes no more. */
export const append = (rules, rule, max) => (rules.length >= max ? rules : [...rules, { ...rule, name: rule.name ?? "", enabled: rule.enabled !== false }]);

/** Take a rule out of the list for now: it stays, marked, until the list is saved. */
export const removeStaged = (rules, index) => patch(rules, index, { removed: true });

/** Undo `removeStaged`. */
export const restore = (rules, index) => rules.map((r, i) => {
  if (i !== index) return r;
  const { removed, ...rest } = r;
  return rest;
});

/** What is saved: the rules that are not taken out, with the name or null and the switch. */
export const kept = (rules) => rules.filter((r) => !r.removed).map((r) => ({ when: r.when, action: r.action, name: r.name?.trim() ? r.name.trim() : null, enabled: r.enabled !== false, ...(r.params ? { params: r.params } : {}) }));

/** What a row tells about its rule: the sentence, or that there are no conditions yet or that one is unfinished. */
export function summaryOf(rule, schema) {
  const text = model.describeRule(rule, schema);
  const action = schema.actions.find((a) => a.key === rule.action);
  // card rules (schema.always): no condition and not "only when" is a rule that holds for every card
  if (!text && schema.always && !rule.conditional && !action?.needsCondition) return { state: "ok", text: t("components.rule_list.always", { action: action?.label ?? rule.action }) };
  if (!text) return { state: "empty", text: t("components.rule_list.no_conditions_yet") };
  if (!model.isComplete(rule.when, schema)) return { state: "incomplete", text: t("components.rule_list.unfinished") };
  return { state: "ok", text };
}

const live = (rules) => rules.map((rule, index) => ({ rule, index })).filter(({ rule }) => !rule.removed && rule.enabled);

/** How many rules are on (not taken out). */
export const countOn = (rules) => live(rules).length;

/** The sentences of the rules that are on, in the order of the list ({label, text}); a rule without conditions says nothing. */
export const activeSentences = (rules, schema) => live(rules).map(({ rule, index }) => ({ label: labelOf(rule, index), text: model.describeRule(rule, schema) })).filter((s) => s.text);
