/* The kinds of nodes in the editor, as classes. The server describes each kind (GET /api/node-types:
 * where it may be used, whether it is fixed or can be added, its ports, settings and what it links
 * to); a view class adds how it looks and which inspector building blocks it shows. `NodeView` has the
 * common behaviour, a kind overrides only what differs. Kinds are registered with `registerView`, the
 * way an extension would add one (ADR-014). */
import { icon } from "../components/icons.js";
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
  static icon = null; // an icon of icons.html shown in the card

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

  /** The line under the title in the inspector. */
  subtitle(node) {
    return this.caption(node) ?? this.label;
  }

  /** Fill the node element; the canvas adds the ports. */
  render(el, node, parts) {
    const text = document.createElement("div");
    text.className = "ge-node__text";
    text.append(parts.name, parts.caption);
    if (this.constructor.icon) el.append(icon(this.constructor.icon, "ge-node__icon"));
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

  /** Whether the name is written next to the port: the outcomes (On Pass, On Error ...), not the plain input / next. */
  labelled(port) {
    return this.constructor.portLabels && !["in", "out"].includes(port.name);
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
    header.className = "ge-stage__header";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "ge-stage__add";
    add.dataset.addAction = "";
    add.textContent = "+ Action";
    header.append(parts.caption, parts.name, add);
    const body = document.createElement("div");
    body.className = "ge-stage__body";
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

/** A step that does work and ends in On Pass or On Fail (the Code and HTTP nodes). */
class ExecutionView extends NodeView {
  static size = { width: 250, height: 84 };
  static portLabels = true;

  subtitle() {
    return this.label;
  }
}

class CodeView extends ExecutionView {
  static kind = "code";
  static icon = "code";

  /** Language and first line of the code. */
  caption(node) {
    const first = (node.config?.code ?? "").split("\n").find((line) => line.trim() !== "");
    return `${node.config?.language ?? "sh"} · ${first?.trim() ?? "no code yet"}`;
  }
}

class HttpView extends ExecutionView {
  static kind = "http";
  static icon = "http";

  /** Method, host and path; the query string (it may carry a token) is never shown. */
  caption(node) {
    const { method = "GET", url = "" } = node.config ?? {};
    return `${method} ${hostAndPath(url) || "no URL yet"}`;
  }
}

/** `https://user:pw@example.org/hook?token=x#y` as `example.org/hook`. */
function hostAndPath(url) {
  const plain = () => url.split(/[?#]/)[0].replace(/^[^/]*@/, "");
  try {
    const { host, pathname } = new URL(url);
    // `user:pw@host/path` without a scheme parses as an opaque URL with no host: never show the userinfo
    return host ? `${host}${pathname === "/" ? "" : pathname}` : plain();
  } catch {
    return plain();
  }
}

const VIEWS = new Map();

/** Make a view class known for its kind (built-in kinds use this as an extension would). */
export function registerView(View) {
  VIEWS.set(View.kind, View);
}

[TriggerView, CompleteView, StageView, ActionView, PipelineNodeView, TimerView, OutputView, CodeView, HttpView].forEach(registerView);

const TYPES = new Map();

/** Load the kinds from the server and pair each with its view (the base view if it has none). */
export async function loadNodeTypes() {
  for (const description of await request("/api/node-types")) {
    const View = VIEWS.get(description.kind) ?? NodeView;
    TYPES.set(description.kind, new View(description));
  }
}

/** The view of a node's kind. */
export function typeOf(nodeOrKind) {
  return TYPES.get(typeof nodeOrKind === "string" ? nodeOrKind : nodeOrKind.kind);
}

/** The kinds that may be added to a pipeline ("pipeline") or an action definition ("action"). */
export function addableIn(scope) {
  return [...TYPES.values()].filter((t) => t.addable && t.scopes.includes(scope));
}
