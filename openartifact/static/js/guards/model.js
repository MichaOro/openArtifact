/* The pure part of the guard library (ADR-060): what a guard says in one line, how often it is used, what the shield of a
 * scope says and which guards the "Add a guard" popup offers. No DOM, no requests: tests/js/guards-model.test.mjs. */
import * as rules from "../components/rule-model.js";
import { t, tn } from "../i18n.js";

export const SCOPES = ["pipeline", "stage", "action", "definition", "node"];
export const EVENTS = ["enter", "pass", "error", "leave", "fail"];

/** A scope that is the graph itself (a pipeline, or an action definition as a whole): it has no node id of its own. */
export const isGraphScope = (type) => type === "pipeline" || type === "definition";

const keyOf = (fieldKey) => fieldKey.replace(/\.$/, "").replace(/\./g, "_");

/** The server's guard schema (`GET /api/rules/schemas/guard`) as the rule builder takes it, with its labels from the
 * dictionary. */
export function builderSchema(schema) {
  return {
    actions: schema.consequences.map((c) => ({ key: c.key, label: t(`guards.consequence.${c.key}`), phrase: "", effect: "" })),
    fields: schema.fields.map((f) => ({
      key: f.key,
      prefix: f.prefix ?? undefined,
      kind: f.kind,
      label: t(`guards.field.${keyOf(f.key)}`),
      minimum: f.minimum,
      units: f.units,
      default: f.kind === "duration" ? 600 : f.kind === "count" ? 5 : 0,
      options: f.options.map((o) => ({ value: o, label: t(`guards.last_status.${o}`) })),
      operators: f.operators.map((o) => ({ key: o, label: t(`guards.operator.${o}`) })),
    })),
  };
}

/** Seconds in words with the largest whole unit ("15 minutes", "90 seconds"). */
export function seconds(value) {
  const { amount, unit } = rules.splitDuration(value, ["days", "hours", "minutes", "seconds"]);
  return tn(`components.rule_model.duration.${unit}`, amount);
}

/** What fires a guard, short: "On entered" / "Every 1 minute, held 5 minutes". */
export function triggerText(trigger) {
  if (!trigger || trigger.type !== "interval") {
    const events = (trigger?.events ?? []).map((e) => t(`guards.event_short.${e}`)).join(", ");
    return t("guards.summary.on_events", { events: events || "–" });
  }
  const parts = [t("guards.summary.every", { every: seconds(trigger.every_seconds ?? 0) })];
  if (trigger.for_seconds) parts.push(t("guards.summary.held", { held: seconds(trigger.for_seconds) }));
  return parts.join(", ");
}

/** The one line a guard is described by in the library and the popups: its trigger and its condition. */
export function summaryLine(guard, schema) {
  const condition = schema && guard.when ? rules.describe(guard.when, schema) : "";
  return `${triggerText(guard.trigger)} · ${condition || t("guards.summary.no_condition")}`;
}

/** "Used in 2 places" / "Not used yet". */
export function usedText(count) {
  return count ? tn("guards.used_in", count) : t("guards.unused");
}

/** The tooltip and accessible name of a scope's shield: "1 guard configured" (guards act only while a run goes, so it
 * never says "active"). */
export function shieldText(count) {
  return tn("guards.shield_tooltip", count);
}

/** Why a definition cannot be deleted, or "" when it can. */
export function deleteBlocked(guard) {
  return guard.used_by ? tn("guards.delete_blocked", guard.used_by) : "";
}

/** The attachments of one scope, with their definition: `{attachment, guard}`, by the guard's name. */
export function attachedTo(guards, type, id) {
  const found = [];
  for (const guard of guards) {
    for (const attachment of guard.attachments ?? []) {
      if (attachment.scope_type === type && attachment.scope_id === id) found.push({ attachment, guard });
    }
  }
  return found.sort((a, b) => a.guard.name.localeCompare(b.guard.name) || a.attachment.id.localeCompare(b.attachment.id));
}

/** How many attachments the scopes of one graph (a pipeline or an action definition) have, by `type|id`. */
export function countsByScope(guards, graphId) {
  const counts = new Map();
  for (const guard of guards) {
    for (const a of guard.attachments ?? []) {
      if ((a.graph_id ?? a.pipeline_id) !== graphId) continue;
      const key = `${a.scope_type}|${a.scope_id}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return counts;
}

/** The guards that sit INSIDE an action definition (on the whole action or on one of its nodes), `{attachment, guard}`,
 * by the guard's name: what the pipeline's action card shows under "In the action". */
export function innerOf(guards, definitionId) {
  const found = [];
  if (!definitionId) return found;
  for (const guard of guards) {
    for (const attachment of guard.attachments ?? []) {
      if ((attachment.graph_id ?? attachment.pipeline_id) === definitionId) found.push({ attachment, guard });
    }
  }
  return found.sort((a, b) => a.guard.name.localeCompare(b.guard.name) || a.attachment.id.localeCompare(b.attachment.id));
}

/** What an inner guard watches, in words: "the whole action" or "node Summarise". */
export function innerScopeText(attachment) {
  return attachment.scope_type === "node" ? t("guards.inner_node", { name: attachment.scope_name || "?" }) : t("guards.inner_whole");
}

/** How many guards a card's shield counts: its own attachments and, for an action, the ones inside its definition. */
export function shieldCount(own, inner) {
  return own + inner;
}

/** The guards the "Add a guard" popup offers for a scope: allowed on that kind of scope, not attached to it yet and
 * matching the search (name or description, any case), by name. */
export function attachable(guards, type, id, query = "") {
  const wanted = query.trim().toLowerCase();
  return guards
    .filter((g) => (g.scope_types ?? SCOPES).includes(type))
    .filter((g) => !(g.attachments ?? []).some((a) => a.scope_type === type && a.scope_id === id))
    .filter((g) => !wanted || g.name.toLowerCase().includes(wanted) || (g.description ?? "").toLowerCase().includes(wanted))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** The library page's search: name, description or the summary line. */
export function matches(guard, query, schema) {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return true;
  return [guard.name, guard.description ?? "", summaryLine(guard, schema)].some((text) => text.toLowerCase().includes(wanted));
}

/** A blank definition as the editor starts it. */
export function blank(name) {
  return {
    name,
    description: "",
    scope_types: [...SCOPES],
    trigger: { type: "event", events: ["enter"] },
    when: rules.emptyGroup(),
    consequence: "pause",
    fallback: "pause",
    escalation: [],
    action_id: null,
  };
}

/** What the server takes from the editor: the trigger without the fields of the other kind. */
export function body(state) {
  const trigger =
    state.trigger.type === "event"
      ? { type: "event", events: state.trigger.events }
      : { type: "interval", every_seconds: state.trigger.every_seconds, for_seconds: state.trigger.for_seconds ?? 0, cooldown_seconds: state.trigger.cooldown_seconds ?? 0 };
  return {
    name: state.name.trim(),
    scope_types: SCOPES.filter((s) => state.scope_types.includes(s)),
    trigger,
    when: state.when,
    consequence: state.consequence,
    fallback: state.fallback ?? "pause",
    escalation: state.escalation,
    action_id: state.action_id ?? null,
  };
}

/** Why the editor cannot save yet, or "". */
export function problem(state, schema) {
  if (!state.name.trim()) return t("guards.name_needed");
  if (!state.scope_types.length) return t("guards.scopes_needed");
  if (!rules.isComplete(state.when, schema)) return t("guards.condition_incomplete");
  if (state.trigger.type === "event" && !state.trigger.events.length) return t("guards.event_needed");
  return "";
}
