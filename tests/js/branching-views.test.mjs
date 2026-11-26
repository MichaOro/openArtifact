import assert from "node:assert/strict";
import { before, test } from "node:test";
import { installDocument, loadTypes } from "./support.mjs";

const JS = "../../openartifact/static/js/editor/";
const { loadNodeTypes, typeOf, addableIn, switchCaseUsed } = await import(`${JS}node-types.js`);

before(async () => {
  installDocument(["code", "http", "if", "switch", "pencil"]);
  await loadTypes(loadNodeTypes);
});

const node = (kind, config = {}) => ({ id: `${kind}-1`, kind, name: kind, x: 0, y: 0, config });

test("If and Switch come after HTTP in the menu of an action", () => {
  const kinds = addableIn("action").map((t) => t.kind);
  assert.deepEqual(kinds.slice(kinds.indexOf("http")), ["http", "if", "switch", "agent", "set", "github", "postgres", "sqlite", "mcp_tool", "github_tool", "openartifact_tool", "http_tool", "code_tool", "postgres_tool", "sqlite_tool", "artifact", "note"]);
});

test("the If card shows its first condition and how many more there are", () => {
  const view = typeOf("if");
  assert.equal(view.caption(node("if")), "no condition yet");
  assert.equal(view.caption(node("if", { left_1: "${var.p}", operator_1: "equals", right_1: "high" })), "${var.p} equals high");
  assert.equal(view.caption(node("if", { left_2: "${var.n}", operator_2: "is empty", right_2: "ignored" })), "${var.n} is empty");
  const three = node("if", { left_1: "a", operator_1: "contains", right_1: "b", left_3: "c", left_5: "d" });
  assert.equal(view.caption(three), "a contains b +2 more");
  const long = view.caption(node("if", { left_1: "x".repeat(80), operator_1: "is true" }));
  assert.ok(long.length <= 41 && long.endsWith("…"));
});

test("the If node has Yes, No and Else outputs, all written next to the ports", () => {
  const view = typeOf("if");
  assert.deepEqual(view.outputs.map((p) => view.portLabel(p.name, node("if"))), ["Yes", "No", "Else"]);
  assert.equal(view.labelled({ name: "else" }), true);
  assert.equal(view.isVisible(node("if"), "else"), true);
});

test("the Switch shows case values as port labels and hides the ports of empty cases", () => {
  const view = typeOf("switch");
  const gold = node("switch", { value: "${var.tier}", case_1: "silver", case_2: " gold ", case_4: "  " });
  assert.equal(view.portLabel("case_1", gold), "silver");
  assert.equal(view.portLabel("case_2", gold), "gold");
  assert.equal(view.portLabel("case_3", gold), "Case 3", "an unused case keeps its default name");
  assert.deepEqual(view.outputs.filter((p) => view.isVisible(gold, p.name)).map((p) => p.name), ["case_1", "case_2", "else"]);
  assert.equal(view.caption(gold), "${var.tier} · 2 cases");
  assert.equal(view.caption(node("switch")), "no value yet · 0 cases");
  assert.equal(view.caption(node("switch", { value: "v", case_1: "a" })), "v · 1 case");
});

test("the Switch card grows with its visible outputs and no edge may start at a hidden case", () => {
  const view = typeOf("switch");
  assert.equal(view.size(node("switch")).height, 84);
  const full = node("switch", Object.fromEntries([1, 2, 3, 4, 5, 6].map((n) => [`case_${n}`, `c${n}`])));
  assert.equal(view.size(full).height, 26 * 7 + 20);
  const target = { id: "out-1", kind: "output" };
  assert.equal(view.canFeed(full, "case_6", target, "pass"), true);
  assert.equal(view.canFeed(node("switch"), "case_6", target, "pass"), false);
  assert.equal(view.canFeed(node("switch"), "else", target, "pass"), true);
});

test("a Switch case is used with a value or with an operator that needs none, like the server says", () => {
  assert.equal(switchCaseUsed({ case_1: "x" }, "case_1"), true);
  assert.equal(switchCaseUsed({ case_1: "  " }, "case_1"), false);
  assert.equal(switchCaseUsed({}, "case_1"), false);
  assert.equal(switchCaseUsed({ case_operator_2: "is empty" }, "case_2"), true);
  assert.equal(switchCaseUsed({ case_operator_2: "contains" }, "case_2"), false);
});

test("a Switch case shows its operator before the value unless it is equals", () => {
  const view = typeOf("switch");
  const rules = node("switch", {
    value: "${var.score}",
    case_1: "90",
    case_operator_1: "greater or equal",
    case_2: "urgent",
    case_operator_2: "contains",
    case_operator_3: "is empty",
    case_4: "gold",
  });
  assert.deepEqual([1, 2, 3, 4].map((n) => view.portLabel(`case_${n}`, rules)), ["≥ 90", "contains urgent", "is empty", "gold"]);
  assert.deepEqual(view.outputs.filter((p) => view.isVisible(rules, p.name)).map((p) => p.name), ["case_1", "case_2", "case_3", "case_4", "else"]);
  assert.equal(view.groupUsed(rules, "Case 3"), true);
  assert.equal(view.groupUsed(rules, "Case 5"), false);
  assert.equal(view.groupUsed(rules, "Something else"), null);
  const target = { id: "out-1", kind: "output" };
  assert.equal(view.canFeed(rules, "case_3", target, "pass"), true);
});

test("an Edit Fields card names the fields it sets", () => {
  const view = typeOf("set");
  assert.equal(view.caption(node("set")), "no field yet");
  assert.equal(view.caption(node("set", { fields: "priority = high\nvar.score = ${var.x}\nBad = 1\nno equals" })), "priority, score");
  assert.deepEqual(view.outputs.map((p) => p.name), ["pass", "fail"]);
});
