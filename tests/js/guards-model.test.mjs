/* The pure part of the guard library (static/js/guards/model.js): the one line about a guard, "Used in N places", the
 * shield's plural tooltip that never says "active", what the "Add a guard" popup offers and what the editor saves. */
import assert from "node:assert/strict";
import { test } from "node:test";

const G = await import("../../openartifact/static/js/guards/model.js");

const SERVER_SCHEMA = {
  consequences: [{ key: "pause", available: true }],
  fields: [
    { key: "runs", kind: "count", options: [], operators: ["at_least"], units: [] },
    { key: "idle", kind: "duration", options: [], operators: ["at_least"], units: ["hours", "minutes", "seconds"] },
  ],
};
const SCHEMA = G.builderSchema(SERVER_SCHEMA);
const idle = { type: "group", mode: "all", items: [{ type: "condition", field: "idle", op: "at_least", value: 900 }] };

function guard(name, extra = {}) {
  return { id: name.toLowerCase(), name, description: "", scope_types: ["pipeline", "stage", "action"], attachments: [], used_by: 0, ...extra };
}

test("a guard is one line: its trigger and its condition in words", () => {
  const stall = { trigger: { type: "interval", every_seconds: 60, for_seconds: 300 }, when: idle };
  assert.equal(G.summaryLine(stall, SCHEMA), "Every 1 minute, held 5 minutes · Time without progress is at least 15 minutes");
  const round = { trigger: { type: "event", events: ["enter", "leave"] }, when: { type: "group", mode: "all", items: [] } };
  assert.equal(G.summaryLine(round, SCHEMA), "On entered, left · No condition (never fires)");
});

test("the use of a definition is counted in places, and only an unused one can be deleted", () => {
  assert.equal(G.usedText(0), "Not used yet");
  assert.equal(G.usedText(1), "Used in 1 place");
  assert.equal(G.usedText(3), "Used in 3 places");
  assert.equal(G.deleteBlocked(guard("A")), "");
  assert.equal(G.deleteBlocked(guard("A", { used_by: 2 })), "Detach it first: it is used in 2 places");
});

test("the shield says how many guards are configured, in the plural that fits, and never that they are active", () => {
  assert.equal(G.shieldText(1), "1 guard configured");
  assert.equal(G.shieldText(4), "4 guards configured");
  assert.doesNotMatch(G.shieldText(2), /active/i);
});

test("the popup offers what may watch the scope, is not attached there yet and matches the search", () => {
  const onStage = { id: "a1", scope_type: "stage", scope_id: "s1", pipeline_id: "p", enabled: true };
  const guards = [
    guard("Stall guard", { attachments: [onStage], used_by: 1 }),
    guard("Health guard", { scope_types: ["stage"], description: "an agent judges the rounds" }),
    guard("Action only", { scope_types: ["action"] }),
    guard("Runtime guard"),
  ];
  assert.deepEqual(G.attachable(guards, "stage", "s1").map((g) => g.name), ["Health guard", "Runtime guard"]);
  assert.deepEqual(G.attachable(guards, "stage", "s2").map((g) => g.name), ["Health guard", "Runtime guard", "Stall guard"]);
  assert.deepEqual(G.attachable(guards, "stage", "s2", "JUDGES").map((g) => g.name), ["Health guard"], "the description is searched too");
  assert.deepEqual(G.attachable(guards, "action", "x").map((g) => g.name), ["Action only", "Runtime guard", "Stall guard"]);
  assert.deepEqual(G.attachedTo(guards, "stage", "s1"), [{ attachment: onStage, guard: guards[0] }]);
  assert.deepEqual([...G.countsByScope(guards, "p")], [["stage|s1", 1]]);
  assert.equal(G.countsByScope(guards, "other").size, 0);
});

test("the editor saves the trigger of its kind only, the scopes in their order, and says what is missing", () => {
  const state = { ...G.blank("Mine"), scope_types: ["action", "stage"], trigger: { type: "interval", every_seconds: 60, events: ["enter"] } };
  assert.deepEqual(G.body(state).trigger, { type: "interval", every_seconds: 60, for_seconds: 0, cooldown_seconds: 0 });
  assert.deepEqual(G.body(state).scope_types, ["stage", "action"]);
  assert.equal(G.problem({ ...state, name: "  " }, SCHEMA), "Give the guard a name.");
  assert.equal(G.problem({ ...state, scope_types: [] }, SCHEMA), "Choose at least one kind of scope it can watch.");
  assert.equal(G.problem({ ...state, trigger: { type: "event", events: [] } }, SCHEMA), "Choose at least one event.");
  assert.equal(G.problem(state, SCHEMA), "");
});

const place = (id, scope_type, scope_id, extra = {}) => ({ id, scope_type, scope_id, graph_id: extra.graph_id ?? "p", enabled: true, ...extra });

test("the scopes of a pipeline and of an action definition are counted by the graph that holds them", () => {
  const guards = [
    guard("Stall", { attachments: [place("a1", "pipeline", "p"), place("a2", "action", "n1"), place("a3", "node", "code", { graph_id: "def", scope_name: "Summarise" })] }),
    guard("Round", { attachments: [place("a4", "definition", "def", { graph_id: "def" }), place("a5", "action", "n1")] }),
  ];
  assert.deepEqual([...G.countsByScope(guards, "p")], [["pipeline|p", 1], ["action|n1", 2]]);
  assert.deepEqual([...G.countsByScope(guards, "def")], [["node|code", 1], ["definition|def", 1]]);
  assert.equal(G.isGraphScope("pipeline") && G.isGraphScope("definition"), true);
  assert.equal(G.isGraphScope("stage") || G.isGraphScope("action") || G.isGraphScope("node"), false);
});

test("the guards inside an action are listed by name with what they watch, and an action without a definition has none", () => {
  const guards = [
    guard("Stall", { attachments: [place("a3", "node", "code", { graph_id: "def", scope_name: "Summarise" })] }),
    guard("Round", { attachments: [place("a4", "definition", "def", { graph_id: "def" }), place("a5", "action", "n1")] }),
  ];
  const inner = G.innerOf(guards, "def");
  assert.deepEqual(inner.map(({ guard: g, attachment }) => [g.name, attachment.scope_type]), [["Round", "definition"], ["Stall", "node"]]);
  assert.equal(G.innerScopeText(inner[0].attachment), "The whole action");
  assert.equal(G.innerScopeText(inner[1].attachment), "Node Summarise");
  assert.deepEqual(G.innerOf(guards, null), []);
  assert.deepEqual(G.innerOf(guards, "other"), []);
});

test("a node of an action is offered the guards that are not attached to it, and its inner guards count in the card's shield", () => {
  const all = ["pipeline", "stage", "action", "definition", "node"];
  const guards = [guard("Stall", { scope_types: all, attachments: [place("a3", "node", "code", { graph_id: "def" })] }), guard("Round", { scope_types: all }), guard("Stage only", { scope_types: ["stage"] })];
  assert.deepEqual(G.attachable(guards, "node", "code").map((g) => g.name), ["Round"]); // not the one that is there, not the one that may not watch a node
  assert.deepEqual(G.attachable(guards, "node", "other").map((g) => g.name), ["Round", "Stall"]);
  assert.equal(G.shieldCount(1, 2), 3);
  assert.equal(G.shieldText(G.shieldCount(0, 1)), "1 guard configured");
});
