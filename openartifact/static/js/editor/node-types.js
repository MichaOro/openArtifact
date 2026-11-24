/* The kinds of nodes in the editor. The server describes each kind (GET /api/node-types, from its YAML manifest,
 * ADR-054): where it may be used, its ports, settings, menu place and how its card looks (`ui`). A view adds the behaviour
 * of the *kind of kind* (`behaviour`: plain, flow, stage, action, pipeline, output, tool): how it is drawn and connects. What
 * differs between kinds of one behaviour is data in the description, drawn by these views; there is no class per kind. A kind
 * may still get a view of its own with `registerView` (the way an extension would, ADR-014). */
import { stageChips } from "./guards.js";
import { icon } from "../components/icons.js";
import { request } from "../http.js";
import { renderCaption } from "./caption.js";
import { FUNCTIONS, agentNames, switchCaseUsed } from "./view-functions.js";
import { t } from "../i18n.js";

export { agentNames, switchCaseUsed };
export const HEADER = 44; // stage header height
export const FAILING_PORTS = ["error", "fail", "else"]; // their connections are drawn as failures
export const SLOTS = 3; // attachment points per side of a stage, top to bottom

/** Height of a stage's attachment point: the header, the middle and the bottom part. */
export function slotY(height, slot) {
  return [HEADER / 2, height / 2, height - HEADER / 2][slot];
}

const SLOT_EDGE = 8; // the lowest point keeps this far from the stage's bottom edge
export const PAD = 24; // space between a stage border and its actions
/** The highest an action can sit in a stage (body coordinates, below the header): the drag clamp stops there, a new action goes there, and the stage's top attachment point is level with its port. One number for all three. */
export const FIRST_ROW = PAD / 2;

/**
 * Heights of a stage's three attachment points on one side, top to bottom, from the stage's top. They depend on the
 * stage's height only, never on its actions: the first is level with the port of an action at the very top (FIRST_ROW: the highest
 * an action can sit and where a new one goes), the last with the port of an action dragged as low as it goes without the stage growing, the middle one
 * halfway. So a line from a point to an action in either place is straight, however the other actions sit. `side` is
 * "in" for the left edge (the inputs of the actions) and "out" for the right edge (their On Pass). Every point stays inside
 * the stage.
 */
export function slotHeights(height, side = "in") {
  const view = typeOf("action");
  if (!view) return [0, 1, 2].map((slot) => slotY(height, slot));
  const sample = { kind: "action", x: 0, y: 0 };
  const facing = (side === "in" ? view.inputs : view.outputs)[0]?.name;
  const port = facing ? view.portLocal(sample, facing).y : view.size(sample).height / 2;
  const clamp = (y) => Math.min(Math.max(y, HEADER / 2), height - SLOT_EDGE);
  const top = clamp(HEADER + FIRST_ROW + port);
  const bottom = clamp(Math.max(height - PAD - view.size(sample).height + port, top));
  return [top, (top + bottom) / 2, bottom];
}

export class NodeView {
  static kind = null;
  static size = { width: 160, height: 64 };
  static portLabels = false; // write the port names next to the ports
  static icon = null; // an icon of icons.html shown in the card

  /** @param {object} description what the server says about the kind */
  constructor(description) {
    Object.assign(this, description);
    this.ui = description.ui ?? {};
    const groupUsed = FUNCTIONS.group_used[this.ui.group_used_fn];
    if (groupUsed) this.groupUsed = (node, group) => groupUsed(node, group); // a kind that knows when a group of its dialog is in use
  }

  // ── looks ────────────────────────────────────────────────────────

  /** The card's size: a function the manifest names, its `ui.size`, or the behaviour's. */
  size(node) {
    const named = FUNCTIONS.size[this.ui.size_fn];
    if (named) return named(node, this);
    return this.ui.size ?? this.constructor.size;
  }

  displayName(node) {
    return node.definition_name ?? node.name;
  }

  /** The small line under the name: the manifest's template or function, else (null: none) the kind's label when the name differs. */
  caption(node) {
    const spec = this.ui.caption;
    if (spec?.template !== undefined) return renderCaption(spec.template, node);
    if (spec?.fn !== undefined) return FUNCTIONS.caption[spec.fn](node, this);
    return this.defaultCaption(node);
  }

  defaultCaption(node) {
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

  /** Every port of the kind (shown or not), with its direction for dragging. Inputs sit left and outputs
   * right unless the server gives a side (the Tools port of an agent at the bottom, a tool's port on top). */
  ports() {
    return [
      ...this.inputs.map((p) => ({ ...p, direction: "input", side: p.side ?? "left", slot: 0 })),
      ...this.outputs.map((p) => ({ ...p, direction: "output", side: p.side ?? "right", slot: 0 })),
    ];
  }

  /** Whether a port is there for this node: its manifest says when (a function, or a field of the node that must be set). */
  isVisible(node, port) {
    const when = [...this.inputs, ...this.outputs].find((p) => p.name === port)?.visible_when;
    if (!when) return true;
    return when.fn ? FUNCTIONS.visible[when.fn](node, port) : Boolean(node[when.node]);
  }

  /** Whether the name is written next to the port: the outcomes (On Pass, On Error ...), not the plain input / next. */
  labelled(port) {
    return (this.ui.port_labels ?? this.constructor.portLabels) && !["in", "out"].includes(port.name);
  }

  /** The name of a port; its manifest may take it from the node (a Switch shows the value of the case). */
  portLabel(port, node = null) {
    const own = [...this.inputs, ...this.outputs].find((p) => p.name === port);
    const fromNode = own?.label_from && node ? FUNCTIONS.label[own.label_from](node, port) : null;
    return fromNode ?? own?.label ?? port;
  }

  /** Where a port sits relative to the node's top-left corner: shown ports spread down each side. */
  portLocal(node, port) {
    const { width, height } = this.size(node);
    const own = [...this.inputs, ...this.outputs].find((p) => p.name === port);
    if (own?.side === "top" || own?.side === "bottom") return { x: width / 2, y: own.side === "top" ? 0 : height };
    const input = this.inputs.some((p) => p.name === port) && !this.outputs.some((p) => p.name === port);
    const side = (input ? this.inputs : this.outputs).filter((p) => this.isVisible(node, p.name) && !p.side);
    const index = Math.max(0, side.findIndex((p) => p.name === port));
    return { x: input ? 0 : width, y: (height * (index + 1)) / (side.length + 1) };
  }

  // ── rules (mirror node_types.py on the server, which has the last word) ─────────────────

  /** May `source.sourcePort` (a node of this kind) feed `target.targetPort`? */
  canFeed(source, sourcePort, target, targetPort) {
    if (target.id === source.id) return false;
    if (targetPort === "tools") return false; // only a tool attaches there (ToolView)
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
    if (this.ui.block === "agent") return [blocks.agent(node), blocks.actions(node, { remove: true })];
    return [blocks.settings(node), blocks.actions(node, { remove: !this.fixed })];
  }
}

/** A step that does work and ends in On Pass or On Fail, or branches: Code, HTTP, If, Switch, Agent, ... */
class FlowView extends NodeView {
  static size = { width: 250, height: 84 };
  static portLabels = true;

  subtitle() {
    return this.label;
  }

  /** A port that is not there (an unused Switch case) cannot feed anything. */
  canFeed(source, sourcePort, target, targetPort) {
    return this.isVisible(source, sourcePort) && super.canFeed(source, sourcePort, target, targetPort);
  }
}

class StageView extends NodeView {
  size(node) {
    return { width: node.width, height: node.height };
  }

  defaultCaption() {
    return this.label;
  }

  render(el, node, parts) {
    const header = document.createElement("header");
    header.className = "ge-stage__header";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "icon-button icon-button--sm ge-stage__add";
    add.dataset.stageAdd = "";
    add.setAttribute("aria-haspopup", "menu");
    add.setAttribute("aria-expanded", "false");
    add.setAttribute("aria-label", t("editor.node_types.add_to_stage"));
    add.title = t("editor.node_types.add_to_stage");
    add.append(icon("plus"));
    header.append(parts.caption, parts.name);
    const guards = stageChips.provider?.(node); // the shield chips of its guards (ADR-060), never nodes
    if (guards) header.append(guards);
    header.append(add);
    const body = document.createElement("div");
    body.className = "ge-stage__body";
    el.append(header, body);
  }

  /** A stage's start and end serve both sides, and each has three attachment points. */
  ports() {
    const ports = [];
    for (let slot = 0; slot < SLOTS; slot += 1) {
      ports.push({ name: "start", label: t("editor.node_types.start"), direction: "both", side: "left", slot });
      ports.push({ name: "end", label: t("editor.node_types.end"), direction: "both", side: "right", slot });
    }
    return ports;
  }

  /** The points follow the stage's height (`slotHeights`); `nodes` is accepted for the callers that pass it and not needed. */
  portLocal(node, port, slot = 0) {
    return { x: port === "start" ? 0 : node.width, y: slotHeights(node.height, port === "start" ? "in" : "out")[slot] };
  }

  canFeed(source, sourcePort, target, targetPort) {
    if (sourcePort === "start") return target.kind === "action" && target.stage_id === source.id;
    return super.canFeed(source, sourcePort, target, targetPort);
  }

  sections(node, blocks) {
    return [blocks.actions(node, { create: () => blocks.addAction(node), remove: true })];
  }
}

/** A shell in a stage that is linked to an action definition. */
class ActionView extends NodeView {
  defaultCaption(node) {
    return node.definition_id ? this.label : t("editor.node_types.empty_action");
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
    return [blocks.link(node, t("editor.node_types.definition"), t("editor.node_types.action_2"), t("editor.node_types.not_defined")), blocks.actions(node, blocks.linkActions(node))];
  }
}

/** A node of the main line that calls another pipeline. */
class PipelineNodeView extends NodeView {
  defaultCaption(node) {
    return node.definition_id ? this.label : t("editor.node_types.no_pipeline_chosen");
  }

  renamable() {
    return false; // named by the pipeline it calls
  }

  sections(node, blocks) {
    return [blocks.link(node, t("editor.node_types.calls"), t("common.pipeline"), t("editor.node_types.not_chosen")), blocks.actions(node, blocks.linkActions(node))];
  }
}

class OutputView extends NodeView {
  /** The connectors sit below the name, On Pass above On Fail. */
  portLocal(node, port) {
    return { x: 0, y: port === "fail" ? 84 : 60 };
  }
}

/** A tool of an agent (ADR-040): hangs below an Agent node, attached to its Tools port; no flow ports. */
class ToolView extends NodeView {
  static size = { width: 200, height: 64 };

  subtitle() {
    return this.label;
  }

  canFeed(source, sourcePort, target, targetPort) {
    return target.kind === "agent" && targetPort === "tools";
  }

  /** The name the model calls it by (empty: the node's name). */
  toolName(node) {
    return node.config?.tool_name || node.name;
  }
}

/** The view of each behaviour a manifest may name (the server's `switch` is drawn like any flow kind). */
const BEHAVIOUR_VIEWS = { plain: NodeView, flow: FlowView, switch: FlowView, stage: StageView, action: ActionView, pipeline: PipelineNodeView, output: OutputView, tool: ToolView };

const VIEWS = new Map();

/** Make a view class known for its kind: it replaces the view its behaviour would give (the way an extension adds one, ADR-014). */
export function registerView(View) {
  VIEWS.set(View.kind, View);
}

const TYPES = new Map();

/** The view class of a kind: its own, else its behaviour's; a kind with an icon gets it as a static of its class (the card reads it there). */
function viewClassFor(description) {
  const Base = VIEWS.get(description.kind) ?? BEHAVIOUR_VIEWS[description.behaviour] ?? NodeView;
  const glyph = description.ui?.icon;
  return glyph ? class extends Base { static icon = glyph; } : Base;
}

/** Load the kinds from the server and pair each with its view. */
export async function loadNodeTypes() {
  for (const description of await request("/api/node-types")) {
    const View = viewClassFor(description);
    TYPES.set(description.kind, new View(description));
  }
}

/** Remember the names of agents (the editor loads them once; the inspector whenever it lists them). */
export function rememberAgents(agents) {
  for (const agent of agents) agentNames.set(agent.id, agent.name);
}

/** The view of a node's kind. */
export function typeOf(nodeOrKind) {
  return TYPES.get(typeof nodeOrKind === "string" ? nodeOrKind : nodeOrKind.kind);
}

/**
 * Entries of the "+" menu that are no kinds (`placeholders` in graph/nodes/_menu.yaml, handed to the page by the server):
 * a place held for something that is coming. Choosing one creates nothing.
 */
let PLACEHOLDERS = [];

/** @param {{key: string, label: string, icon: string, group: string, group_index: number, order: number, scopes: string[], soon: boolean}[]} list */
export function setPlaceholders(list) {
  PLACEHOLDERS = Array.isArray(list) ? list : [];
}

/** A placeholder by its key (null when the server declares none of that name). */
export function placeholderOf(key) {
  return PLACEHOLDERS.find((p) => p.key === key) ?? null;
}

/** The placeholders offered in one editor ("pipeline" or "action"), shaped like kinds so the menu can group and search them. */
export function placeholdersIn(scope) {
  return PLACEHOLDERS.filter((p) => p.scopes.includes(scope)).map((p) => ({
    kind: p.key,
    label: p.label,
    icon: p.icon,
    menu_icon: p.icon,
    soon: p.soon,
    placeholder: true,
    menu: { group: p.group, group_index: p.group_index, order: p.order },
  }));
}

/** The kinds that may be added to a pipeline ("pipeline") or an action definition ("action"). */
export function addableIn(scope) {
  return [...TYPES.values()].filter((t) => t.addable && t.scopes.includes(scope));
}

/**
 * The kinds of the add menu in their clusters: the cluster and the place in it are the manifest's (`menu`); a kind that
 * has none lands in "More", last. Clusters without a kind are left out.
 * @param {{kind: string, label: string, menu?: {group: string, group_index: number, order: number}|null}[]} types
 * @returns {{group: string, types: {kind: string, label: string}[]}[]}
 */
export function groupAddable(types) {
  const clusters = new Map();
  for (const type of types) {
    const group = type.menu?.group ?? t("editor.node_types.more");
    const rank = type.menu ? type.menu.group_index : Number.MAX_SAFE_INTEGER;
    if (!clusters.has(group)) clusters.set(group, { group, rank, types: [] });
    clusters.get(group).types.push(type);
  }
  return [...clusters.values()]
    .sort((a, b) => a.rank - b.rank)
    .map(({ group, types: inGroup }) => ({ group, types: inGroup.sort((a, b) => (a.menu?.order ?? 0) - (b.menu?.order ?? 0)) }));
}

/**
 * The search of the add menu: the kinds whose name or kind contains the text (ignoring case), each with the cluster it
 * is in, in the order of the clusters. A cluster's name is not a search term: the clusters only help to find your way.
 * @returns {{kind: string, label: string, group: string}[]}
 */
export function searchAddable(types, query) {
  const wanted = query.trim().toLowerCase();
  return groupAddable(types)
    .flatMap(({ group, types: inGroup }) =>
      inGroup.map((t) => ({ kind: t.kind, label: t.label, group, menu_icon: t.menu_icon, ...(t.placeholder ? { placeholder: true, icon: t.icon, soon: t.soon } : {}) })),
    )
    .filter((t) => !wanted || t.label.toLowerCase().includes(wanted) || t.kind.toLowerCase().includes(wanted));
}
