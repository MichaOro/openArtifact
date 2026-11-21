/* Geometry and connection rules of the workflow canvas. Pure functions over plain node/edge
 * objects as the API returns them. The server (workflow/rules.py) is the authority on what may be
 * connected; canConnect() only mirrors it so the editor can offer valid targets. */

export const HEADER = 44; // stage header height
export const PAD = 24; // space between a stage border and its actions
export const ACTION_GAP = 64; // space between neighbouring actions
export const TOP_LEVEL_GAP = 96; // space between a new trigger/stage/complete node and its neighbour
export const SIZE = {
  trigger: { width: 160, height: 64 },
  action: { width: 190, height: 68 },
  complete: { width: 160, height: 56 },
};
export const STAGE_MIN = { width: 320, height: 220 };

// A stage has one start and one end, each serving both sides (see workflow/rules.py).
export const OUTPUTS = { trigger: ["out"], stage: ["start", "end"], action: ["pass", "error"], complete: [] };
export const INPUTS = { trigger: [], stage: ["start", "end"], action: ["in"], complete: ["in"] };

export const PORT_LABELS = {
  out: "Next",
  start: "First action",
  end: "Next",
  pass: "On Pass",
  error: "On Error",
  in: "Input",
};

/** Node size in world units (stages carry their own). */
export function sizeOf(node) {
  return node.kind === "stage" ? { width: node.width, height: node.height } : SIZE[node.kind];
}

/** Top-left corner on the canvas; an action's position is relative to its stage's body. */
export function originOf(node, nodes) {
  if (node.kind !== "action") return { x: node.x, y: node.y };
  const stage = nodes.get(node.stage_id);
  return { x: stage.x + node.x, y: stage.y + HEADER + node.y };
}

/** The node's rectangle on the canvas. */
export function boxOf(node, nodes) {
  return { ...originOf(node, nodes), ...sizeOf(node) };
}

/** Where a port sits on the canvas. */
export function portPoint(node, port, nodes) {
  const { x, y } = originOf(node, nodes);
  const { width, height } = sizeOf(node);
  switch (`${node.kind}:${port}`) {
    case "stage:start":
      return { x, y: y + HEADER / 2 };
    case "stage:end":
      return { x: x + width, y: y + HEADER / 2 };
    case "action:pass":
      return { x: x + width, y: y + 24 };
    case "action:error":
      return { x: x + width, y: y + 48 };
    default: // inputs of actions and complete nodes sit left; a trigger's output sits right
      return port === "out" ? { x: x + width, y: y + height / 2 } : { x, y: y + height / 2 };
  }
}

/** May `source.sourcePort` feed `target.targetPort`? Mirrors workflow/rules.py. */
export function canConnect(source, sourcePort, target, targetPort) {
  if (!OUTPUTS[source.kind].includes(sourcePort) || !INPUTS[target.kind].includes(targetPort)) return false;
  if (source.kind === "stage" && sourcePort === "start") return target.kind === "action" && target.stage_id === source.id;
  if (source.kind === "action") {
    if (target.kind === "action") return target.stage_id === source.stage_id;
    return target.kind === "stage" && targetPort === "end" && target.id === source.stage_id;
  }
  if (target.kind === "action") return false;
  if (target.kind === "stage" && (targetPort !== "start" || target.id === source.id)) return false;
  return !(source.kind === "trigger" && target.kind === "complete");
}

const CORNER = 12; // radius of the rounded corners of routed edges
const DETOUR = 28; // how far a routed edge keeps away from the nodes

/**
 * The path of an edge. Forward connections are smooth curves; a connection that has to go back
 * (a loop into the node's own input, or to a node further left) leaves to the right, runs below both
 * nodes and comes in from the left, with rounded corners, instead of cutting across the nodes.
 */
export function edgePath(from, to, fromBox, toBox, { routed = true } = {}) {
  if (!routed || to.x - from.x >= 8) {
    const reach = Math.min(Math.max((to.x - from.x) / 2, 48), 220);
    return `M ${from.x} ${from.y} C ${from.x + reach} ${from.y}, ${to.x - reach} ${to.y}, ${to.x} ${to.y}`;
  }
  const low = Math.max(fromBox.y + fromBox.height, toBox.y + toBox.height) + DETOUR;
  return rounded([from, { x: from.x + DETOUR, y: from.y }, { x: from.x + DETOUR, y: low }, { x: to.x - DETOUR, y: low }, { x: to.x - DETOUR, y: to.y }, to]);
}

/** A polyline with each inner corner replaced by a quadratic curve. */
function rounded(points) {
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const before = Math.min(CORNER, Math.hypot(b.x - a.x, b.y - a.y) / 2);
    const after = Math.min(CORNER, Math.hypot(c.x - b.x, c.y - b.y) / 2);
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

/** The smallest stage size that still contains all its actions. */
export function fitStage(stage, actions) {
  let width = STAGE_MIN.width;
  let height = STAGE_MIN.height;
  for (const action of actions) {
    width = Math.max(width, action.x + SIZE.action.width + PAD);
    height = Math.max(height, HEADER + action.y + SIZE.action.height + PAD);
  }
  return { width: Math.max(stage.width, width), height: Math.max(stage.height, height) };
}
