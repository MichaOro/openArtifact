import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { chip, installDocument, uninstallDocument } from "./support.mjs";

const f = await import("../../openartifact/static/js/tasks/history-format.js");

beforeEach(() => installDocument(["check", "clock", "x", "stop"]));
afterEach(() => uninstallDocument());

test("formatDuration: tenths below ten seconds, whole seconds, minutes, hours", () => {
  assert.equal(f.formatDuration(0), "0 s");
  assert.equal(f.formatDuration(0.44), "0.4 s");
  assert.equal(f.formatDuration(9.96), "10 s");
  assert.equal(f.formatDuration(9.949), "9.9 s");
  assert.equal(f.formatDuration(12.4), "12 s");
  assert.equal(f.formatDuration(59.6), "1 min 0 s");
  assert.equal(f.formatDuration(185), "3 min 5 s");
  assert.equal(f.formatDuration(3599), "59 min 59 s");
  assert.equal(f.formatDuration(3600), "1 h 0 min");
  assert.equal(f.formatDuration(7380), "2 h 3 min");
});

test("formatDuration: a negative value is shown as zero; a missing one as nothing", () => {
  assert.equal(f.formatDuration(-3), "0 s");
  assert.equal(f.formatDuration(null), "");
  assert.equal(f.formatDuration(undefined), "");
  assert.equal(f.formatDuration(Number.NaN), "");
});

test("formatTime: empty for nothing, otherwise the local rendering of the instant", () => {
  assert.equal(f.formatTime(""), "");
  assert.equal(f.formatTime(null), "");
  const iso = "2026-03-10T12:34:56Z";
  assert.equal(f.formatTime(iso), new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" }));
});

test("formatDateTime and formatDay render as the inline helpers of the lists did: to the minute, and the day only", () => {
  const iso = "2026-03-04T05:06:07Z";
  assert.equal(f.formatDateTime(iso), new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }));
  assert.equal(f.formatDay(iso), new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }));
  assert.notEqual(f.formatDateTime(iso), f.formatTime(iso), "to the minute, without the seconds formatTime shows");
  assert.ok(f.formatDateTime(iso).startsWith(f.formatDay(iso)), "the date part is the day");
});

test("secondsBetween: the gap, zero at the least, until now without an end, null without a start", () => {
  assert.equal(f.secondsBetween("2026-03-10T12:00:00Z", "2026-03-10T12:00:03.500Z"), 3.5);
  assert.equal(f.secondsBetween("2026-03-10T12:00:05Z", "2026-03-10T12:00:00Z"), 0, "an end before the start (clock skew)");
  assert.equal(f.secondsBetween(null, "2026-03-10T12:00:00Z"), null);
  const since = new Date(Date.now() - 4000).toISOString();
  const open = f.secondsBetween(since, null);
  assert.ok(open >= 3.9 && open < 6, String(open));
});

test("executionSeconds prefers the server's duration, else the elapsed time", () => {
  assert.equal(f.executionSeconds({ duration_seconds: 2.5, started_at: "2026-03-10T12:00:00Z", finished_at: "2026-03-10T13:00:00Z" }), 2.5);
  assert.equal(f.executionSeconds({ duration_seconds: 0, started_at: "2026-03-10T12:00:00Z", finished_at: "2026-03-10T13:00:00Z" }), 0, "zero is a value");
  assert.equal(f.executionSeconds({ duration_seconds: null, started_at: "2026-03-10T12:00:00Z", finished_at: "2026-03-10T12:00:10Z" }), 10);
});

test("originLabel names the known origins and shows an unknown one as it is", () => {
  assert.deepEqual(["user", "api", "mcp", "system"].map(f.originLabel), ["User", "API", "MCP", "System"]);
  assert.equal(f.originLabel("cron"), "cron");
  assert.equal(f.originLabel(null), "");
  assert.equal(f.originLabel(undefined), "");
});

test("plural", () => {
  assert.equal(f.plural(0, "step"), "0 steps");
  assert.equal(f.plural(1, "step"), "1 step");
  assert.equal(f.plural(2, "step"), "2 steps");
});

test("setChip writes the status, the text and the icon", () => {
  for (const [status, text, icon] of [["running", "Running", "clock"], ["done", "Done", "check"], ["failed", "Failed", "x"], ["stopped", "Stopped", "stop"], ["pass", "Pass", "check"], ["fail", "Fail", "x"]]) {
    const c = chip();
    f.setChip(c.root, status);
    assert.equal(c.root.dataset.status, status);
    assert.equal(c.textSlot.textContent, text);
    assert.equal(c.iconSlot.children[0].iconName, icon);
  }
});

test("setChip shows an unknown status as it is, with the clock", () => {
  const c = chip();
  f.setChip(c.root, "weird");
  assert.equal(c.textSlot.textContent, "weird");
  assert.equal(c.iconSlot.children[0].iconName, "clock");
});
