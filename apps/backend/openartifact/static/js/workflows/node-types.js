/* The kinds of nodes in the editor, as classes. The server describes each kind (GET /api/node-types:
 * where it may be used, whether it is fixed or can be added, its ports, settings and what it links
 * to); a view class adds how it looks and which inspector building blocks it shows. `NodeView` has the
 * common behaviour, a kind overrides only what differs. Kinds are registered with `registerView`, the
 * way an extension would add one (ADR-014). */
import { request } from "../http.js";

export const HEADER = 44; // stage header height
export const SLOTS = 3; // attachment points per side of a stage, top to bottom

/** Height of a stage's attachment point: the header, the middle and the bottom part. */
export function slotY(height, slot) {
  return [HEADER / 2, height / 2, height - HEADER / 2][slot];
}

export class NodeView {
  static kind = null;
  static size = { width: 160, height: 64 };
  static portLabels = false; // write the port names next to the ports

  /** @param {object} description what the server says about the kind */
  constructor(description) {
    Object.assign(this, description);
  }

  // ── looks ────────────────────────────────────────────────────────

  size() {
    return this.constructor.size;
  }

  displayName(node) {
    return node.definition_name ?? node.name;
  }

  /** The small line under the name (null: none, e.g. when it would only repeat the name). */
  caption(node) {
    return this.displayName(node) === this.label ? null : this.label;
  }

  /** Fill the node element; the canvas adds the ports. */
  render(el, node, parts) {
    const text = document.createElement("div");
    text.className = "wf-node__text";
    text.append(parts.name, parts.caption);
    el.append(text);
  }

  // ── ports ────────────────────────────────────────────────────────

  /** Every port of the kind (shown or not), with its direction for dragging. */
  ports() {
    return [
      ...this.inputs.map((p) => ({ ...p, direction: "input", side: "left", slot: 0 })),
      ...this.outputs.map((p) => ({ ...p, direction: "output", side: "right", slot: 0 })),
    ];
  }

  /** Whether a port is there for this node (an action without On Fail has no Error output). */
  isVisible(node, port) {
    return true;
  }

  portLabel(port) {
    return [...this.inputs, ...this.outputs].find((p) => p.name === port)?.label ?? port;
  }

  /** Where a port sits relative to the node's top-left corner: shown ports spread down each side. */
  portLocal(node, port) {
    const { width, height } = this.size(node);
    const input = this.inputs.some((p) => p.name === port) && !this.outputs.some((p) => p.name === port);
    const side = (input ? this.inputs : this.outputs).filter((p) => this.isVisible(node, p.name));
    const index = Math.max(0, side.findIndex((p) => p.name === port));
    return { x: input ? 0 : width, y: (height * (index + 1)) / (side.length + 1) };
  }

  // ── rules (mirror node_types.py on the server, which has the last word) ─────────────────

  /** May `source.sourcePort` (a node of this kind) feed `target.targetPort`? */
  canFeed(source, sourcePort, target, targetPort) {
    if (target.id === source.id) return false;
    if (target.kind === "action") return false;
    return !(target.kind === "stage" && targetPort !== "start");
  }

  // ── inspector ────────────────────────────────────────────────────

  /** Whether the user may rename the node in place. */
  renamable() {
    return true;
  }

  /** What the inspector shows below the title, as building blocks (see inspector.js). */
  sections(node, blocks) {
    return [blocks.settings(node), blocks.actions(node, { remove: !this.fixed })];
  }
}

class TriggerView extends NodeView {
  static kind = "trigger";
}

class CompleteView extends NodeView {
  static kind = "complete";
  static size = { width: 160, height: 56 };
}

class StageView extends NodeView {
  static kind = "stage";

  size(node) {
    return { width: node.width, height: node.height };
  }

  caption() {
    return this.label;
  }

  render(el, node, parts) {
    const header = document.createElement("header");
    header.className = "wf-stage__header";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "wf-stage__add";
    add.dataset.addAction = "";
    add.textContent = "+ Action";
    header.append(parts.caption, parts.name, add);
    const body = document.createElement("div");
    body.className = "wf-stage__body";
    el.append(header, body);
  }

  /** A stage's start and end serve both sides, and each has three attachment points. */
  ports() {
    const ports = [];
    for (let slot = 0; slot < SLOTS; slot += 1) {
      ports.push({ name: "start", label: "Start", direction: "both", side: "left", slot });
      ports.push({ name: "end", label: "End", direction: "both", side: "right", slot });
    }
    return ports;
  }

  portLocal(node, port, slot = 0) {
    return { x: port === "start" ? 0 : node.width, y: slotY(node.height, slot) };
  }

  canFeed(source, sourcePort, target, targetPort) {
    if (sourcePort === "start") return target.kind === "action" && target.stage_id === source.id;
    return super.canFeed(source, sourcePort, target, targetPort);
  }

  sections(node, blocks) {
    return [blocks.actions(node, { create: () => blocks.addAction(node), remove: true })];
  }
}

class ActionView extends NodeView {
  static kind = "action";
  static size = { width: 190, height: 68 };
  static portLabels = true;

  caption(node) {
    return node.definition_id ? this.label : "Empty action";
  }

  isVisible(node, port) {
    return port !== "error" || node.definition_fail_enabled !== false; // its definition has no On Fail
  }

  canFeed(source, sourcePort, target, targetPort) {
    if (target.kind === "action") return target.stage_id === source.stage_id;
    return target.kind === "stage" && targetPort === "end" && target.id === source.stage_id;
  }

  renamable() {
    return false; // named by its action definition
  }

  sections(node, blocks) {
    return [blocks.link(node, "Definition", "Action", "Not defined"), blocks.actions(node, blocks.linkActions(node))];
  }
}

class PipelineNodeView extends NodeView {
  static kind = "pipeline";
  static size = { width: 200, height: 64 };

  caption(node) {
    return node.definition_id ? this.label : "No pipeline chosen";
  }

  renamable() {
    return false; // named by the pipeline it calls
  }

  sections(node, blocks) {
    return [blocks.link(node, "Calls", "Pipeline", "Not chosen"), blocks.actions(node, blocks.linkActions(node))];
  }
}

class TimerView extends NodeView {
  static kind = "timer";

  caption(node) {
    return `${node.seconds} s`; // what a timer waits for is always worth showing
  }
}

class OutputView extends NodeView {
  static kind = "output";
  static size = { width: 250, height: 104 };
  static portLabels = true;

  isVisible(node, port) {
    return port !== "fail" || node.fail_enabled;
  }

  /** The connectors sit below the name, On Pass above On Fail. */
  portLocal(node, port) {
    return { x: 0, y: port === "fail" ? 84 : 60 };
  }
}

const VIEWS = new Map();

/** Make a view class known for its kind (built-in kinds use this as an extension would). */
export function registerView(View) {
  VIEWS.set(View.kind, View);
}

[TriggerView, CompleteView, StageView, ActionView, PipelineNodeView, TimerView, OutputView].forEach(registerView);

const TYPES = new Map();

/** Load the kinds from the server and pair each with its view (the base view if it has none). */
export async function loadNodeTypes() {
  for (const description of await request("/api/workflows/node-types")) {
    const View = VIEWS.get(description.kind) ?? NodeView;
    TYPES.set(description.kind, new View(description));
  }
}

/** The view of a node's kind. */
export function typeOf(nodeOrKind) {
  return TYPES.get(typeof nodeOrKind === "string" ? nodeOrKind : nodeOrKind.kind);
}

/** The kinds that may be added to a pipeline ("workflow") or an action definition ("action"). */
export function addableIn(scope) {
  return [...TYPES.values()].filter((t) => t.addable && t.scopes.includes(scope));
}
