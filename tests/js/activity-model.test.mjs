/* The pure parts of the History timeline (static/js/tasks/activity-model.js): what a change says, the merge of live
 * executions and activity entries, and the filter. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { filterTimeline, mergeTimeline, sentenceOf, traceAsExecution, withEntry } from "../../openartifact/static/js/tasks/activity-model.js";

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

test("a trace is read like an execution so the row cells can show it", () => {
  const trace = entry("run", { number: 3, pipeline: "Flow", status: "failed", started_at: "2026-11-24T07:00:00Z", finished_at: "2026-11-24T07:00:02Z", duration_ms: 2500, steps: 4 }, { execution_id: "x1", actor_kind: "mcp" });
  assert.deepEqual(traceAsExecution(trace), {
    id: "x1",
    number: 3,
    status: "failed",
    pipeline_name: "Flow",
    started_at: "2026-11-24T07:00:00Z",
    finished_at: "2026-11-24T07:00:02Z",
    duration_seconds: 2.5,
    started_by: "mcp",
    step_count: 4,
  });
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

test("the filter shows all, only runs (live and deleted) or only changes", () => {
  const items = mergeTimeline(
    [execution("x2", 2, "2026-11-24T09:00:00Z")],
    [entry("lane", {}, { id: "c1", created_at: "2026-11-24T08:30:00Z" }), entry("run", {}, { id: "t0", execution_id: "gone", created_at: "2026-11-24T07:00:00Z" })],
  );
  assert.deepEqual(filterTimeline(items, "all").map((i) => i.type), ["execution", "change", "trace"]);
  assert.deepEqual(filterTimeline(items, "runs").map((i) => i.type), ["execution", "trace"]);
  assert.deepEqual(filterTimeline(items, "changes").map((i) => i.type), ["change"]);
});

test("a live entry is added once, in front, and replaces one with the same id", () => {
  const one = entry("lane", {}, { id: "1" });
  const two = entry("title", {}, { id: "2" });
  assert.deepEqual(withEntry([one], two).map((e) => e.id), ["2", "1"]);
  assert.deepEqual(withEntry([two, one], { ...one, kind: "parent" }).map((e) => [e.id, e.kind]), [["1", "parent"], ["2", "title"]]);
});
