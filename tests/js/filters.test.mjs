import assert from "node:assert/strict";
import { test } from "node:test";

const { Filters, STATUSES, ORIGINS, RANGES } = await import("../../openartifact/static/js/executions/filters.js");

const NOW = Date.parse("2026-03-10T12:00:00Z");

test("the allowed values and ranges", () => {
  assert.deepEqual(STATUSES, ["running", "done", "failed", "stopped"]);
  assert.deepEqual(ORIGINS, ["user", "api", "mcp", "system"]);
  assert.deepEqual(RANGES, { "1h": 3600, "24h": 86400, "7d": 604800 });
});

test("an empty value has nothing set", () => {
  const f = new Filters();
  assert.deepEqual([f.status, f.startedBy, f.pipeline, f.q, f.range, f.since, f.until, f.pageSize], [[], [], "", "", "", "", "", ""]);
  assert.equal(f.active, false);
  assert.equal(f.activeCount, 0);
  assert.equal(f.custom, false);
  assert.equal(f.toSearch(), "");
});

test("the constructor puts statuses and origins into canonical order and drops unknown ones; text is trimmed", () => {
  const f = new Filters({ status: ["failed", "bogus", "running"], startedBy: ["mcp", "user"], pipeline: "  Flow ", q: " x ", range: "99h" });
  assert.deepEqual(f.status, ["running", "failed"]);
  assert.deepEqual(f.startedBy, ["user", "mcp"]);
  assert.equal(f.pipeline, "Flow");
  assert.equal(f.q, "x");
  assert.equal(f.range, "", "an unknown range is dropped");
});

test("fromSearch reads the API's names, comma separated, case and whitespace tolerant, deduplicated", () => {
  const f = Filters.fromSearch("?status=Failed, running,failed,nonsense&started_by=API,&pipeline=Release&q=hello%20world&since=2026-01-01&until=2026-02-01&page_size=5");
  assert.deepEqual(f.status, ["running", "failed"]);
  assert.deepEqual(f.startedBy, ["api"]);
  assert.equal(f.pipeline, "Release");
  assert.equal(f.q, "hello world");
  assert.equal(f.since, "2026-01-01");
  assert.equal(f.until, "2026-02-01");
  assert.equal(f.pageSize, "5");
  assert.equal(f.custom, true);
  assert.equal(Filters.fromSearch("").active, false);
  assert.equal(Filters.fromSearch("?range=24h").range, "24h");
});

test("toSearch and fromSearch round-trip", () => {
  const f = new Filters({ status: ["done", "failed"], startedBy: ["api"], pipeline: "Flow", q: "a&b", range: "7d", pageSize: "20" });
  assert.equal(f.toSearch(), "?status=done%2Cfailed&started_by=api&pipeline=Flow&q=a%26b&range=7d&page_size=20");
  assert.equal(Filters.fromSearch(f.toSearch()).toSearch(), f.toSearch());
  const custom = new Filters({ since: "2026-01-01", until: "2026-02-01" });
  assert.equal(custom.toSearch(), "?since=2026-01-01&until=2026-02-01");
});

test("a preset range wins over since and until in the URL", () => {
  assert.equal(new Filters({ range: "1h", since: "2026-01-01", until: "2026-02-01" }).toSearch(), "?range=1h");
});

test("with() changes some filters and keeps the rest (and normalises)", () => {
  const f = new Filters({ status: ["done"], q: "x", pageSize: "3" }).with({ status: ["failed"], q: " y " });
  assert.deepEqual([f.status, f.q, f.pageSize], [["failed"], "y", "3"]);
});

test("active and activeCount count kinds of filter; a time range of any form counts once; page_size is no filter", () => {
  assert.equal(new Filters({ pageSize: "5" }).active, false);
  assert.equal(new Filters({ status: ["done", "failed"] }).activeCount, 1);
  assert.equal(new Filters({ status: ["done"], startedBy: ["api"], pipeline: "p", q: "q", range: "1h" }).activeCount, 5);
  assert.equal(new Filters({ since: "2026-01-01", until: "2026-01-02" }).activeCount, 1);
  assert.equal(new Filters({ until: "2026-01-02" }).custom, true);
  assert.equal(new Filters({ range: "1h", since: "2026-01-01" }).custom, false);
});

test("toQuery: a preset range becomes a since computed from `now`", () => {
  const q = new Filters({ status: ["failed"], startedBy: ["user", "api"], pipeline: "Flow", q: "boom", range: "24h", until: "ignored" }).toQuery({ limit: 50, cursor: "abc", now: NOW });
  assert.equal(q.toString(), "status=failed&started_by=user%2Capi&pipeline=Flow&q=boom&since=2026-03-09T12%3A00%3A00.000Z&limit=50&cursor=abc");
});

test("toQuery: a custom range passes since and until through; nothing set gives an empty query", () => {
  assert.equal(new Filters({ since: "2026-01-01", until: "2026-02-01" }).toQuery().toString(), "since=2026-01-01&until=2026-02-01");
  assert.equal(new Filters().toQuery().toString(), "");
  assert.equal(new Filters().toQuery({ limit: 0 }).toString(), "", "no limit is sent for 0");
  assert.equal(new Filters({ range: "1h" }).toQuery({ now: NOW }).get("since"), "2026-03-10T11:00:00.000Z");
});

const run = (fields) => ({ status: "done", started_by: "user", pipeline_id: "p1", pipeline_name: "Release flow", started_at: "2026-03-10T11:30:00Z", ...fields });

test("mayInclude: no filter admits everything", () => {
  assert.equal(new Filters().mayInclude(run({}), NOW), true);
});

test("mayInclude: status and origin", () => {
  assert.equal(new Filters({ status: ["failed"] }).mayInclude(run({}), NOW), false);
  assert.equal(new Filters({ status: ["done", "failed"] }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ startedBy: ["api"] }).mayInclude(run({}), NOW), false);
  assert.equal(new Filters({ startedBy: ["user"] }).mayInclude(run({}), NOW), true);
});

test("mayInclude: the pipeline matches by id or by a part of its name, ignoring case", () => {
  assert.equal(new Filters({ pipeline: "p1" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ pipeline: "RELEASE" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ pipeline: "other" }).mayInclude(run({}), NOW), false);
  assert.equal(new Filters({ pipeline: "other" }).mayInclude(run({ pipeline_name: null }), NOW), false);
});

test("mayInclude: the text search never excludes (an event has no artifact title)", () => {
  assert.equal(new Filters({ q: "nothing like it" }).mayInclude(run({}), NOW), true);
});

test("mayInclude: a preset range excludes what started before it", () => {
  assert.equal(new Filters({ range: "1h" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ range: "1h" }).mayInclude(run({ started_at: "2026-03-10T10:59:59Z" }), NOW), false);
  assert.equal(new Filters({ range: "1h" }).mayInclude(run({ started_at: "2026-03-10T11:00:00Z" }), NOW), true, "exactly at the boundary is inside");
});

test("mayInclude: since and until given by hand; an unreadable since excludes nothing", () => {
  assert.equal(new Filters({ since: "2026-03-10T12:00:00Z" }).mayInclude(run({}), NOW), false);
  assert.equal(new Filters({ since: "2026-03-10T11:00:00Z" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ until: "2026-03-10T11:00:00Z" }).mayInclude(run({}), NOW), false);
  assert.equal(new Filters({ until: "2026-03-10T11:30:00Z" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ since: "garbage" }).mayInclude(run({}), NOW), true);
  assert.equal(new Filters({ range: "1h", until: "2000-01-01" }).mayInclude(run({}), NOW), true, "until is ignored beside a preset");
});

test("mayInclude uses the current time when none is given", () => {
  const recent = run({ started_at: new Date().toISOString() });
  assert.equal(new Filters({ range: "1h" }).mayInclude(recent), true);
  assert.equal(new Filters({ range: "1h" }).mayInclude(run({ started_at: "2020-01-01T00:00:00Z" })), false);
});

test("the dry-run filter lives in the URL, goes to the API and decides which events may belong", () => {
  const only = Filters.fromSearch("?dry_run=only");
  assert.equal(only.dryRun, "only");
  assert.equal(only.toSearch(), "?dry_run=only");
  assert.equal(only.toQuery().get("dry_run"), "only");
  assert.equal(only.activeCount, 1);
  assert.equal(only.mayInclude({ status: "done", started_at: "2026-03-10T11:00:00Z", dry_run: true }, NOW), true);
  assert.equal(only.mayInclude({ status: "done", started_at: "2026-03-10T11:00:00Z", dry_run: false }, NOW), false);
  const real = Filters.fromSearch("?dry_run=exclude");
  assert.equal(real.mayInclude({ status: "done", started_at: "2026-03-10T11:00:00Z", dry_run: true }, NOW), false);
  assert.equal(real.mayInclude({ status: "done", started_at: "2026-03-10T11:00:00Z" }, NOW), true);
  assert.equal(Filters.fromSearch("?dry_run=maybe").dryRun, "", "an unknown value is dropped");
  assert.equal(new Filters().toSearch(), "");
});

test("the observed runs are a kind of their own: apart from the dry runs started by hand, in the URL and in the API query (ADR-088)", () => {
  const at = "2026-03-10T11:00:00Z";
  const manual = { status: "done", started_at: at, dry_run: true, observed: false };
  const watched = { status: "done", started_at: at, dry_run: true, observed: true };
  const only = Filters.fromSearch("?dry_run=only");
  assert.equal(only.toQuery().get("observed"), "exclude", "an observed run is a dry run for the server: the page leaves it out of 'Dry runs'");
  assert.equal(only.toSearch(), "?dry_run=only", "the link stays what it was");
  assert.equal(only.mayInclude(manual, NOW), true);
  assert.equal(only.mayInclude(watched, NOW), false);
  const observed = Filters.fromSearch("?observed=only");
  assert.equal(observed.dryRun, "observed");
  assert.equal(observed.toSearch(), "?observed=only");
  assert.equal(observed.toQuery().get("observed"), "only");
  assert.equal(observed.toQuery().get("dry_run"), null);
  assert.equal(observed.activeCount, 1);
  assert.equal(observed.mayInclude(watched, NOW), true);
  assert.equal(observed.mayInclude(manual, NOW), false);
  const real = Filters.fromSearch("?dry_run=exclude");
  assert.equal(real.mayInclude(watched, NOW), false, "an observed run is no real run");
  assert.equal(real.toQuery().get("observed"), null);
});

test("toQuery uses the current time when none is given", () => {
  const since = new Date(new Filters({ range: "1h" }).toQuery().get("since")).getTime();
  assert.ok(Math.abs(Date.now() - 3600_000 - since) < 5000);
});
