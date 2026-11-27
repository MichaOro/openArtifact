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

test("the address of the execution in the history and of all dry runs", () => {
  assert.equal(m.historyUrl(12, "e 1"), "/artifacts/12/executions/e%201");
  assert.equal(m.allDryRunsUrl, "/executions?dry_run=only");
});

test("the tab lists the newest dry runs of this graph on the card, five at most", () => {
  const run = (n, extra = {}) => ({ id: `e${n}`, dry_run: true, pipeline_id: "p1", started_at: `2026-11-27T08:0${n}:00Z`, status: "done", ...extra });
  const all = [run(1), run(2), run(3), run(4), run(5), run(6), run(7, { dry_run: false }), run(8, { pipeline_id: "other" })];
  assert.deepEqual(m.listedRuns(all, "p1").map((e) => e.id), ["e6", "e5", "e4", "e3", "e2"], "no real run, no other pipeline, newest first");
  assert.equal(m.listedRuns(all, null).length, 5, "without a pipeline (an action nobody places yet) the pipeline is not asked");
  assert.deepEqual(m.listedRuns(undefined, "p1"), []);
});

test("the running dry run is the one the Start button becomes a Stop for", () => {
  assert.equal(m.runningRun([{ id: "a", status: "done" }, { id: "b", status: "running" }]).id, "b");
  assert.equal(m.runningRun([{ id: "a", status: "stopped" }]), null);
  assert.equal(m.runningRun(undefined), null);
});

test("the + Add menu offers the optional items that are not on the form yet, the test card first and for now alone", () => {
  assert.deepEqual(m.OPTIONAL_ITEMS.map((i) => i.key), ["card"]);
  assert.deepEqual(m.availableItems(new Set()).map((i) => i.key), ["card"]);
  assert.deepEqual(m.availableItems(new Set(["card"])), []);
  for (const item of m.OPTIONAL_ITEMS) assert.ok(item.labelKey && item.icon, "every item names its label and its icon");
});
