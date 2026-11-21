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

export const OUTPUTS = { trigger: ["out"], stage: ["out", "entry"], action: ["pass", "error"], complete: [] };
export const INPUTS = { trigger: [], stage: ["in", "exit"], action: ["in"], complete: ["in"] };

export const PORT_LABELS = {
  out: "Next",
  entry: "First action",
  pass: "On Pass",
  error: "On Error",
  in: "Input",
  exit: "Stage end",
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

/** Where a port sits on the canvas. */
export function portPoint(node, port, nodes) {
  const { x, y } = originOf(node, nodes);
  const { width, height } = sizeOf(node);
  const body = y + HEADER + (height - HEADER) / 2;
  switch (`${node.kind}:${port}`) {
    case "stage:in":
      return { x, y: y + HEADER / 2 };
    case "stage:out":
      return { x: x + width, y: y + HEADER / 2 };
    case "stage:entry":
      return { x, y: body };
    case "stage:exit":
      return { x: x + width, y: body };
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
  if (source.kind === "stage" && sourcePort === "entry") return target.kind === "action" && target.stage_id === source.id;
  if (source.kind === "action") {
    if (target.kind === "action") return target.stage_id === source.stage_id;
    return target.kind === "stage" && targetPort === "exit" && target.id === source.stage_id;
  }
  if (target.kind === "action" || (target.kind === "stage" && targetPort === "exit")) return false;
  if (target.id === source.id) return false;
  return !(source.kind === "trigger" && target.kind === "complete");
}

/** A smooth curve leaving the source to the right and entering the target from the left. */
export function curve(from, to) {
  const reach = Math.min(Math.max(Math.abs(to.x - from.x) / 2, 48), 220);
  return `M ${from.x} ${from.y} C ${from.x + reach} ${from.y}, ${to.x - reach} ${to.y}, ${to.x} ${to.y}`;
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
