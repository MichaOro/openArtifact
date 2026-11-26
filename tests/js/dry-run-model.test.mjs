import assert from "node:assert/strict";
import { test } from "node:test";

const m = await import("../../openartifact/static/js/editor/dry-run-model.js");

const INPUTS = [
  { name: "who", type: "text", required: true },
  { name: "times", type: "number", required: false, default: "2" },
  { name: "loud", type: "boolean", required: false },
  { name: "mood", type: "choice", required: false, choices: ["calm", "wild"] },
  { name: "tags", type: "list", required: false },
];

test("the form has one entry per declared input, in order, with the control its type is entered in", () => {
  const fields = m.formFields(INPUTS);
  assert.deepEqual(fields.map((f) => f.name), ["who", "times", "loud", "mood", "tags"]);
  assert.deepEqual(fields.map(m.controlOf), ["text", "number", "boolean", "choice", "lines"]);
  assert.deepEqual(fields[3].choices, ["calm", "wild"]);
  assert.equal(fields[1].default, "2");
  assert.deepEqual(m.formFields(undefined), []);
});

test("the faint text of an empty field is the default, or says the field is required", () => {
  const [who, times, loud] = m.formFields(INPUTS);
  assert.equal(m.placeholderOf(times), "2");
  assert.equal(m.placeholderOf(who), "Required");
  assert.equal(m.placeholderOf(loud), "");
});

test("only what was filled in is sent: an empty field is left to the declared default", () => {
  const fields = m.formFields(INPUTS);
  assert.deepEqual(m.inputsToSend(fields, { who: "Ann", times: "  ", loud: "true", tags: "a\r\nb" }), { who: "Ann", loud: "true", tags: "a\nb" });
  assert.deepEqual(m.inputsToSend(fields, {}), {});
});

test("a graph that declares no inputs sends none (the server refuses inputs for it)", () => {
  assert.equal(m.inputsToSend([], { who: "Ann" }), undefined);
  const body = m.runBody({ target: { pipeline_id: "p1" }, fields: [], entered: {}, version: "draft" });
  assert.deepEqual(body, { pipeline_id: "p1", version: "draft" });
});

test("a run of an action starts at the place a pipeline puts it", () => {
  const target = { pipeline_id: "p1", stage_id: "s1", action_id: "a1" };
  const body = m.runBody({ target, fields: m.formFields(INPUTS), entered: { who: "Ann" }, version: "published" });
  assert.deepEqual(body, { pipeline_id: "p1", version: "published", stage_id: "s1", action_id: "a1", inputs: { who: "Ann" } });
});

test("the cards are those of the board that are not archived, by number, with the lane beside them", () => {
  const tasks = [
    { id: "b", number: 2, title: "Second", status: "doing" },
    { id: "a", number: 1, title: "First", status: "todo" },
    { id: "z", number: 3, title: "Old", status: "todo", archived_at: "2026-11-01T00:00:00Z" },
  ];
  const lanes = [{ status: "todo", title: "To do" }, { status: "doing", title: "In progress" }];
  const options = m.cardOptions(tasks, lanes);
  assert.deepEqual(options.map((o) => [o.value, o.label, o.description]), [["a", "#1 First", "To do"], ["b", "#2 Second", "In progress"]]);
  assert.equal(options[0].keywords, "1");
});

test("the remembered card is used only while it is still among the options", () => {
  const options = [{ value: "a" }, { value: "b" }];
  assert.equal(m.rememberedCard(options, "b"), "b");
  assert.equal(m.rememberedCard(options, "gone"), null);
  assert.equal(m.rememberedCard(options, null), null);
  assert.equal(m.cardKey("g1"), "oa-dry-run-card-g1");
  assert.notEqual(m.cardKey("g1"), m.cardKey("g2"), "one memory per graph");
});

test("the place of an action: the remembered one, else the first, none when no pipeline puts it", () => {
  const placements = [{ action_id: "a1", pipeline_name: "P", stage_name: "S" }, { action_id: "a2", pipeline_name: "Q", stage_name: "T" }];
  assert.equal(m.chooseTarget(placements, "a2").action_id, "a2");
  assert.equal(m.chooseTarget(placements, "gone").action_id, "a1");
  assert.equal(m.chooseTarget([], "a1"), null);
  assert.equal(m.placementLabel(placements[1]), "Q · T");
});

test("the server's refusals read in plain words", () => {
  assert.match(m.startErrorText({ code: "stopped", status: 409 }), /emergency stop is on/);
  assert.match(m.startErrorText({ status: 409 }), /being processed/);
  assert.equal(m.startErrorText({ status: 422, detail: "input 'who' is required" }), "input 'who' is required");
  assert.equal(m.startErrorText({ status: 500, message: "Boom" }), "Boom");
  assert.deepEqual(m.problemLines([" a ", "", "b"]), ["a", "b"]);
});

test("a step says what it would have done when it was skipped, and why it failed when it did", () => {
  const rows = m.stepRows([
    { id: "3", seq: 3, kind: "output", outcome: "pass", node_name: "Output" },
    { id: "2", seq: 2, kind: "artifact", outcome: "pass", node_name: "Say hello", data: { dry_run: true, would_have: "added this comment" } },
    { id: "1", seq: 1, kind: "trigger", outcome: "pass", node_name: "Trigger" },
    { id: "4", seq: 4, kind: "set", outcome: "fail", node_name: "Say", reason: "no result", data: null },
  ]);
  assert.deepEqual(rows.map((r) => r.name), ["Say hello", "Say"], "the trigger and a passing output say nothing");
  assert.equal(rows[0].skipped, true);
  assert.equal(rows[0].text, "Would have added this comment");
  assert.equal(rows[1].text, "no result");
});

test("the status words and the address of the execution in the history", () => {
  assert.equal(m.statusLabel("done"), "Done");
  assert.equal(m.statusLabel("running"), "Running");
  assert.equal(m.historyUrl(12, "e 1"), "/artifacts/12/executions/e%201");
});
