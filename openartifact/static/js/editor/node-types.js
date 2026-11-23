/* The kinds of nodes in the editor, as classes. The server describes each kind (GET /api/node-types:
 * where it may be used, whether it is fixed or can be added, its ports, settings and what it links
 * to); a view class adds how it looks and which inspector building blocks it shows. `NodeView` has the
 * common behaviour, a kind overrides only what differs. Kinds are registered with `registerView`, the
 * way an extension would add one (ADR-014). */
import { overridesOf } from "../agents/model.js";
import { icon } from "../components/icons.js";
import { request } from "../http.js";
import { fieldNames } from "./reference-completion.js";

export const HEADER = 44; // stage header height
export const FAILING_PORTS = ["error", "fail", "else"]; // their connections are drawn as failures
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

  /** Every port of the kind (shown or not), with its direction for dragging. Inputs sit left and outputs
   * right unless the server gives a side (the Tools port of an agent at the bottom, a tool's port on top). */
  ports() {
    return [
      ...this.inputs.map((p) => ({ ...p, direction: "input", side: p.side ?? "left", slot: 0 })),
      ...this.outputs.map((p) => ({ ...p, direction: "output", side: p.side ?? "right", slot: 0 })),
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

  /** The name of a port; a kind may take it from the node (a Switch shows the value of the case). */
  portLabel(port, node = null) {
    return [...this.inputs, ...this.outputs].find((p) => p.name === port)?.label ?? port;
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

/** A step that does work and ends in On Pass or On Fail (Code, HTTP); If and Switch have their own outputs. */
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

/** Operators that look at the value only (mirror of UNARY_OPERATORS, graph/node_types.py). */
const UNARY = ["is empty", "is not empty", "is true", "is false"];
const OPERATOR_SIGNS = { "not equals": "≠", "greater than": ">", "less than": "<", "greater or equal": "≥", "less or equal": "≤" };

/** Whether a Switch case is in use: a value, or an operator that needs none (mirror of switch_case_used). */
export function switchCaseUsed(config, port) {
  const operator = config?.[`case_operator_${port.slice(5)}`] ?? "equals";
  return UNARY.includes(operator) || (config?.[port] ?? "").trim() !== "";
}

/** Longest text a card shows of a condition. */
const SHORT = 40;
const short = (text) => (text.length > SHORT ? `${text.slice(0, SHORT)}…` : text);

class IfView extends ExecutionView {
  static kind = "if";
  static icon = "if";
  static size = { width: 250, height: 104 };

  /** The first condition and how many more there are. */
  caption(node) {
    const config = node.config ?? {};
    const used = [1, 2, 3, 4, 5].filter((n) => (config[`left_${n}`] ?? "").trim() !== "");
    if (!used.length) return "no condition yet";
    const n = used[0];
    const operator = config[`operator_${n}`] ?? "equals";
    const unary = ["is empty", "is not empty", "is true", "is false"].includes(operator);
    const first = short(`${config[`left_${n}`]} ${operator}${unary ? "" : ` ${config[`right_${n}`] ?? ""}`}`.trim());
    return used.length > 1 ? `${first} +${used.length - 1} more` : first;
  }
}

class SwitchView extends ExecutionView {
  static kind = "switch";
  static icon = "switch";

  #usedCases(node) {
    return [1, 2, 3, 4, 5, 6].filter((n) => switchCaseUsed(node.config, `case_${n}`));
  }

  /** The value and the number of cases. */
  caption(node) {
    const value = (node.config?.value ?? "").trim();
    const cases = this.#usedCases(node).length;
    return `${value ? short(value) : "no value yet"} · ${cases} ${cases === 1 ? "case" : "cases"}`;
  }

  /** The ports of unused cases are not there; Else always is. */
  isVisible(node, port) {
    return !port.startsWith("case_") || switchCaseUsed(node.config, port);
  }

  /** A case group of the inspector is open when the case is in use. */
  groupUsed(node, group) {
    const n = group.match(/^Case (\d)$/)?.[1];
    return n ? switchCaseUsed(node.config, `case_${n}`) : null;
  }

  /** The card grows with its visible outputs. */
  size(node) {
    const visible = this.outputs.filter((p) => this.isVisible(node, p.name)).length;
    return { width: 250, height: Math.max(84, 26 * visible + 20) };
  }

  /** A case is shown by its condition as the user wrote it: the value, or the operator before it when it is
   * not "equals" ("> 10", "contains urgent", "is empty"). */
  portLabel(port, node = null) {
    if (!port.startsWith("case_") || !node) return super.portLabel(port, node);
    const value = node.config?.[port]?.trim() ?? "";
    const operator = node.config?.[`case_operator_${port.slice(5)}`] ?? "equals";
    const text = operator === "equals" ? value : `${OPERATOR_SIGNS[operator] ?? operator} ${UNARY.includes(operator) ? "" : value}`.trim();
    return text ? short(text) : super.portLabel(port, node);
  }

  canFeed(source, sourcePort, target, targetPort) {
    return this.isVisible(source, sourcePort) && super.canFeed(source, sourcePort, target, targetPort);
  }
}

class SetView extends ExecutionView {
  static kind = "set";
  static icon = "pencil";

  /** The names of the fields it sets. */
  caption(node) {
    const names = fieldNames(node.config?.fields);
    if (!names.length) return "no field yet";
    return short(names.join(", "));
  }
}

class AgentView extends ExecutionView {
  static kind = "agent";
  static icon = "agent";

  /** The agent's name and how many settings the node overrides. */
  caption(node) {
    const id = node.config?.agent_id;
    if (!id) return "no agent yet";
    const own = overridesOf(node.config).length;
    // an execution's frozen node carries its agent; the editor knows the names of the list
    return `${node.agent?.name ?? agentNames.get(id) ?? "agent"}${own ? ` · ${own} override${own === 1 ? "" : "s"}` : ""}`;
  }

  sections(node, blocks) {
    return [blocks.agent(node), blocks.actions(node, { remove: true })];
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

class McpToolView extends ToolView {
  static kind = "mcp_tool";
  static icon = "plug";

  caption(node) {
    return hostAndPath(node.config?.url ?? "") || "no endpoint yet";
  }
}

class HttpToolView extends ToolView {
  static kind = "http_tool";
  static icon = "http";

  caption(node) {
    const { method = "GET", url = "" } = node.config ?? {};
    return `${method} ${hostAndPath(url) || "no URL yet"}`;
  }
}

class CodeToolView extends ToolView {
  static kind = "code_tool";
  static icon = "code";

  caption(node) {
    return `${node.config?.language ?? "python"} · ${this.toolName(node)}`;
  }
}

/** The first line of a query that says something, cut for a card (a query may hold names; it never holds a secret). */
function queryLine(config) {
  const first = (config?.query ?? "").split("\n").find((line) => line.trim() !== "");
  return first ? short(first.trim()) : "no query yet";
}

class GithubView extends ExecutionView {
  static kind = "github";
  static icon = "github";

  /** The operation and the repository; Create comment says when it is switched off (it would fail). */
  caption(node) {
    const { operation = "Get repository", repository = "", allow_comments = false } = node.config ?? {};
    const off = operation === "Create comment" && !allow_comments ? " (off)" : "";
    return `${operation}${off} · ${repository.trim() ? short(repository.trim()) : "no repository yet"}`;
  }
}

class PostgresView extends ExecutionView {
  static kind = "postgres";
  static icon = "database";

  /** The query; "changes" in front when the node may change data. */
  caption(node) {
    return `${node.config?.allow_write ? "changes · " : ""}${queryLine(node.config)}`;
  }
}

class PostgresToolView extends ToolView {
  static kind = "postgres_tool";
  static icon = "database";

  caption(node) {
    return `${this.toolName(node)} · ${node.config?.allow_write ? "changes · " : ""}${queryLine(node.config)}`;
  }
}

/** `https://user:pw@example.org/hook?token=x#y` as `example.org/hook`. */
function hostAndPath(url) {
  const plain = () => url.split(/[?#]/)[0].replace(/^[^/]*@/, "");
  try {
    const { host, pathname } = new URL(url);
    // `user:pw@host/path` without a scheme parses as an opaque URL with no host: never show the userinfo
    // the path as written: a tool's {parameter} stays readable
    return host ? `${host}${pathname === "/" ? "" : decodeURI(pathname)}` : plain();
  } catch {
    return plain();
  }
}

const VIEWS = new Map();

/** Make a view class known for its kind (built-in kinds use this as an extension would). */
export function registerView(View) {
  VIEWS.set(View.kind, View);
}

[TriggerView, CompleteView, StageView, ActionView, PipelineNodeView, TimerView, OutputView, CodeView, HttpView, IfView, SwitchView, AgentView, SetView, GithubView, PostgresView, McpToolView, HttpToolView, CodeToolView, PostgresToolView].forEach(registerView);

const TYPES = new Map();

/** Load the kinds from the server and pair each with its view (the base view if it has none). */
export async function loadNodeTypes() {
  for (const description of await request("/api/node-types")) {
    const View = VIEWS.get(description.kind) ?? NodeView;
    TYPES.set(description.kind, new View(description));
  }
}

/** The names of the agents by id, for the caption of an agent node (filled by `rememberAgents`). */
export const agentNames = new Map();

/** Remember the names of agents (the editor loads them once; the inspector whenever it lists them). */
export function rememberAgents(agents) {
  for (const agent of agents) agentNames.set(agent.id, agent.name);
}

/** The view of a node's kind. */
export function typeOf(nodeOrKind) {
  return TYPES.get(typeof nodeOrKind === "string" ? nodeOrKind : nodeOrKind.kind);
}

/** The kinds that may be added to a pipeline ("pipeline") or an action definition ("action"). */
export function addableIn(scope) {
  return [...TYPES.values()].filter((t) => t.addable && t.scopes.includes(scope));
}

/** The clusters of the add menu, in order, with the kinds in each (a kind nobody listed lands in "More"). */
const ADD_GROUPS = [
  ["Structure", ["stage", "pipeline"]],
  ["AI", ["agent"]],
  ["Agent tools", ["mcp_tool", "http_tool", "code_tool", "postgres_tool"]],
  ["Apps and data", ["github", "postgres"]],
  ["Core", ["code", "http"]],
  ["Data", ["set"]],
  ["Flow", ["if", "switch", "timer"]],
];

/**
 * The kinds of the add menu in their clusters; `query` narrows them to those whose name, kind or cluster contains it
 * (ignoring case); clusters left empty are dropped.
 * @param {{kind: string, label: string}[]} types
 * @returns {{group: string, types: {kind: string, label: string}[]}[]}
 */
export function groupAddable(types, query = "") {
  const wanted = query.trim().toLowerCase();
  const listed = new Set(ADD_GROUPS.flatMap(([, kinds]) => kinds));
  const clusters = [...ADD_GROUPS, ["More", types.filter((t) => !listed.has(t.kind)).map((t) => t.kind)]];
  return clusters
    .map(([group, kinds]) => ({
      group,
      types: kinds
        .map((kind) => types.find((t) => t.kind === kind))
        .filter((t) => t && (!wanted || [t.label, t.kind, group].some((text) => text.toLowerCase().includes(wanted)))),
    }))
    .filter((cluster) => cluster.types.length);
}
