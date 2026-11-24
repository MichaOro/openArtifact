/* Geometry of the graph canvas. Pure functions over plain node/edge objects as the API returns
 * them; what a kind of node looks like and may connect to comes from its view (node-types.js). */
import { FIRST_ROW, HEADER, PAD, slotHeights, typeOf } from "./node-types.js";
import { t } from "../i18n.js";

export { PAD }; // space between a stage border and its actions
export const ACTION_GAP = 64; // space between neighbouring actions
export const TOP_LEVEL_GAP = 96; // space between a new node of the main line and its neighbour
export const TOOL_GAP = 120; // space between an agent and the tools hanging below it
export const STAGE_MIN = { width: 320, height: 220 };
export const EDGE_STYLES = { curved: t("editor.geometry.curved"), straight: t("editor.geometry.straight"), elbow: t("editor.geometry.elbow") };

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
  const local = typeOf(node).portLocal(node, port, slot, nodes);
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

/**
 * May a connection that was pressed at `start` end at `other`? Pressed at an output (or a stage's two-way point) it feeds
 * `other`, pressed at an input it is fed by `other`: the rule is `canConnect` with the two ends in their own roles, so a
 * connection reads the same whichever end it was drawn from. Each end is {node, port, direction}.
 */
export function canConnectFrom(start, other) {
  if (start.direction === "input") return other.direction !== "input" && canConnect(other.node, other.port, start.node, start.port);
  return other.direction !== "output" && canConnect(start.node, start.port, other.node, other.port);
}

const CORNER = 12; // radius of rounded corners
const DETOUR = 28; // how far a routed edge keeps away from the nodes
const TIGHT = 48; // a forward connection with less room than this would bend too sharply

/**
 * The path of an edge in the given style. A connection that has to go back, or that has too little
 * room to bend, leaves to the right, runs below both nodes and comes in from the left instead of
 * cutting across them (rounded for curved and elbow, with sharp corners for straight).
 */
export function edgePath(from, to, fromBox, toBox, { routed = true, style = "curved", attachment = false } = {}) {
  if (attachment) return attachmentPath(from, to);
  const dx = to.x - from.x;
  const level = Math.abs(to.y - from.y) < 1; // a straight run needs no room to bend: it is drawn as it is
  if (routed && dx < TIGHT && !(dx > 0 && level)) {
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

/** A tool's attachment: from the top of the tool up to the bottom of the agent, whatever the style. */
function attachmentPath(from, to) {
  const reach = Math.min(Math.max(Math.abs(from.y - to.y) / 2, 32), 160);
  return `M ${from.x} ${from.y} C ${from.x} ${from.y - reach}, ${to.x} ${to.y + reach}, ${to.x} ${to.y}`;
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

/**
 * Where a new tool goes (ADR-040): below the agent `selectedId` names (or the last agent), right of the
 * tools already attached to it; `null` when there is no agent. `agentId` is the agent to attach it to.
 */
export function nextToolPosition(nodes, edges, selectedId) {
  const agents = [...nodes.values()].filter((n) => n.kind === "agent");
  const agent = nodes.get(selectedId)?.kind === "agent" ? nodes.get(selectedId) : agents[agents.length - 1];
  if (!agent) return null;
  const tools = [...edges.values()].filter((e) => e.target_id === agent.id && e.target_port === "tools").map((e) => nodes.get(e.source_id)).filter(Boolean);
  const x = tools.length ? Math.max(...tools.map((t) => t.x + sizeOf(t).width)) + ACTION_GAP / 2 : agent.x;
  return { agentId: agent.id, x, y: agent.y + sizeOf(agent).height + TOOL_GAP };
}

/** Where a new action goes: flows run left to right, so right of the last action of its stage. */
export function nextActionPosition(stage, nodes) {
  const actions = actionsOf(stage, nodes);
  const x = actions.length ? Math.max(...actions.map((a) => a.x + sizeOf(a).width)) + ACTION_GAP : PAD;
  return { x, y: FIRST_ROW };
}

/** The least a stage may measure: the smallest size that still holds all its actions (and never below STAGE_MIN). */
export function minStageSize(actions) {
  let width = STAGE_MIN.width;
  let height = STAGE_MIN.height;
  for (const action of actions) {
    const size = sizeOf(action);
    width = Math.max(width, action.x + size.width + PAD);
    height = Math.max(height, HEADER + action.y + size.height + PAD);
  }
  return { width, height };
}

/** A stage grows to hold its actions and never shrinks by itself; only a resize makes it smaller. */
export function fitStage(stage, actions) {
  const least = minStageSize(actions);
  return { width: Math.max(stage.width, least.width), height: Math.max(stage.height, least.height) };
}

/**
 * Where a node dragged by its port heights should settle so that a connection runs straight: `pairs` are
 * `{ own, other }` heights of one of its ports and the port it is connected to. The nearest pair within `threshold`
 * wins; the result is how far to move the node and the height that is then shared, or null when nothing is near.
 */
export function snapY(pairs, threshold) {
  let best = null;
  for (const { own, other } of pairs) {
    const delta = other - own;
    if (Math.abs(delta) <= threshold && (!best || Math.abs(delta) < Math.abs(best.delta))) best = { delta, y: other };
  }
  return best;
}

/**
 * The heights an action (or any node of a stage) can settle on so that a line to its stage's points is straight: its input
 * level with each of the stage's three points on the left edge, its first output level with each on the right edge. Each
 * entry is `{ own, other, from, to }` as `snapY` takes it (`from` and `to` are where the guide line starts and ends).
 */
export function slotPairs(node, nodes) {
  const stage = node.stage_id ? nodes.get(node.stage_id) : null;
  if (!stage) return [];
  const view = typeOf(node);
  const pairs = [];
  for (const [side, ports, edge] of [["in", view.inputs, "start"], ["out", view.outputs, "end"]]) {
    const port = ports.find((p) => !p.side && view.isVisible(node, p.name));
    if (!port) continue;
    const mine = portPoint(node, port.name, nodes);
    const heights = slotHeights(stage.height, side);
    heights.forEach((y) => pairs.push({ own: mine.y, other: stage.y + y, from: mine.x, to: edge === "start" ? stage.x : stage.x + stage.width }));
  }
  return pairs;
}
