import assert from "node:assert/strict";
import { test } from "node:test";

const { arrange, shownKeys, LAST } = await import("../../openartifact/static/js/components/icon-list-model.js");
const { barVisibility, facts, liveNote, liveState, parseLimit, settingOf } = await import("../../openartifact/static/js/editor/observe-model.js");

const read = (state, extra = {}) => ({
  draft: { enabled: true },
  published: { enabled: true },
  draft_differs: false,
  state: { enabled: true, observing: true, ended: false, released: false, days: null, runs: null, runs_done: 0, started_at: null, ends_at: null, reason: null, ...state },
  ...extra,
});

test("the entries of the status bar keep their fixed order and the plus is always last", () => {
  const entries = [
    { key: "add", order: LAST, visible: true },
    { key: "guard", order: 20, visible: true },
    { key: "observe", order: 10, visible: true },
    { key: "ended", order: 5, visible: false },
  ];
  assert.deepEqual(arrange(entries).map((e) => e.key), ["ended", "observe", "guard", "add"]);
  assert.deepEqual(shownKeys(entries), ["observe", "guard", "add"], "eye, shield, plus");
});

test("an entry that is not active takes no place, so the others close up, and one that appears takes its own place", () => {
  const entries = [
    { key: "observe", order: 10, visible: true },
    { key: "guard", order: 20, visible: false },
    { key: "add", order: LAST, visible: true },
  ];
  assert.deepEqual(shownKeys(entries), ["observe", "add"], "no guard: the eye sits next to the plus");
  entries[1].visible = true;
  assert.deepEqual(shownKeys(entries), ["observe", "guard", "add"], "the shield appears between: the eye stays on its left");
  entries[0].visible = false;
  assert.deepEqual(shownKeys(entries), ["guard", "add"]);
});

test("the eye is there while the published mode observes, the stop sign while the observation has ended, nothing otherwise", () => {
  assert.equal(liveState(read({})), "observing");
  assert.deepEqual(barVisibility(read({})), { observe: true, ended: false });
  assert.deepEqual(barVisibility(read({ observing: false, ended: true })), { observe: false, ended: true });
  assert.deepEqual(barVisibility(read({ released: true, observing: false })), { observe: false, ended: false }, "released: it runs for real");
  assert.deepEqual(barVisibility(read({}, { published: null })), { observe: false, ended: false }, "only the published version is observed, a draft never");
  assert.deepEqual(barVisibility(null), { observe: false, ended: false });
});

test("a limit is empty (none), a whole number inside the range, or a named problem", () => {
  assert.deepEqual(parseLimit("", "days"), { value: null, error: null });
  assert.deepEqual(parseLimit(" 7 ", "days"), { value: 7, error: null });
  assert.equal(parseLimit("0", "days").error, "range");
  assert.equal(parseLimit("366", "days").error, "range");
  assert.equal(parseLimit("100000", "runs").error, null);
  assert.equal(parseLimit("100001", "runs").error, "range");
  assert.equal(parseLimit("2.5", "runs").error, "whole");
  assert.equal(parseLimit("abc", "runs").error, "whole");
});

test("the setting that goes to the draft has the three keys", () => {
  assert.deepEqual(settingOf({ enabled: true, days: 3, runs: null }), { enabled: true, days: 3, runs: null });
  assert.deepEqual(settingOf({ enabled: false }), { enabled: false, days: null, runs: null });
});

test("the line under the switch says what is live only while the draft differs", () => {
  assert.equal(liveNote(read({})), null, "they agree: nothing to say");
  assert.equal(liveNote(read({}, { draft_differs: true })), "observing");
  assert.equal(liveNote(read({ observing: false, ended: true }, { draft_differs: true })), "ended");
  assert.equal(liveNote(read({}, { draft_differs: true, published: null })), "off");
});

test("the facts of the eye: since, the runs counted (with the limit when there is one) and the end", () => {
  const all = facts(read({ started_at: "2026-11-27T08:00:00Z", runs: 5, runs_done: 2, ends_at: "2026-12-04T08:00:00Z" }));
  assert.deepEqual(all, [["since", { date: "2026-11-27" }], ["runs_of", { done: 2, runs: 5 }], ["ends", { date: "2026-12-04" }]]);
  assert.deepEqual(facts(read({ runs_done: 3 })), [["runs", { done: 3 }]], "no limit: just the count");
});
