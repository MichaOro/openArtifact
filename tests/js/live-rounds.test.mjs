/* The rounds of a running agent as the panel draws them (components/live-rounds.js): names, counts and states as text. */
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { installDocument, textOf, uninstallDocument } from "./support.mjs";

const { liveRounds } = await import("../../openartifact/static/js/components/live-rounds.js");
const { noteAgentCall, noteAgentTurn, liveSummary } = await import("../../openartifact/static/js/execution/visit-model.js");

beforeEach(() => installDocument(["check", "x"]));
afterEach(() => uninstallDocument());

test("nothing heard, nothing drawn", () => {
  assert.equal(liveRounds(undefined, null), null);
});

test("each round shows its words, its tokens and its calls with their state", () => {
  const live = new Map();
  noteAgentTurn(live, { agent_node_id: "a", turn: 1, state: "finished", text: "Looking at the README.", tokens: 90, total_tokens: 90 });
  noteAgentCall(live, { agent_node_id: "a", turn: 1, state: "started", tool: "get_file_contents", tool_node_name: "GitHub MCP" });
  noteAgentCall(live, { agent_node_id: "a", turn: 1, state: "finished", tool: "get_file_contents", ok: true, duration_ms: 1700 });
  noteAgentTurn(live, { agent_node_id: "a", turn: 2, state: "started" });
  const agent = live.get("a");
  const root = liveRounds(agent, liveSummary(agent));
  assert.equal(root.tagName, "section");
  const text = textOf(root);
  assert.ok(text.includes("Looking at the README.") && text.includes("get_file_contents") && text.includes("1.7 s"), text);
  assert.ok(text.includes("2 rounds") && text.includes("1 calls") && text.includes("90 tokens"), text);
  assert.ok(text.includes("asking the model"), "the open round says it is waiting for the model");
});

test("a wrap-up round and a failed call say so", () => {
  const live = new Map();
  noteAgentTurn(live, { agent_node_id: "a", turn: 1, state: "started", wrap_up: "the limit of 2 iterations" });
  noteAgentCall(live, { agent_node_id: "a", turn: 1, state: "started", tool: "x", tool_node_name: "T" });
  noteAgentCall(live, { agent_node_id: "a", turn: 1, state: "finished", tool: "x", ok: false, duration_ms: 20 });
  const agent = live.get("a");
  const text = textOf(liveRounds(agent, liveSummary(agent)));
  assert.ok(text.includes("Final answer (the limit of 2 iterations)") && text.includes("1 failed"), text);
});
