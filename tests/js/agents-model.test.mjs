/* The pure helpers of the agent pages (static/js/agents/model.js): what a list shows, the overrides of
 * a node, the input mapping and the facts of an agent step. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  OVERRIDES,
  optionsOf,
  sampleHint,
  toolCallRows,
  agentChips,
  agentFacts,
  fieldLabel,
  formatMapping,
  inputStateText,
  isPlainHttp,
  mappingRows,
  numberOf,
  overridesOf,
  parseMapping,
  providerInEffect,
  seconds,
  showValue,
  usableModels,
  useText,
} from "../../openartifact/static/js/agents/model.js";

test("the chips of an agent say whether it runs, what is published and whether the draft differs", () => {
  assert.deepEqual(agentChips({ active: true, published_number: 3, draft_changed: false }), [
    ["Active", "ok"],
    ["v3 published", ""],
  ]);
  assert.deepEqual(agentChips({ active: false, published_number: null, draft_changed: true }), [
    ["Inactive", "bad"],
    ["Not published", "warn"],
  ]);
  assert.deepEqual(agentChips({ active: true, published_number: 1, draft_changed: true }).at(-1), ["Draft has changes", "accent"]);
});

test("how many nodes use an agent is said in words", () => {
  assert.equal(useText(0), "Not used by a node");
  assert.equal(useText(1), "Used by 1 node");
  assert.equal(useText(4), "Used by 4 nodes");
});

test("an override is a setting with a value, and false and 0 are values", () => {
  const config = { agent_id: "a", inputs: "x = 1", system_prompt_enabled: false, retries: 0, temperature: null, model: undefined, max_tokens: 5 };
  assert.deepEqual(overridesOf(config), ["system_prompt_enabled", "max_tokens", "retries"]);
  assert.deepEqual(overridesOf(null), []);
  assert.deepEqual(overridesOf({}), []);
});

test("every overridable setting has a label and the server's keys are covered", () => {
  // agents/schemas.py OVERRIDABLE
  assert.deepEqual(new Set(OVERRIDES.map((o) => o.key)), new Set(["system_prompt_enabled", "system_prompt", "user_prompt", "provider_id", "model", "temperature", "max_tokens", "request_timeout_seconds", "total_timeout_seconds", "retries", "max_iterations"]));
  assert.equal(fieldLabel("max_tokens"), "Max tokens");
  assert.equal(fieldLabel("inputs"), "Inputs");
  assert.equal(fieldLabel("unknown_key"), "unknown_key");
});

test("values are shown as text, a switch as On or Off", () => {
  assert.equal(showValue(null), "not set");
  assert.equal(showValue(""), "not set");
  assert.equal(showValue(false), "Off");
  assert.equal(showValue(true, "switch"), "On");
  assert.equal(showValue(0), "0");
  assert.equal(showValue("text"), "text");
});

test("a mapping is name = value per line and survives a round trip", () => {
  const text = "ticket = ${node.Fetch.output}\n\ninput.context = a = b\nBad Name = x\nno equals\nticket = second";
  assert.deepEqual(parseMapping(text), { ticket: "${node.Fetch.output}", context: "a = b" });
  assert.deepEqual(parseMapping(null), {});
  assert.equal(formatMapping({ ticket: " ${var.t} ", empty: "  ", multi: "a\nb" }), "ticket = ${var.t}\nmulti = a b");
  assert.deepEqual(parseMapping(formatMapping({ a: "1", b: "x = y" })), { a: "1", b: "x = y" });
});

test("the rows of a mapping are the declared inputs, then what is mapped without being declared", () => {
  const inputs = [
    { name: "ticket", type: "string", required: true },
    { name: "context", type: "string", required: false, default: "none" },
  ];
  const rows = mappingRows(inputs, "ticket = T\nold = gone");
  assert.deepEqual(
    rows.map((r) => [r.name, r.value, r.declared, r.required]),
    [
      ["ticket", "T", true, true],
      ["context", "", true, false],
      ["old", "gone", false, false],
    ],
  );
  assert.equal(rows[1].default, "none");
});

test("only enabled models that are still listed can be chosen", () => {
  const provider = {
    models: [
      { model_id: "a", enabled: true, available: true },
      { model_id: "b", enabled: false, available: true },
      { model_id: "c", enabled: true, available: false },
    ],
  };
  assert.deepEqual(usableModels(provider), ["a"]);
  assert.deepEqual(usableModels(null), []);
});

test("the provider in effect is the named one, else the default one", () => {
  const providers = [
    { id: "p1", is_default: false },
    { id: "p2", is_default: true },
  ];
  assert.equal(providerInEffect(providers, "p1").id, "p1");
  assert.equal(providerInEffect(providers, null).id, "p2");
  assert.equal(providerInEffect(providers, "gone"), null); // a deleted provider is not replaced silently
  assert.equal(providerInEffect([], null), null);
});

test("a number of a form is null when empty and NaN when it is none", () => {
  assert.equal(numberOf(""), null);
  assert.equal(numberOf("  "), null);
  assert.equal(numberOf(null), null);
  assert.equal(numberOf(" 0.5 "), 0.5);
  assert.ok(Number.isNaN(numberOf("many")));
});

test("the facts of an agent step name model, tokens and attempts", () => {
  const data = { provider: "Local", model: "small", agent_version: 2, attempts: 3, finish_reason: "length", usage: { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18 } };
  assert.deepEqual(agentFacts(data), ["Local: small", "Agent version 2", "18 tokens (11 in, 7 out)", "3 attempts", "Finish reason: length"]);
  assert.deepEqual(agentFacts({ provider: "L", model: "m", attempts: 1, finish_reason: "stop", usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: null } }), ["L: m", "6 tokens (4 in, 2 out)"]);
  assert.deepEqual(agentFacts(null), []);
  assert.deepEqual(agentFacts({ agent_id: "a", agent_version: 1 }), ["Agent version 1"]);
});

test("tokens the provider did not report are not shown as zero", () => {
  const facts = agentFacts({ provider: "L", model: "m", attempts: 1, usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null } });
  assert.deepEqual(facts, ["L: m", "Tokens: not reported by the provider"]);
  assert.deepEqual(agentFacts({ provider: "L", model: "m", usage: null }), ["L: m"]); // a failed request has no usage at all
  assert.deepEqual(agentFacts({ usage: { total_tokens: 9 } }), ["9 tokens"]);
});

test("the state of an input and a duration are words", () => {
  assert.equal(inputStateText("unset"), "not set (empty)");
  assert.equal(inputStateText("pending"), "known when the node runs");
  assert.equal(inputStateText("other"), "other");
  assert.equal(seconds(1234), "1.2 s");
  assert.equal(seconds(45000), "45 s");
  assert.equal(seconds(null), "");
});

test("the tool calls of a step: turn, tool, arguments, result (an error marked) and time", () => {
  const turns = [
    { attempts: [], tool_calls: [{ tool: "get_issue", arguments: '{"number": 7}', result: "Issue #7", error: false, duration_ms: 1500 }] },
    { attempts: [], tool_calls: [{ tool: "nothere", arguments: "{}", result: "Error: there is no tool named nothere", error: true, duration_ms: 0 }] },
    { attempts: [], tool_calls: [] },
  ];
  assert.deepEqual(toolCallRows(turns), [
    ["1", "get_issue", '{"number": 7}', { text: "Issue #7", state: "" }, "1.5 s"],
    ["2", "nothere", "{}", { text: "Error: there is no tool named nothere", state: "error" }, "0.0 s"],
  ]);
  assert.deepEqual(toolCallRows(undefined), []); // a step from before tools
});

test("max iterations is a setting a node may override", () => {
  assert.deepEqual(OVERRIDES.find((o) => o.key === "max_iterations"), { key: "max_iterations", label: "Max iterations", kind: "integer", min: 1, max: 50 });
});

test("only an http address needs the confirmation of an unencrypted connection", () => {
  assert.equal(isPlainHttp("http://litellm:4000/v1"), true);
  assert.equal(isPlainHttp("  HTTP://127.0.0.1:4000/v1"), true);
  assert.equal(isPlainHttp("https://api.example.org/v1"), false);
  assert.equal(isPlainHttp("httpx://example.org"), false);
  assert.equal(isPlainHttp(""), false);
  assert.equal(isPlainHttp(null), false);
});

test("the optional areas are switched on as the backend reads them: a stored switch wins, else the data decides", () => {
  assert.deepEqual(optionsOf({ system_prompt_enabled: false, inputs: [], retries: 3, request_timeout_seconds: 60, total_timeout_seconds: 600, max_iterations: 10 }), { system_prompt: false, inputs: false, limits: false });
  assert.deepEqual(optionsOf({ system_prompt_enabled: true, inputs: [{ name: "a" }], temperature: 0.2 }), { system_prompt: true, inputs: true, limits: true });
  assert.equal(optionsOf({ inputs: [], retries: 1, request_timeout_seconds: 60, total_timeout_seconds: 600, max_iterations: 10 }).limits, true); // a limit that differs counts
  assert.deepEqual(optionsOf({ inputs: [{ name: "a" }], temperature: 0.2, inputs_enabled: false, limits_enabled: false }), { system_prompt: false, inputs: false, limits: false }); // switched off, data kept
});

test("the grey example of a Quick test field says what goes in", () => {
  assert.equal(sampleHint({ type: "string", default: "none" }), "e.g. none");
  assert.equal(sampleHint({ type: "string", default: null, description: "the ticket text" }), "e.g. the ticket text");
  assert.equal(sampleHint({ type: "number", default: null }), "e.g. 3");
  assert.equal(sampleHint({ type: "boolean" }), "e.g. true");
  assert.equal(sampleHint({ type: "string" }), "e.g. Login fails after the update");
});
