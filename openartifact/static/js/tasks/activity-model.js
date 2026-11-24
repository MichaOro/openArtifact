/* The pure parts of the History tab's timeline (ADR-058): what a change says, how the executions that still exist and
 * the entries of the activity are merged into one list, and the filter. No document access: tests/js/activity-model.test.mjs. */
import { t } from "../i18n.js";

/** The three views of the timeline. */
export const FILTERS = ["all", "runs", "changes"];

/** A trace is an execution that was deleted; every other entry is a change of the artifact. */
export const isTrace = (entry) => entry.kind === "run";

/** The time an entry belongs to, in milliseconds (a trace sits where its execution started). */
export const timeOf = (item) => new Date(item.at).getTime();

const quote = (text) => `“${text}”`;

/**
 * What a change says, as one sentence without the name of who did it ("moved from Backlog to MVP").
 * @param {{kind: string, data: object}} entry an activity entry that is not a trace
 */
export function sentenceOf(entry) {
  const d = entry.data ?? {};
  switch (entry.kind) {
    case "created":
      return d.lane ? t("tasks.activity.created_in_lane", { lane: d.lane }) : t("tasks.activity.created");
    case "lane":
      return t("tasks.activity.moved", { from: d.from ?? "?", to: d.to ?? "?" });
    case "title":
      return d.from ? t("tasks.activity.renamed", { from: quote(d.from), to: quote(d.to ?? "") }) : t("tasks.activity.changed_title");
    case "description":
      return t("tasks.activity.changed_description");
    case "parent":
      if (d.to && d.from) return t("tasks.activity.parent_changed", { from: d.from, to: d.to });
      return d.to ? t("tasks.activity.parent_set", { to: d.to }) : t("tasks.activity.parent_removed", { from: d.from ?? "?" });
    case "field":
      if (d.to === null || d.to === undefined || d.to === "") return t("tasks.activity.field_cleared", { label: d.label ?? d.field });
      return t("tasks.activity.field_set", { label: d.label ?? d.field, to: quote(d.to) });
    case "pipeline":
      return d.to ? t("tasks.activity.pipeline_assigned", { to: d.to }) : t("tasks.activity.pipeline_removed");
    case "stage":
      return t("tasks.activity.stage_set", { to: d.to ?? "?" });
    case "action":
      return t("tasks.activity.action_set", { to: d.to ?? "?" });
    default:
      return entry.kind;
  }
}

/** The facts of a trace in the shape the history row cells take (see history-row.js): an execution without the steps. */
export function traceAsExecution(entry) {
  const d = entry.data ?? {};
  return {
    id: entry.execution_id,
    number: d.number,
    status: d.status,
    pipeline_name: d.pipeline ?? "",
    started_at: d.started_at ?? entry.created_at,
    finished_at: d.finished_at ?? null,
    duration_seconds: d.duration_ms == null ? null : d.duration_ms / 1000,
    started_by: entry.actor_kind,
    step_count: d.steps ?? 0,
  };
}

/**
 * The timeline: executions that still exist (interactive rows) and activity entries (changes, and the traces of deleted
 * executions), newest first. A trace of an execution that is shown as a live row is left out, so a run appears once.
 * @param {object[]} executions the artifact's executions
 * @param {object[]} activity the artifact's activity entries
 * @returns {{type: "execution"|"change"|"trace", at: string, key: string, execution?: object, entry?: object}[]}
 */
export function mergeTimeline(executions, activity) {
  const live = new Set(executions.map((e) => e.id));
  const items = [
    ...executions.map((execution) => ({ type: "execution", at: execution.started_at, key: `e:${execution.id}`, execution })),
    ...activity
      .filter((entry) => !(isTrace(entry) && live.has(entry.execution_id)))
      .map((entry) => ({ type: isTrace(entry) ? "trace" : "change", at: entry.created_at, key: `a:${entry.id}`, entry })),
  ];
  return items.sort((a, b) => timeOf(b) - timeOf(a) || b.key.localeCompare(a.key));
}

/** The items a filter shows: all, only runs (live and traces), or only changes. */
export function filterTimeline(items, filter) {
  if (filter === "runs") return items.filter((item) => item.type !== "change");
  if (filter === "changes") return items.filter((item) => item.type === "change");
  return items;
}

/** The entries with this one added (by id); an entry already there is replaced. */
export function withEntry(entries, entry) {
  return [entry, ...entries.filter((e) => e.id !== entry.id)];
}
