import assert from "node:assert/strict";
import { test } from "node:test";

const { planSettings, groupsOf, isSet, optionLabel } = await import("../../openartifact/static/js/editor/settings-plan.js");

const s = (key, extra = {}) => ({ key, label: key, type: "text", default: null, stored_in: "config", section: "definition", level: "core", inherits: null, ...extra });
const node = (config = {}) => ({ id: "n", kind: "http", config });

test("a setting is set when the node stores a value for it; a column setting always is", () => {
  assert.equal(isSet(node({ a: "x" }), s("a")), true);
  assert.equal(isSet(node({ a: null }), s("a")), false);
  assert.equal(isSet(node({}), s("a")), false);
  assert.equal(isSet({ seconds: 5 }, s("seconds", { stored_in: "column" })), true);
});

test("a stored default is no configuration, except where a parent supplies the value", () => {
  const timeout = s("timeout", { type: "integer", default: 30 });
  assert.equal(isSet(node({ timeout: 30 }), timeout), false, "a new node stores the defaults of its settings");
  assert.equal(isSet(node({ timeout: 45 }), timeout), true);
  assert.equal(isSet(node({ secrets: "" }), s("secrets", { default: "" })), false);
  assert.equal(isSet(node({ secrets: "API_KEY" }), s("secrets", { default: "" })), true);
  assert.equal(isSet(node({ temperature: 0.2 }), s("temperature", { inherits: "agent", default: null })), true, "an override equal to the agent's value is still an override");
});

test("core settings are shown, optional ones only once set, the rest is offered, advanced ones are folded", () => {
  const settings = [
    s("url"),
    s("headers", { level: "optional" }),
    s("body", { level: "optional" }),
    s("timeout", { section: "behaviour", level: "optional" }),
    s("status", { section: "behaviour", level: "advanced" }),
    s("on_failure", { section: "behaviour" }),
  ];
  const plan = planSettings(settings, node({ headers: "A: b" }));
  const [definition, behaviour] = plan.sections;
  assert.deepEqual(definition.core.map((x) => x.key), ["url"]);
  assert.deepEqual(definition.shown.map((x) => x.key), ["headers"], "a configured optional setting is always visible");
  assert.deepEqual(definition.available.map((x) => x.key), ["body"]);
  assert.deepEqual(behaviour.core.map((x) => x.key), ["on_failure"]);
  assert.deepEqual(behaviour.available.map((x) => x.key), ["timeout"]);
  assert.deepEqual(behaviour.advanced.settings.map((x) => x.key), ["status"]);
  assert.equal(behaviour.advanced.open, false);
  assert.equal(plan.columns, 2);
});

test("an advanced setting that is set opens its disclosure", () => {
  const settings = [s("url"), s("status", { section: "behaviour", level: "advanced" })];
  assert.equal(planSettings(settings, node({ status: "200" })).sections[1].advanced.open, true);
  assert.equal(planSettings(settings, node({})).sections[1].advanced.open, false);
});

test("a node without behaviour settings has one column and no empty section", () => {
  const plan = planSettings([s("value"), s("case_1")], node());
  assert.equal(plan.columns, 1);
  assert.deepEqual(plan.sections.map((x) => x.id), ["definition"], "an empty section is not part of the plan");
});

test("a node whose only settings are behaviour ones also has one column", () => {
  const plan = planSettings([s("on_failure", { section: "behaviour" })], node());
  assert.equal(plan.columns, 1);
  assert.deepEqual(plan.sections.map((x) => x.id), ["behaviour"]);
});

test("skipped keys are left out (the agent block draws them itself)", () => {
  const plan = planSettings([s("agent_id"), s("inputs"), s("user_prompt", { inherits: "agent" })], node(), { skip: ["agent_id", "inputs"] });
  assert.deepEqual(plan.sections[0].core.map((x) => x.key), ["user_prompt"]);
});

test("a node of an inherited setting is overridden when it stores a value, and optional inherited ones wait in the menu", () => {
  const settings = [s("temperature", { section: "behaviour", level: "optional", inherits: "agent" }), s("retries", { section: "behaviour", level: "optional", inherits: "agent" })];
  const plan = planSettings(settings, node({ retries: 1 }));
  assert.deepEqual(plan.sections[0].shown.map((x) => x.key), ["retries"]);
  assert.deepEqual(plan.sections[0].available.map((x) => x.key), ["temperature"]);
});

test("settings of one group stay together in the order they were declared", () => {
  const list = [s("a", { group: "Model" }), s("b", { group: "Model" }), s("c"), s("d", { group: "Limits" })];
  assert.deepEqual(groupsOf(list).map((g) => [g.group, g.settings.map((x) => x.key)]), [["Model", ["a", "b"]], [null, ["c"]], ["Limits", ["d"]]]);
});

test("the menu names an optional setting with what applies while it is not set", () => {
  assert.equal(optionLabel(s("t", { label: "Timeout (s)", default: 30 })), "Timeout (s) · default 30");
  assert.equal(optionLabel(s("t", { label: "Temperature", inherits: "agent" }), "0.2"), "Temperature · Agent: 0.2");
  assert.equal(optionLabel(s("t", { label: "Headers" })), "Headers");
});
