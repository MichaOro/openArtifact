/* The Execution Trace as pure logic (execution/trace-model.js): which rounds are drawn and in which order, how identical calls are grouped,
 * what a search and a filter leave, the numbers over the rounds. */
import assert from "node:assert/strict";
import { test } from "node:test";

const { CHUNK, SHOWN, arrange, groupCalls, matches, roundsFromDetail, roundsFromLive, startsOpen, summarize } = await import("../../openartifact/static/js/execution/trace-model.js");

const round = (turn, extra = {}) => ({ turn, state: "done", tokens: 100 * turn, ms: 1000, startedAt: null, error: null, wrapUp: null, finishReason: null, text: "", calls: [], ...extra });
const rounds = (n) => Array.from({ length: n }, (_, i) => round(i + 1));

test("the newest rounds come first: three of them, then the number left out, then the first round as an anchor", () => {
  const view = arrange(rounds(8));
  assert.deepEqual(view.shown.map((r) => r.turn), [8, 7, 6]);
  assert.equal(view.first.turn, 1);
  assert.equal(view.hidden, 4, "rounds 5 to 2 stay hidden");
  assert.equal(view.more, 4);
  assert.equal(SHOWN, 3);
});

test("with few rounds nothing is hidden and the first round is still the last row", () => {
  const view = arrange(rounds(4));
  assert.deepEqual(view.shown.map((r) => r.turn), [4, 3, 2]);
  assert.equal(view.first.turn, 1);
  assert.equal(view.hidden, 0);
  const one = arrange(rounds(1));
  assert.deepEqual(one.shown.map((r) => r.turn), [1]);
  assert.equal(one.first, null, "a single round is just the round");
  assert.deepEqual(arrange([]).shown, []);
});

test("Show more reveals one chunk of rounds at a time, however long the run is", () => {
  const long = rounds(100);
  const first = arrange(long);
  assert.equal(first.hidden, 100 - 1 - SHOWN);
  assert.equal(first.more, CHUNK, "one click reveals a chunk of twenty");
  const next = arrange(long, first.more);
  assert.deepEqual(next.shown.map((r) => r.turn).slice(0, 3), [100, 99, 98]);
  assert.equal(next.shown.length, SHOWN + CHUNK);
  assert.equal(next.hidden, first.hidden - CHUNK);
  const last = arrange(long, 96);
  assert.equal(last.hidden, 0);
  assert.equal(last.first.turn, 1);
});

test("the newest round is on top even when the rounds arrive in another order", () => {
  const view = arrange([round(2), round(5), round(1), round(4), round(3)]);
  assert.deepEqual(view.shown.map((r) => r.turn), [5, 4, 3]);
  assert.equal(view.hidden, 1, "round 2 is left out, round 1 stays as the anchor");
});

test("identical consecutive calls are one row with a count, the times added, failed and running winning", () => {
  const groups = groupCalls([
    { tool: "get_artifacts", node: "MCP", state: "ok", ms: 100 },
    { tool: "get_artifacts", node: "MCP", state: "ok", ms: 250 },
    { tool: "get_artifacts", node: "MCP", state: "failed", ms: 50, error: "boom" },
    { tool: "list_lanes", node: "MCP", state: "ok", ms: 10 },
    { tool: "get_artifacts", node: "MCP", state: "ok", ms: null },
  ]);
  assert.deepEqual(groups.map((g) => [g.tool, g.count]), [["get_artifacts", 3], ["list_lanes", 1], ["get_artifacts", 1]]);
  assert.equal(groups[0].ms, 400);
  assert.equal(groups[0].state, "failed");
  assert.equal(groups[0].error, "boom");
});

test("a search looks at tool names, node names and error texts; the filter keeps errors or rounds with calls", () => {
  const plain = round(1);
  const calling = round(2, { calls: [{ tool: "list_lanes", node: "OpenArtifact MCP", state: "ok", ms: 1 }] });
  const broken = round(3, { calls: [{ tool: "write", node: "", state: "failed", ms: 1, error: "permission denied" }] });
  const failedRequest = round(4, { state: "failed", error: "HTTP 500" });
  assert.equal(matches(calling, { query: "LANES" }), true, "case does not matter");
  assert.equal(matches(calling, { query: "openartifact" }), true);
  assert.equal(matches(plain, { query: "lanes" }), false);
  assert.equal(matches(broken, { query: "denied" }), true);
  assert.equal(matches(failedRequest, { query: "500" }), true);
  assert.deepEqual([plain, calling, broken, failedRequest].filter((r) => matches(r, { kind: "errors" })), [broken, failedRequest]);
  assert.deepEqual([plain, calling, broken, failedRequest].filter((r) => matches(r, { kind: "calls" })), [calling, broken]);
  assert.equal(matches(plain, {}), true);
});

test("a working round and a round with a failure start open, the others closed", () => {
  assert.equal(startsOpen(round(1, { state: "running" })), true);
  assert.equal(startsOpen(round(2, { state: "failed" })), true);
  assert.equal(startsOpen(round(3, { calls: [{ tool: "x", node: "", state: "failed", ms: 1 }] })), true);
  assert.equal(startsOpen(round(4)), false);
});

test("the summary counts rounds, calls and failures and prefers the known totals", () => {
  const list = [round(1, { calls: [{ tool: "a", node: "", state: "ok", ms: 1 }] }), round(2, { calls: [{ tool: "a", node: "", state: "failed", ms: 1 }] })];
  assert.deepEqual(summarize(list), { rounds: 2, calls: 2, failed: 1, tokens: 300, ms: 2000 });
  assert.deepEqual(summarize(list, { totalTokens: 999, durationMs: 5000 }), { rounds: 2, calls: 2, failed: 1, tokens: 999, ms: 5000 });
  assert.equal(summarize([round(1, { tokens: null, ms: null })]).tokens, null, "unknown stays unknown");
  assert.equal(summarize([]).ms, null);
});

test("the rounds of a finished step come from its turns: the request time, the tokens, the calls with their errors, no message text", () => {
  const list = roundsFromDetail({
    turns: [
      { attempts: [{ started_at: "2026-11-27T10:00:00Z", duration_ms: 400 }, { started_at: "2026-11-27T10:00:01Z", duration_ms: 600 }], text: "I will look.", tokens: 90, finish_reason: "tool_calls", tool_calls: [{ tool: "ping", node_name: "Pinger", error: false, result: "pong", duration_ms: 12 }, { tool: "bad", node_name: "Breaker", error: true, result: "  it   broke\nbadly ", duration_ms: 7 }] },
      { attempts: [], text: "Done.", finish_reason: "stop", tool_calls: [], wrap_up: "the limit of 2 iterations" },
      { attempts: [{ started_at: "2026-11-27T10:00:05Z", duration_ms: 50 }], error: "HTTP 500", tool_calls: [] },
    ],
  });
  assert.equal(list.length, 3);
  assert.deepEqual([list[0].turn, list[0].state, list[0].tokens, list[0].ms, list[0].startedAt], [1, "done", 90, 1000, "2026-11-27T10:00:00Z"]);
  assert.deepEqual(list[0].calls.map((c) => [c.tool, c.node, c.state, c.error]), [["ping", "Pinger", "ok", null], ["bad", "Breaker", "failed", "it broke badly"]]);
  assert.equal(list[0].text, "", "the message text is for a later stage");
  assert.equal(JSON.stringify(list).includes("pong"), false, "no result text");
  assert.equal(list[1].wrapUp, "the limit of 2 iterations");
  assert.equal(list[1].ms, null);
  assert.deepEqual([list[2].state, list[2].error], ["failed", "HTTP 500"]);
  assert.deepEqual(roundsFromDetail(null), []);
});

test("the rounds of a working agent come from the events and keep the clipped words that were heard", () => {
  const live = {
    tokens: 250,
    rounds: [
      { turn: 1, state: "done", text: "Looking.", tokens: 90, ms: 1500, startedAt: 1000, error: null, wrapUp: null, calls: [{ tool: "ping", node: "Pinger", state: "ok", ms: 12 }] },
      { turn: 2, state: "running", text: "", tokens: null, ms: null, startedAt: 2500, error: null, wrapUp: null, calls: [{ tool: "ping", node: "Pinger", state: "running", ms: null }] },
    ],
  };
  const list = roundsFromLive(live);
  assert.deepEqual(list.map((r) => [r.turn, r.state]), [[1, "done"], [2, "running"]]);
  assert.equal(list[0].text, "Looking.");
  assert.equal(list[1].calls[0].state, "running");
  assert.deepEqual(roundsFromLive(undefined), []);
});
