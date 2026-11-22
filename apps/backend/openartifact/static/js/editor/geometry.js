/* Geometry of the graph canvas. Pure functions over plain node/edge objects as the API returns
 * them; what a kind of node looks like and may connect to comes from its view (node-types.js). */
import { HEADER, typeOf } from "./node-types.js";

export const PAD = 24; // space between a stage border and its actions
export const ACTION_GAP = 64; // space between neighbouring actions
export const TOP_LEVEL_GAP = 96; // space between a new node of the main line and its neighbour
export const STAGE_MIN = { width: 320, height: 220 };
export const EDGE_STYLES = { curved: "Curved", straight: "Straight", elbow: "Elbow" };

/** What a node is called on the canvas (a linked node carries the name of what it links to). */
export function displayName(node) {
  return typeOf(node).displayName(node);
}

/** Node size in world units. */
export function sizeOf(node) {
  return typeOf(node).size(node);
}

/** Top-left corner on the canvas; a node inside a stage is positioned relative to the stage's body. */
export function originOf(node, nodes) {
  if (!node.stage_id) return { x: node.x, y: node.y };
  const stage = nodes.get(node.stage_id);
  return { x: stage.x + node.x, y: stage.y + HEADER + node.y };
}

/** The node's rectangle on the canvas. */
export function boxOf(node, nodes) {
  return { ...originOf(node, nodes), ...sizeOf(node) };
}

/** Where a port sits on the canvas (`slot` picks one of a stage's three points per side). */
export function portPoint(node, port, nodes, slot = 0) {
  const origin = originOf(node, nodes);
  const local = typeOf(node).portLocal(node, port, slot);
  return { x: origin.x + local.x, y: origin.y + local.y };
}

/** May `source.sourcePort` feed `target.targetPort`? Mirrors the server's rules (node_types.py). */
export function canConnect(source, sourcePort, target, targetPort) {
  const from = typeOf(source);
  const to = typeOf(target);
  if (!from.outputs.some((p) => p.name === sourcePort) || !to.inputs.some((p) => p.name === targetPort)) return false;
  if (!from.isVisible(source, sourcePort) || !to.isVisible(target, targetPort)) return false;
  return from.canFeed(source, sourcePort, target, targetPort);
}

const CORNER = 12; // radius of rounded corners
const DETOUR = 28; // how far a routed edge keeps away from the nodes
const TIGHT = 48; // a forward connection with less room than this would bend too sharply

/**
 * The path of an edge in the given style. A connection that has to go back, or that has too little
 * room to bend, leaves to the right, runs below both nodes and comes in from the left instead of
 * cutting across them (rounded for curved and elbow, with sharp corners for straight).
 */
export function edgePath(from, to, fromBox, toBox, { routed = true, style = "curved" } = {}) {
  const dx = to.x - from.x;
  if (routed && dx < TIGHT) {
    const low = Math.max(fromBox.y + fromBox.height, toBox.y + toBox.height) + DETOUR;
    const points = [from, { x: from.x + DETOUR, y: from.y }, { x: from.x + DETOUR, y: low }, { x: to.x - DETOUR, y: low }, { x: to.x - DETOUR, y: to.y }, to];
    return polyline(points, style === "straight" ? 0 : CORNER);
  }
  if (style === "straight") return polyline([from, to], 0);
  if (style === "elbow") {
    const middle = from.x + dx / 2;
    return polyline([from, { x: middle, y: from.y }, { x: middle, y: to.y }, to], CORNER);
  }
  const reach = Math.min(Math.max(dx / 2, 48), 220);
  return `M ${from.x} ${from.y} C ${from.x + reach} ${from.y}, ${to.x - reach} ${to.y}, ${to.x} ${to.y}`;
}

/** A polyline whose inner corners are replaced by quadratic curves of the given radius. */
function polyline(points, radius) {
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const before = Math.min(radius, Math.hypot(b.x - a.x, b.y - a.y) / 2);
    const after = Math.min(radius, Math.hypot(c.x - b.x, c.y - b.y) / 2);
    const toward = (p, q, length) => {
      const size = Math.hypot(q.x - p.x, q.y - p.y) || 1;
      return { x: p.x + ((q.x - p.x) / size) * length, y: p.y + ((q.y - p.y) / size) * length };
    };
    const start = toward(b, a, before);
    const end = toward(b, c, after);
    d += ` L ${start.x} ${start.y} Q ${b.x} ${b.y} ${end.x} ${end.y}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

/** The actions inside a stage. */
export function actionsOf(stage, nodes) {
  return [...nodes.values()].filter((n) => n.stage_id === stage.id);
}

/**
 * Where a new stage (or timer) goes: right of the last node of the main line, or of the trigger.
 * `nodes` is the editor's Map of nodes.
 */
export function nextTopLevelPosition(nodes, kind) {
  const line = [...nodes.values()].filter((n) => typeOf(n).chain);
  const right = Math.max(...line.map((n) => n.x + sizeOf(n).width), 60);
  return { x: Math.round(right + TOP_LEVEL_GAP), y: kind === "stage" ? 40 : 172 };
}

/** Where a new action goes: flows run left to right, so right of the last action of its stage. */
export function nextActionPosition(stage, nodes) {
  const actions = actionsOf(stage, nodes);
  const x = actions.length ? Math.max(...actions.map((a) => a.x + sizeOf(a).width)) + ACTION_GAP : PAD;
  return { x, y: PAD * 2 };
}

/** The smallest stage size that still contains all its actions. */
export function fitStage(stage, actions) {
  let width = STAGE_MIN.width;
  let height = STAGE_MIN.height;
  for (const action of actions) {
    const size = sizeOf(action);
    width = Math.max(width, action.x + size.width + PAD);
    height = Math.max(height, HEADER + action.y + size.height + PAD);
  }
  return { width: Math.max(stage.width, width), height: Math.max(stage.height, height) };
}
