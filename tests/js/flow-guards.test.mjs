/* What the shield of the read-only flow says (execution/flow-guards.js): active only while the run is running, the place is
 * watched and a guard there is still switched on. */
import assert from "node:assert/strict";
import { test } from "node:test";

const { guardPlaces, placeState, shieldTitle } = await import("../../openartifact/static/js/execution/flow-guards.js");

const guard = (over = {}) => ({ id: "a1", guard_id: "g1", name: "Stall guard", scope_type: "stage", scope_id: "s1", graph_id: "p1", enabled: true, ...over });
const flow = (over = {}) => ({
  execution: { status: "running" },
  attached_guards: [guard()],
  guards: { scopes: { "stage:s1": { type: "stage", id: "s1", active: true } }, firings: [] },
  ...over,
});
const state = (f, graph = "p1", types = ["stage", "node"], id = "s1") => placeState(guardPlaces(f), f, graph, types, id);

test("a place with a guard switched on, running and watched is active", () => {
  assert.deepEqual(state(flow()), { count: 1, active: 1, state: "active", names: ["Stall guard"], fired: [] });
});

test("it is idle when the run is over, the place is not watched, or every guard there is switched off now", () => {
  assert.equal(state(flow({ execution: { status: "done" } })).state, "idle");
  assert.equal(state(flow({ guards: { scopes: { "stage:s1": { type: "stage", id: "s1", active: false } }, firings: [] } })).state, "idle");
  assert.equal(state(flow({ guards: {} })).state, "idle", "an older run without bookkeeping");
  assert.equal(state(flow({ attached_guards: [guard({ enabled: false })] })).state, "idle");
});

test("only the guards switched on count as active; the others still count as there", () => {
  const f = flow({ attached_guards: [guard(), guard({ id: "a2", name: "Other", enabled: false })] });
  const s = state(f);
  assert.deepEqual([s.count, s.active, s.state], [2, 1, "active"]);
});

test("a place nothing watches has no shield, and a graph or a type of another place does not match", () => {
  assert.equal(state(flow({ attached_guards: [] })), null);
  assert.equal(state(flow(), "other-graph"), null);
  assert.equal(state(flow(), "p1", ["action"]), null);
  assert.equal(state(flow(), "p1", ["stage"], "s2"), null);
});

test("a node place is found through the node type, and the guards that fired are named once", () => {
  const f = flow({
    attached_guards: [guard({ scope_type: "node", scope_id: "n1", graph_id: "d1" })],
    guards: { scopes: { "node:n1": { type: "node", id: "n1", active: true } }, firings: [{ scope_type: "node", scope_id: "n1", guard: "Stall guard" }, { scope_type: "node", scope_id: "n1", guard: "Stall guard" }] },
  });
  const s = state(f, "d1", ["action", "node"], "n1");
  assert.equal(s.state, "active");
  assert.deepEqual(s.fired, ["Stall guard"]);
  assert.ok(shieldTitle(s).includes("Stall guard"));
});
