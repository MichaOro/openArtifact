/* The pure parts of the History timeline (static/js/tasks/activity-model.js): what a change says, the merge of live
 * executions and activity entries, and the filter. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  actorName,
  collapse,
  collapseComments,
  filterTimeline,
  isHiddenComment,
  markerOf,
  mergeTimeline,
  previewOf,
  rangesText,
  sentenceOf,
  traceOf,
  withEntry,
  withoutComment,
} from "../../openartifact/static/js/tasks/activity-model.js";

const entry = (kind, data = {}, extra = {}) => ({ id: `a-${kind}`, kind, data, actor_kind: "user", actor_name: "You", execution_id: null, created_at: "2026-11-24T08:00:00Z", ...extra });
const execution = (id, number, at) => ({ id, number, status: "done", started_at: at });

test("every kind of change says what happened, in words that name the lanes, titles and fields involved", () => {
  assert.equal(sentenceOf(entry("created", { lane: "Backlog" })), "created this artifact in Backlog");
  assert.equal(sentenceOf(entry("created")), "created this artifact");
  assert.equal(sentenceOf(entry("lane", { from: "Backlog", to: "MVP" })), "moved it from Backlog to MVP");
  assert.equal(sentenceOf(entry("title", { from: "Old", to: "New" })), "renamed it from “Old” to “New”");
  assert.equal(sentenceOf(entry("title", { to: "New" })), "changed the title");
  assert.equal(sentenceOf(entry("description")), "changed the description");
  assert.equal(sentenceOf(entry("parent", { from: null, to: "Epic" })), "set the parent to Epic");
  assert.equal(sentenceOf(entry("parent", { from: "Epic", to: null })), "removed the parent Epic");
  assert.equal(sentenceOf(entry("parent", { from: "A", to: "B" })), "changed the parent from A to B");
  assert.equal(sentenceOf(entry("field", { field: "priority", label: "Priority", to: "high" })), "set Priority to “high”");
  assert.equal(sentenceOf(entry("field", { field: "priority", label: "Priority", to: null })), "cleared Priority");
  assert.equal(sentenceOf(entry("field", { field: "priority", to: "x" })), "set priority to “x”"); // no label: the name
  assert.equal(sentenceOf(entry("pipeline", { to: "Flow" })), "assigned the pipeline Flow");
  assert.equal(sentenceOf(entry("pipeline", { to: null })), "removed the pipeline");
  assert.equal(sentenceOf(entry("stage", { to: "Review" })), "set the stage to Review");
  assert.equal(sentenceOf(entry("action", { to: "Check" })), "set the action to Check");
  assert.equal(sentenceOf(entry("something-new")), "something-new"); // an unknown kind is shown as it is, not hidden
});

test("a delete action says who deleted what: one execution with when it ran, several as ranges", () => {
  assert.deepEqual(traceOf(entry("run", { number: 3, started_at: "2026-11-23T09:21:25Z" })), { sentence: "deleted execution #3", ran: "2026-11-23T09:21:25Z" });
  assert.deepEqual(traceOf(entry("run", { numbers: [3, 4, 5, 9], count: 4 })), { sentence: "deleted 4 executions (#3–#5, #9)", ran: null });
  assert.equal(traceOf(entry("run", { numbers: [7], count: 1 })).sentence, "deleted 1 execution (#7)");
  assert.equal(traceOf(entry("run", { numbers: [1, 2], count: 80 })).sentence, "deleted 80 executions (#1, #2, …)"); // the rest only counted
});

test("numbers are compressed to ranges, two in a row stay as two", () => {
  assert.equal(rangesText([5, 3, 4]), "#3–#5");
  assert.equal(rangesText([1, 2]), "#1, #2");
  assert.equal(rangesText([1, 3, 5]), "#1, #3, #5");
  assert.equal(rangesText([2], 3), "#2, …");
});

test("old traces and the operator's own actors are named in words, a person or token as they are", () => {
  const system = (name) => entry("run", {}, { actor_kind: "system", actor_name: name });
  assert.equal(actorName(system("unknown")), "someone");
  assert.equal(actorName(system("retention rule")), "retention rule");
  assert.equal(actorName(system("operator guard")), "operator guard");
  assert.equal(actorName(entry("run", {}, { actor_kind: "api", actor_name: "opencode" })), "opencode");
  assert.equal(actorName(entry("run", {}, { actor_kind: "user", actor_name: "You" })), "You");
});

test("the preview of a comment is its first words on one line, cut with an ellipsis", () => {
  assert.equal(previewOf("was geht ab"), "was geht ab");
  assert.equal(previewOf("line one\n\n  line   two"), "line one line two");
  const cut = previewOf("x".repeat(200));
  assert.equal(cut.length, 80);
  assert.ok(cut.endsWith("…"));
  assert.equal(previewOf(null), "");
});

test("the timeline is newest first and a run that still exists is shown once, as the live row", () => {
  const executions = [execution("x1", 1, "2026-11-24T08:00:00Z"), execution("x2", 2, "2026-11-24T09:00:00Z")];
  const activity = [
    entry("lane", { from: "A", to: "B" }, { id: "c1", created_at: "2026-11-24T08:30:00Z" }),
    entry("run", { number: 1 }, { id: "t1", execution_id: "x1", created_at: "2026-11-24T08:00:00Z" }), // x1 is still there
    entry("run", { number: 0 }, { id: "t0", execution_id: "gone", created_at: "2026-11-24T07:00:00Z" }), // deleted
    entry("created", {}, { id: "c0", created_at: "2026-11-24T06:00:00Z" }),
  ];
  const items = mergeTimeline(executions, activity);
  assert.deepEqual(
    items.map((i) => [i.type, i.key]),
    [["execution", "e:x2"], ["change", "a:c1"], ["execution", "e:x1"], ["trace", "a:t0"], ["change", "a:c0"]],
  );
});

test("when a run is deleted its live row goes and its trace takes the place, once", () => {
  const trace = entry("run", { number: 1 }, { id: "t1", execution_id: "x1", created_at: "2026-11-24T08:00:00Z" });
  assert.deepEqual(mergeTimeline([execution("x1", 1, "2026-11-24T08:00:00Z")], [trace]).map((i) => i.type), ["execution"]);
  assert.deepEqual(mergeTimeline([], [trace]).map((i) => i.type), ["trace"]);
});

test("entries at the same time keep a fixed order", () => {
  const a = entry("title", {}, { id: "a" });
  const b = entry("lane", {}, { id: "b" });
  assert.deepEqual(mergeTimeline([], [a, b]).map((i) => i.key), mergeTimeline([], [b, a]).map((i) => i.key));
});

test("the filter shows all, only runs (live and deleted), only changes or only comments (and their deletions)", () => {
  const items = mergeTimeline(
    [execution("x2", 2, "2026-11-24T09:00:00Z")],
    [
      entry("lane", {}, { id: "c1", created_at: "2026-11-24T08:30:00Z" }),
      entry("run", {}, { id: "t0", execution_id: "gone", created_at: "2026-11-24T07:00:00Z" }),
      entry("comment", { comment_id: "k1" }, { id: "k", created_at: "2026-11-24T08:45:00Z" }),
      entry("comment_deleted", {}, { id: "kd", created_at: "2026-11-24T08:50:00Z" }),
    ],
  );
  assert.deepEqual(filterTimeline(items, "all").map((i) => i.type), ["execution", "comment", "comment", "change", "trace"]);
  assert.deepEqual(filterTimeline(items, "runs").map((i) => i.type), ["execution", "trace"]);
  assert.deepEqual(filterTimeline(items, "changes").map((i) => i.type), ["change"]);
  assert.deepEqual(filterTimeline(items, "comments").map((i) => i.entry.kind), ["comment_deleted", "comment"]);
});

const many = (n) => Array.from({ length: n }, (_, i) => ({ type: "change", key: `a:${i}`, entry: { kind: i === n - 1 ? "created" : "lane" } }));

test("collapsed, the newest ten stay and the created entry at the bottom; the rest is counted", () => {
  const { shown, hidden } = collapse(many(25), false);
  assert.equal(shown.length, 11);
  assert.equal(shown.at(-1).entry.kind, "created"); // the anchor is always there
  assert.equal(shown[0].key, "a:0");
  assert.equal(hidden, 14);
});

test("a timeline that fits, or an expanded one, hides nothing; without a created entry there is no anchor", () => {
  assert.equal(collapse(many(10), false).hidden, 0);
  assert.equal(collapse(many(11), false).hidden, 0); // the 11th IS the anchor: nothing to fold
  assert.equal(collapse(many(25), true).hidden, 0);
  assert.equal(collapse(many(25), true).shown.length, 25);
  const noAnchor = many(25).map((item) => ({ ...item, entry: { kind: "lane" } }));
  assert.deepEqual([collapse(noAnchor, false).shown.length, collapse(noAnchor, false).hidden], [10, 15]);
});

const comments = (n) => Array.from({ length: n }, (_, i) => ({ id: `c${i}` })); // oldest first

test("comments: the newest ten are shown, oldest first, the older ones are counted", () => {
  const { shown, hidden } = collapseComments(comments(25), false);
  assert.deepEqual([shown[0].id, shown.at(-1).id, shown.length, hidden], ["c15", "c24", 10, 15]);
  assert.equal(collapseComments(comments(10), false).hidden, 0);
  assert.equal(collapseComments(comments(25), true).shown.length, 25);
});

test("a comment being edited is never folded away: everything is shown then", () => {
  assert.equal(collapseComments(comments(25), false, 10, "c3").shown.length, 25);
  assert.equal(collapseComments(comments(25), false, 10, "c20").shown.length, 10); // already in view
  assert.equal(collapseComments(comments(25), false, 10, "gone").shown.length, 10);
});

test("a jump to a comment under the fold needs the list expanded first, one in view or unknown does not", () => {
  assert.equal(isHiddenComment(comments(25), "c3"), true);
  assert.equal(isHiddenComment(comments(25), "c15"), false);
  assert.equal(isHiddenComment(comments(25), "c24"), false);
  assert.equal(isHiddenComment(comments(25), "nope"), false);
  assert.equal(isHiddenComment(comments(5), "c0"), false);
});

test("a deleted comment's entry goes, the others stay", () => {
  const entries = [entry("comment", { comment_id: "k1" }, { id: "1" }), entry("comment", { comment_id: "k2" }, { id: "2" }), entry("lane", {}, { id: "3" })];
  assert.deepEqual(withoutComment(entries, "k1").map((e) => e.id), ["2", "3"]);
});

test("each kind of event has its marker: an icon and a tone", () => {
  const item = (type, extra) => ({ type, ...extra });
  assert.deepEqual(markerOf(item("execution", { execution: { status: "done" } })), { icon: "check", tone: "ok" });
  assert.deepEqual(markerOf(item("execution", { execution: { status: "failed" } })), { icon: "x", tone: "bad" });
  assert.deepEqual(markerOf(item("execution", { execution: { status: "running" } })), { icon: "play", tone: "accent" });
  assert.deepEqual(markerOf(item("trace", { entry: { kind: "run" } })), { icon: "trash", tone: "bad" });
  assert.deepEqual(markerOf(item("comment", { entry: { kind: "comment" } })), { icon: "message", tone: "accent" });
  assert.deepEqual(markerOf(item("comment", { entry: { kind: "comment_deleted" } })), { icon: "trash", tone: "bad" });
  assert.deepEqual(markerOf(item("change", { entry: { kind: "created" } })), { icon: "plug", tone: "ok" });
  assert.deepEqual(markerOf(item("change", { entry: { kind: "lane" } })).icon, "columns");
  assert.deepEqual(markerOf(item("change", { entry: { kind: "never-seen" } })), { icon: "settings", tone: "muted" });
});

test("a live entry is added once, in front, and replaces one with the same id", () => {
  const one = entry("lane", {}, { id: "1" });
  const two = entry("title", {}, { id: "2" });
  assert.deepEqual(withEntry([one], two).map((e) => e.id), ["2", "1"]);
  assert.deepEqual(withEntry([two, one], { ...one, kind: "parent" }).map((e) => [e.id, e.kind]), [["1", "parent"], ["2", "title"]]);
});
