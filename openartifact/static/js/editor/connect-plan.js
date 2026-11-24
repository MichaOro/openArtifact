/* The plan of a line that is released on the empty canvas: the menu of what can be connected there, which port of the new
 * node takes the line, where the node lands and which connection it replaces. Pure functions over plain node/edge objects
 * (the DOM and the saving are connect-menu.js and the editor). The rules are the editor's own: `canConnectFrom`. */
import { HEADER, FAILING_PORTS, typeOf } from "./node-types.js";
import { canConnectFrom, clampInStage, displayName, nextToolPosition, portPoint } from "./geometry.js";

export const STRAIGHT_SNAP = 16; // world units: closer than this to the level of the dragged port the line is made straight

/** The ports a new node offers first, in this order, when several would fit (never the error output unless it is the only one). */
const PREFERRED = { source: ["in", "start"], target: ["pass", "out", "yes", "case_1", "end"] };

/** A stand-in for a node that does not exist yet: enough for the rules and for the geometry of its ports. */
export function sampleOf(kind, fields = {}) {
  return { id: "__new__", kind, name: "", x: 0, y: 0, config: {}, ...fields };
}

/** `source`: the dragged port gives the line (an output, or a stage's two-way point) and the new node takes it in; `target`: the dragged port is an input and the new node feeds it. */
export const roleOf = (origin) => (origin.direction === "input" ? "target" : "source");

/** The ports of a new node of this kind that may end the line, in the order they are tried. */
function fitting(origin, kind, stage) {
  const view = typeOf(kind);
  const sample = sampleOf(kind, kind === "action" && stage ? { stage_id: stage.id } : {}); // an action only follows an action of its own stage
  const role = roleOf(origin);
  const wanted = role === "source" ? ["input", "both"] : ["output", "both"];
  return view
    .ports()
    .filter((p) => wanted.includes(p.direction) && view.isVisible(sample, p.name))
    .filter((p) => canConnectFrom(origin, { node: sample, port: p.name, direction: p.direction }));
}

/** The port of a new node of `kind` that the line ends at (null when none fits). */
export function choosePort(origin, kind, stage = null) {
  const ok = fitting(origin, kind, stage);
  if (!ok.length) return null;
  const order = PREFERRED[roleOf(origin)];
  const preferred = order.map((name) => ok.find((p) => p.name === name)).find(Boolean);
  return preferred ?? ok.find((p) => !FAILING_PORTS.includes(p.name)) ?? ok[0];
}

/** The kinds the menu offers for the dragged port: those with a port that fits (clusters without one disappear on their own). */
export function candidates(origin, types, stage = null) {
  return types.filter((type) => choosePort(origin, type.kind, stage) !== null);
}

/**
 * The kinds that can be made at all where the line was released: in the pipeline editor an action inside a stage and the
 * kinds of the main line outside it; in the action editor the nodes of the "+" menu.
 */
export function kindsFor(scope, stage, addable) {
  if (scope === "pipeline" && stage) return [typeOf("action")];
  return addable;
}

/**
 * Where the new node goes and what it needs to be created: its connected port at the release point (the line is made
 * straight when that is close to the level of the dragged port), a tool below its agent, an action inside its stage
 * (relative to the stage, kept inside its inner border). `release` is a point of the canvas (world units).
 */
export function placement({ origin, kind, release, nodes, edges, stage }) {
  if (typeOf(kind).tool && origin.port === "tools") {
    const spot = nextToolPosition(nodes, edges, origin.node.id);
    if (spot) return { kind, x: spot.x, y: spot.y };
  }
  const port = choosePort(origin, kind, stage);
  const local = typeOf(kind).portLocal(sampleOf(kind), port.name, 0, nodes);
  let [x, y] = [release.x - local.x, release.y - local.y];
  const level = portPoint(origin.node, origin.port, nodes, origin.slot ?? 0).y;
  if (Math.abs(release.y - level) <= STRAIGHT_SNAP) y = level - local.y;
  if (kind === "action" && stage) {
    const inside = clampInStage(x - stage.x, y - stage.y - HEADER);
    return { kind, stage_id: stage.id, x: Math.round(inside.x), y: Math.round(inside.y) };
  }
  return { kind, x: Math.round(x), y: Math.round(y) };
}

/** The connection of the dragged port and the new node's port, stored from the output to the input whichever end was dragged. */
export function connectionFor(origin, created, port) {
  const slot = origin.slot ?? 0;
  if (roleOf(origin) === "source") {
    return { source_id: origin.node.id, source_port: origin.port, target_id: created.id, target_port: port, source_slot: slot, target_slot: 0 };
  }
  return { source_id: created.id, source_port: port, target_id: origin.node.id, target_port: origin.port, source_slot: 0, target_slot: slot };
}

/** What the new connection lets go: the one that already leaves the dragged output (an output has at most one); an input may be fed by several, they stay. */
export function replacedEdges(origin, edges, nodes) {
  if (roleOf(origin) !== "source") return [];
  return [...edges.values()]
    .filter((e) => e.source_id === origin.node.id && e.source_port === origin.port)
    .map((e) => ({ id: e.id, name: displayName(nodes.get(e.target_id) ?? origin.node) }));
}
