/* The canvas of the flow page: the editor's Canvas and node views, read-only, drawing one graph of the
 * frozen snapshot with the walk of one visit on it. What was walked is shown by classes and small
 * badges on the nodes and edges; never by colour alone (every state has its own icon and word, a node
 * that did not run is dashed as well as dimmed, a walked edge is thicker and numbered). */
import { icon } from "../components/icons.js";
import { shieldButton, updateShield } from "../components/guard-shield.js";
import { Canvas } from "../editor/canvas.js";
import { typeOf } from "../editor/node-types.js";
import { addBubbles, FAILING_PORTS } from "./flow-bubbles.js";
import { placeState, shieldTitle } from "./flow-guards.js";
import { nameOf } from "./visit-model.js";
import { CARD_ORDER, cardIcon, placeCardIcon, removeCardIcon } from "../components/card-icons.js";
import { skipMarker, skipText } from "../components/skip-marker.js";
import { plural, t } from "../i18n.js";

/** state -> [word for people, word of the aria label, icon] */
export const STATES = {
  pass: [t("credentials.credentials_page.passed"), "passed", "check"],
  fail: [t("common.failed"), "failed", "x"],
  running: [t("common.running"), "running", "clock"],
  stopped: [t("execution.flow_view.stopped_here"), t("execution.flow_view.stopped_here_2"), "stop"],
  skipped: [t("execution.flow_view.skipped"), "skipped", "chevrons-right"],
  "not-run": [t("execution.flow_view.not_run"), t("execution.flow_view.not_run_2"), null],
};
const READABLE = 0.4; // fitting a wide flow does not shrink it below this: it is panned instead
const STATE_CLASSES = Object.keys(STATES).map((state) => `ef-state-${state}`);

export class FlowView {
  /**
   * @param {object} options
   * @param {HTMLElement} options.viewport the [data-viewport] element
   * @param {(node: object) => void} options.onActivate a node was clicked or Enter was pressed on it
   * @param {() => void} options.onClear the background was clicked
   * @param {(zoom: number) => void} options.onZoom
   */
  constructor({ viewport, onActivate, onClear, onZoom }) {
    this.viewport = viewport;
    this.nodes = new Map();
    this.edges = new Map();
    this.walk = null;
    this.live = false;
    this.guards = null; // {flow, places}: the guards of the run, so a place that guards watch carries the shield
    this.graphId = null;
    this.canvas = new Canvas({
      viewport,
      nodes: this.nodes,
      edges: this.edges,
      readOnly: true,
      minZoom: 0.1,
      handlers: {
        onSelect: () => onClear(),
        onOpen: (node) => onActivate(node),
        onZoom,
        onNodeDrawn: (node, el) => this.#decorateNode(node, el),
        onEdgeDrawn: (edge, group) => this.#decorateEdge(edge, group),
      },
    });
    viewport.classList.add("ef-viewport");
  }

  /**
   * Draw a graph with the walk of one visit.
   * @param {object} graph a graph of the flow response
   * @param {{states: Map, edgeOrder: Map}} walk what FlowModel.describe() says
   * @param {{fit?: boolean, live?: boolean}} options fit: show all of it (a different graph); live: the run is still
   *   going, so bubbles flow along what was walked (a finished run only shows where it went, without motion)
   */
  show(graph, walk, { fit = false, live = false } = {}) {
    this.walk = walk;
    this.live = live;
    this.graphId = graph.id;
    this.nodes.clear();
    this.edges.clear();
    // left to right: this is the order the nodes are reached with the keyboard
    for (const node of [...graph.nodes].sort((a, b) => a.x - b.x || a.y - b.y)) this.nodes.set(node.id, node);
    for (const edge of graph.edges) this.edges.set(edge.id, edge);
    this.canvas.selection = this.canvas.selection && this.nodes.has(this.canvas.selection.id) ? this.canvas.selection : null;
    this.canvas.sync();
    if (fit) this.fit();
  }

  /** The guards of the run (see flow-guards.js); the next draw puts the shields on the places they watch. */
  setGuards(guards) {
    this.guards = guards;
  }

  select(nodeId) {
    this.canvas.select(nodeId && this.nodes.has(nodeId) ? { type: "node", id: nodeId } : null);
    if (nodeId && this.nodes.has(nodeId)) this.canvas.reveal(this.nodes.get(nodeId));
  }

  zoomBy = (factor) => this.canvas.zoomBy(factor);
  fit = () => this.canvas.fit({ floor: READABLE });

  #decorateNode(node, el) {
    const info = this.walk?.states.get(node.id) ?? { state: "not-run", passes: 0 };
    const [, word, glyph] = STATES[info.state];
    el.classList.remove(...STATE_CLASSES);
    el.classList.add(`ef-state-${info.state}`);
    el.classList.toggle("is-dim", info.state === "not-run" || info.state === "skipped");
    el.classList.toggle("has-child", info.passes > 0);
    el.classList.toggle("ef-tool", Boolean(info.tool)); // a tool node an agent used: green, red or working, not dimmed

    let badge = el.querySelector(":scope > .ef-badge");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "ef-badge";
      badge.setAttribute("aria-hidden", "true");
      el.append(badge);
    }
    badge.hidden = !glyph;
    badge.replaceChildren(...(glyph ? [icon(glyph)] : []));
    if (info.passes > 1) badge.append(`×${info.passes}`);
    if (info.tool && info.calls > 1) badge.append(`×${info.calls}`);
    badge.dataset.state = info.state;
    badge.title = word;

    const calls = info.tool ? toolCallsText(info) : null;
    const facts = [word, calls, info.step?.exit_code != null ? t("execution.flow_panel.exit_code_exit_code", { exit_code: info.step.exit_code }) : null, info.passes > 1 ? `${info.passes} passes` : null, info.passes ? t("execution.flow_panel.enter_opens") : null];
    el.setAttribute("aria-label", `${typeOf(node).label}: ${nameOf(node)}, ${facts.filter(Boolean).join(", ")}`);
    el.title = info.state === "not-run" ? t("execution.flow_view.not_run") : calls ?? "";
    this.#decorateSkip(node, el, info);
    this.#decorateGuard(node, el);
  }

  /** A node a dry run skipped is drawn like one that ran (it was passed in the flow: dimmed means not reached) and carries the skip marker in the
   * card's icon list, with what it would have done as its tooltip; a node that handed over a mock has no such marker (ADR-086 addendum 3). */
  #decorateSkip(node, el, info) {
    const text = node.kind === "stage" ? null : skipText(info.step);
    const marker = cardIcon(el, "skipped");
    if (!text) {
      if (marker) removeCardIcon(el, "skipped");
      return;
    }
    if (marker?.getAttribute("aria-label") === text) return;
    placeCardIcon(el, "skipped", CARD_ORDER.skipped, skipMarker(info.step));
  }

  /** The shield of the editor, read-only, where a guard watches: green and pulsing while one is watching now, else grey. */
  #decorateGuard(node, el) {
    const host = node.kind === "stage" ? el.querySelector(".ge-stage__header") : el;
    if (!host) return;
    let shield = host.querySelector(":scope > [data-guard-shield]");
    const state = this.guards ? placeState(this.guards.places, this.guards.flow, this.graphId, node.kind === "stage" || node.kind === "action" ? [node.kind, "node"] : ["node"], node.id) : null;
    if (!state) {
      shield?.remove();
      return;
    }
    if (!shield) {
      shield = shieldButton(state.count, nameOf(node), { readOnly: true });
      if (node.kind !== "stage") shield.classList.add("gd-shield--node");
      host.append(shield);
    }
    updateShield(shield, state.count, nameOf(node));
    shield.title = shieldTitle(state);
    shield.dataset.state = state.state;
  }

  #decorateEdge(edge, group) {
    if (edge.target_port === "tools") return this.#decorateToolEdge(edge, group);
    const order = this.walk?.edgeOrder.get(edge.id);
    group.classList.toggle("is-walked", order !== undefined);
    group.classList.toggle("is-idle", order === undefined);
    if (order === undefined) return;
    const line = group.querySelector(".ge-edge__line");
    const middle = line.getPointAtLength(line.getTotalLength() / 2);
    const mark = document.createElementNS("http://www.w3.org/2000/svg", "g");
    mark.setAttribute("class", "ef-edge__order");
    mark.setAttribute("transform", `translate(${middle.x} ${middle.y})`);
    const disc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    disc.setAttribute("r", "9");
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.textContent = String(order);
    mark.append(disc, text);
    group.append(mark);
    if (this.live) addBubbles(group, line, FAILING_PORTS.includes(edge.source_port));
  }

  /** The dashed line of a tool: faint while the tool was not used, then in the colour of what its calls came to; while a call is
   * in progress the bubbles run along it from the agent to the tool. */
  #decorateToolEdge(edge, group) {
    const use = this.walk?.states.get(edge.source_id);
    const state = use?.tool ? use.state : null;
    for (const name of ["pass", "fail", "running"]) group.classList.toggle(`is-tool-${name}`, state === name);
    group.classList.toggle("is-walked", state !== null);
    group.classList.toggle("is-idle", state === null);
    if (state !== "running" || !this.live) return;
    const line = group.querySelector(".ge-edge__line");
    addBubbles(group, line, false, { reverse: true }); // the agent asks the tool: from the agent down to it
  }
}

/** "9 calls" or "9 calls, 1 failed": what the node of a tool says about what was asked of it. */
function toolCallsText(info) {
  const calls = plural("execution.flow_view.tool_calls", info.calls);
  return info.errors > 0 ? t("execution.flow_view.tool_calls_failed", { calls, errors: info.errors }) : calls;
}
