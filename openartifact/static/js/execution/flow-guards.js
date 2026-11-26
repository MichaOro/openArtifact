/* The guards of an execution as the read-only flow shows them (ADR-060): where a guard watches (a stage, an action, a node) the
 * place carries the shield of the editor. What state it is in is decided here, without a DOM:
 *
 *   - **active** (green, pulsing): the execution is running, the place is being watched right now (the guards' bookkeeping
 *     says its scope is active) and at least one guard attached there is still switched on;
 *   - **idle** (grey): every other case: no guard switched on any more, the place is not running (yet, or any more), the run is over.
 *
 * The attached guards are those of the frozen run (the snapshot's switched-on attachments), `enabled` is whether each is still
 * switched on now (the engine checks that live). */
import { t, tn } from "../i18n.js";

const keyOf = (graphId, type, id) => `${graphId}|${type}|${id}`;

/** The guards by place: a Map of "graph|type|id" -> `[{id, name, enabled}]`. */
export function guardPlaces(flow) {
  const places = new Map();
  for (const guard of flow.attached_guards ?? []) {
    const key = keyOf(guard.graph_id, guard.scope_type, guard.scope_id);
    if (!places.has(key)) places.set(key, []);
    places.get(key).push({ id: guard.id, name: guard.name, enabled: guard.enabled !== false });
  }
  return places;
}

/** What the shield of a place says: `{count, active, state, names, fired}`; null when no guard watches the place. */
export function placeState(places, flow, graphId, types, id) {
  for (const type of types) {
    const guards = places.get(keyOf(graphId, type, id));
    if (!guards?.length) continue;
    const running = flow.execution?.status === "running";
    const scope = Object.values(flow.guards?.scopes ?? {}).find((s) => s.type === type && s.id === id);
    const watched = running && Boolean(scope?.active);
    const active = watched ? guards.filter((g) => g.enabled).length : 0;
    const fired = [...new Set((flow.guards?.firings ?? []).filter((f) => f.scope_type === type && f.scope_id === id).map((f) => f.guard))];
    return { count: guards.length, active, state: active > 0 ? "active" : "idle", names: guards.map((g) => g.name), fired };
  }
  return null;
}

/** The tooltip of a shield: "2 guards, 1 active", the names, and the guards that fired in this run. */
export function shieldTitle(state) {
  const lines = [tn("execution.flow_guards.summary", state.count, { count: state.count, active: state.active }), state.names.join(", ")];
  if (state.fired.length) lines.push(t("execution.flow_guards.fired", { names: state.fired.join(", ") }));
  return lines.join("\n");
}
