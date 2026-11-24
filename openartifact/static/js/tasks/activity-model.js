/* The pure parts of the History tab's timeline (ADR-058): what an entry says, who is named, how the executions that
 * still exist and the entries of the activity are merged into one list, the filter, the GitHub-style collapse and the
 * marker of each entry. No document access: tests/js/activity-model.test.mjs. */
import { plural, t } from "../i18n.js";

/** The views of the timeline. */
export const FILTERS = ["all", "comments", "runs", "changes"];

/** How many entries (and comments) are shown before "Show N older" (ADR-058). */
export const COLLAPSED = 10;

/** The longest preview of a comment in the timeline, in characters. */
export const PREVIEW = 80;

const quote = (text) => `“${text}”`;

/** The type of an activity entry: a delete action on executions, a comment (or its deletion), or a change. */
export function typeOfEntry(entry) {
  if (entry.kind === "run") return "trace";
  if (entry.kind === "comment" || entry.kind === "comment_deleted") return "comment";
  return "change";
}

/** The filter an item belongs to: executions (live and deleted, and what guards did to them), changes, or comments. */
export const groupOf = (item) => (item.entry?.kind === "guard" ? "runs" : { execution: "runs", trace: "runs", comment: "comments", change: "changes" }[item.type]);

/** A duration in seconds as the facts of a guard say it: "45 s", "14 min". */
function span(seconds) {
  return seconds >= 120 ? t("tasks.activity.minutes", { n: Math.round(seconds / 60) }) : t("tasks.activity.seconds", { n: Math.round(seconds) });
}

/** The facts a guard fired on, in a few words ("round 10, 14 min without progress", ADR-060). */
export function factsOf(facts = {}) {
  const parts = [t("tasks.activity.round", { n: facts.runs ?? 0 })];
  if (facts.idle >= 1) parts.push(t("tasks.activity.without_progress", { time: span(facts.idle) }));
  if (facts.elapsed >= 1) parts.push(t("tasks.activity.in_the_scope", { time: span(facts.elapsed) }));
  if (facts.errors) parts.push(plural("tasks.activity.errors", facts.errors));
  return parts.join(", ");
}

/** What a guard did: its consequence, or that it failed (and the flow went on), reached its cap or cannot act yet. */
function guardSentence(d) {
  const facts = factsOf(d.facts);
  if (d.outcome === "failed") return t("tasks.activity.guard_failed", { scope: scopeOf(d), reason: d.detail ?? "" });
  if (d.outcome === "capped") return t("tasks.activity.guard_capped", { scope: scopeOf(d) });
  if (d.outcome === "unavailable") return t("tasks.activity.guard_unavailable", { scope: scopeOf(d) });
  return t("tasks.activity.guard_fired", { outcome: t(`tasks.activity.guard_outcome.${d.outcome}`), scope: scopeOf(d), facts });
}

/** The time an entry belongs to, in milliseconds. */
export const timeOf = (item) => new Date(item.at).getTime();

/** Who an entry names: the operator's own actors and the unknown deleter of an old trace in words. */
export function actorName(entry) {
  if (entry.actor_kind !== "system") return entry.actor_name;
  return { unknown: t("tasks.activity.someone"), "retention rule": t("tasks.activity.retention_rule"), "operator guard": t("tasks.activity.operator_guard") }[entry.actor_name] ?? entry.actor_name;
}

/**
 * What a change says, as one sentence without the name of who did it ("moved from Backlog to MVP").
 * @param {{kind: string, data: object}} entry an activity entry that is a change
 */
/** What a guard firing names: the scope's name, and for a node of an action "node X of action Y" in the reader's language. */
export function scopeOf(d) {
  if (d.scope_type === "node") return t("tasks.activity.scope_node", { name: d.scope_name ?? "?", parent: d.scope_parent ?? "?" });
  return d.scope_name ?? "?";
}

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
    case "guard":
      return guardSentence(d);
    default:
      return entry.kind;
  }
}

/** Numbers as ranges: [3, 4, 5, 9] -> "#3–#5, #9"; `count` larger than the numbers given adds "…". */
export function rangesText(numbers, count = numbers.length) {
  const sorted = [...numbers].sort((a, b) => a - b);
  const parts = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    parts.push(j === i ? `#${sorted[i]}` : j === i + 1 ? `#${sorted[i]}, #${sorted[j]}` : `#${sorted[i]}–#${sorted[j]}`);
    i = j + 1;
  }
  if (count > sorted.length) parts.push("…");
  return parts.join(", ");
}

/**
 * What a delete action on executions says, and when the single execution ran.
 * @param {{data: object}} entry a ``run`` entry
 * @returns {{sentence: string, ran: string | null}}
 */
export function traceOf(entry) {
  const d = entry.data ?? {};
  if (Array.isArray(d.numbers)) {
    return { sentence: plural("tasks.activity.deleted_executions", d.count ?? d.numbers.length, { numbers: rangesText(d.numbers, d.count ?? d.numbers.length) }), ran: null };
  }
  return { sentence: t("tasks.activity.deleted_execution", { number: d.number ?? "?" }), ran: d.started_at ?? null };
}

/** The first line of a comment for the timeline: white space folded, cut at `PREVIEW` characters. */
export function previewOf(body, max = PREVIEW) {
  const text = String(body ?? "").replace(/\s+/g, " ").trim();
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

/**
 * The timeline: executions that still exist (interactive rows) and activity entries, newest first. A trace of an
 * execution that is shown as a live row is left out, so one never appears twice.
 * @returns {{type: "execution"|"change"|"trace"|"comment", at: string, key: string, execution?: object, entry?: object}[]}
 */
export function mergeTimeline(executions, activity) {
  const live = new Set(executions.map((e) => e.id));
  const items = [
    ...executions.map((execution) => ({ type: "execution", at: execution.started_at, key: `e:${execution.id}`, execution })),
    ...activity
      .filter((entry) => !(entry.kind === "run" && live.has(entry.execution_id)))
      .map((entry) => ({ type: typeOfEntry(entry), at: entry.created_at, key: `a:${entry.id}`, entry })),
  ];
  return items.sort((a, b) => timeOf(b) - timeOf(a) || b.key.localeCompare(a.key));
}

/** The items a filter shows. */
export function filterTimeline(items, filter) {
  return filter === "all" ? items : items.filter((item) => groupOf(item) === filter);
}

/**
 * The window GitHub-style: the newest `limit` items and, always, the "created" entry at the bottom; the rest is hidden
 * behind "Show N older". `expanded` shows everything.
 * @returns {{shown: object[], hidden: number}}
 */
export function collapse(items, expanded, limit = COLLAPSED) {
  if (expanded || items.length <= limit) return { shown: items, hidden: 0 };
  const head = items.slice(0, limit);
  const anchor = items.find((item) => item.entry?.kind === "created" && !head.includes(item));
  const shown = anchor ? [...head, anchor] : head;
  return { shown, hidden: items.length - shown.length };
}

/**
 * The comments to show: the newest `limit`, oldest first as in the list; `keepId` (a comment being edited or jumped
 * to) is never hidden - then everything is shown.
 * @returns {{shown: object[], hidden: number}}
 */
export function collapseComments(comments, expanded, limit = COLLAPSED, keepId = null) {
  if (expanded || comments.length <= limit) return { shown: comments, hidden: 0 };
  const index = keepId === null ? -1 : comments.findIndex((c) => c.id === keepId);
  if (index !== -1 && index < comments.length - limit) return { shown: comments, hidden: 0 };
  return { shown: comments.slice(-limit), hidden: comments.length - limit };
}

/** Whether a comment is hidden in the collapsed list (so a jump to it must expand the list first). */
export function isHiddenComment(comments, id, limit = COLLAPSED) {
  const index = comments.findIndex((c) => c.id === id);
  return index !== -1 && index < comments.length - limit;
}

/** The entries with this one added (by id); an entry already there is replaced. */
export function withEntry(entries, entry) {
  return [entry, ...entries.filter((e) => e.id !== entry.id)];
}

/** The entries of the activity without the one that stands for this comment (it was deleted). */
export function withoutComment(entries, commentId) {
  return entries.filter((e) => !(e.kind === "comment" && e.data?.comment_id === commentId));
}

const STATUS_MARKERS = {
  done: { icon: "check", tone: "ok" },
  pass: { icon: "check", tone: "ok" },
  failed: { icon: "x", tone: "bad" },
  fail: { icon: "x", tone: "bad" },
  running: { icon: "play", tone: "accent" },
};
const KIND_MARKERS = {
  created: { icon: "plug", tone: "ok" },
  lane: { icon: "columns", tone: "accent" },
  parent: { icon: "parent", tone: "accent" },
  title: { icon: "pencil", tone: "muted" },
  description: { icon: "pencil", tone: "muted" },
  field: { icon: "tag", tone: "muted" },
  pipeline: { icon: "pipeline", tone: "accent" },
  stage: { icon: "layers", tone: "accent" },
  action: { icon: "action", tone: "accent" },
};

const GUARD_TONES = { pause: "accent", abort: "bad", failed: "bad", capped: "muted", unavailable: "muted" };

/** The round marker of an item: the icon and the tone say what kind of event it is. */
export function markerOf(item) {
  if (item.entry?.kind === "guard") return { icon: "shield", tone: GUARD_TONES[item.entry.data?.outcome] ?? "ok" };
  if (item.type === "execution") return STATUS_MARKERS[item.execution.status] ?? { icon: "clock", tone: "muted" };
  if (item.type === "trace") return { icon: "trash", tone: "bad" };
  if (item.type === "comment") return item.entry.kind === "comment_deleted" ? { icon: "trash", tone: "bad" } : { icon: "message", tone: "accent" };
  return KIND_MARKERS[item.entry.kind] ?? { icon: "settings", tone: "muted" };
}
