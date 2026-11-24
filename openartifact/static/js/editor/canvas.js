/* The graph canvas: renders nodes (HTML) and edges (SVG) inside a pannable, zoomable world and
 * turns pointer input into callbacks. It owns no data: nodes/edges are the editor's Maps.
 * With `readOnly` (the flow view of an execution) nodes do not move, ports do not connect, nothing
 * is deleted and edges cannot be picked: only panning, zooming and the notifications remain.
 *
 *  - drag a node to move it (an action stays inside its stage, which grows as needed);
 *  - drag from a port to a port that fits to connect (from an output to an input, or the other way round);
 *  - editor: the right button drags the view; the left button selects (a click, or a frame drawn on the background that
 *    takes every node it touches; Shift adds) and moves the selected nodes together; wheel or the zoom buttons zoom;
 *  - read-only: dragging the background with the left button pans;
 *  - click a node or an edge to select it. */
import { EDGE_STYLES, actionsOf, clampInStage, boxOf, displayName, canConnectFrom, edgePath, fitStage, minStageSize, originOf, portPoint, sizeOf, slotPairs, snapY } from "./geometry.js";
import { icon } from "../components/icons.js";
import { FAILING_PORTS, HEADER, typeOf } from "./node-types.js";
import { t } from "../i18n.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const DRAG_THRESHOLD = 4;
const SNAP_DISTANCE = 8; // screen pixels within which a dragged node settles level with a connected port
const RESIZE_STEP = 10; // a key press on a resize handle changes the stage by this much (Shift: four times)
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const NUDGE = 8;
const RELEASE_MIN = 12; // a line must be dragged this far (screen pixels) before releasing it on the canvas opens the menu

const svg = (name, attributes = {}) => {
  const el = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value);
  return el;
};

export class Canvas {
  /**
   * @param {object} options
   * @param {HTMLElement} options.viewport
   * @param {Map<string, object>} options.nodes
   * @param {Map<string, object>} options.edges
   * @param {object} options.handlers onSelect(selection|null, {focusInspector, keepMulti}), onMoved(node),
   *   onConnect(source, port, target, port, {source_slot, target_slot}), onDelete(selection), onZoom(zoom),
   *   onEdgeDelete(edgeId) and onEdgeStyle(edge, style) for the bar a connection shows on hover (the editor only);
   *   onNodeAction(action, node, button) for the bar under a node ("delete", "more") and onNodeMenu(node, {x, y})
   *   for a right click on it (the editor only);
   *   read-only: onOpen(node) (Enter on a node), onNodeDrawn(node, el) and onEdgeDrawn(edge, group)
   *   to decorate what was drawn
   * @param {boolean} [options.readOnly]
   * @param {number} [options.minZoom] how far it may zoom out (a wide flow on a phone needs less than the editor)
   */
  constructor({ viewport, nodes, edges, handlers, readOnly = false, minZoom = MIN_ZOOM }) {
    this.viewport = viewport;
    this.nodes = nodes;
    this.edges = edges;
    this.handlers = handlers;
    this.readOnly = readOnly;
    this.minZoom = minZoom;
    this.view = { x: 40, y: 40, zoom: 1 };
    this.selection = null;
    /** @type {Set<string>} the ids of the selected nodes (more than one after a frame was drawn) */
    this.multi = new Set();
    this.elements = new Map();
    this.gesture = null;

    this.world = viewport.querySelector("[data-world]");
    this.nodeLayer = viewport.querySelector("[data-nodes]");
    this.edgeLayer = viewport.querySelector("[data-edges]");
    this.edgeLayer.append(this.#markers());
    this.hoverEdgeId = null;
    this.hideTimer = null;
    this.edgeBar = this.readOnly ? null : this.#createEdgeBar();
    viewport.style.setProperty("--ge-stage-header", `${HEADER}px`); // read by editor.css

    if (!readOnly) {
      viewport.classList.add("is-editor");
      viewport.addEventListener("contextmenu", (event) => event.preventDefault()); // the right button pans
    }
    viewport.addEventListener("click", (event) => {
      const button = event.target.closest("[data-node-action]");
      const el = button?.closest(".ge-node");
      if (button && el && !this.readOnly) this.handlers.onNodeAction?.(button.dataset.nodeAction, this.nodes.get(el.dataset.nodeId), button);
    });
    viewport.addEventListener("dblclick", (event) => {
      // the pointer is captured while a gesture runs, which makes the viewport the target: look under the pointer
      const grip = this.readOnly ? null : document.elementFromPoint(event.clientX, event.clientY)?.closest(".ge-resize");
      if (grip) this.fitToContent(this.nodes.get(grip.closest(".ge-node").dataset.nodeId));
    });
    viewport.addEventListener("pointerdown", (event) => this.#onPointerDown(event));
    viewport.addEventListener("pointermove", (event) => this.#onPointerMove(event));
    viewport.addEventListener("pointerup", (event) => this.#onPointerUp(event));
    viewport.addEventListener("pointercancel", () => this.#cancelGesture());
    viewport.addEventListener("pointerleave", () => this.#leaveEdge());
    viewport.addEventListener("wheel", (event) => this.#onWheel(event), { passive: false });
    viewport.addEventListener("keydown", (event) => this.#onKeydown(event));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.gesture?.type === "connect") this.#cancelGesture();
    });
    this.#applyView();
  }

  // ── rendering ──────────────────────────────────────────────────────

  /** Reconcile the DOM with the current nodes and edges. */
  sync() {
    for (const [id, el] of this.elements) {
      if (!this.nodes.has(id)) {
        el.remove();
        this.elements.delete(id);
      }
    }
    const ordered = [...this.nodes.values()].sort((a, b) => Boolean(a.stage_id) - Boolean(b.stage_id)); // containers first
    for (const node of ordered) {
      let el = this.elements.get(node.id);
      if (!el) {
        el = this.#createNode(node);
        this.elements.set(node.id, el);
      }
      const host = node.stage_id ? this.elements.get(node.stage_id)?.querySelector(".ge-stage__body") : this.nodeLayer;
      if (host && el.parentElement !== host) host.append(el);
      this.#updateNode(node, el);
    }
    this.drawEdges();
  }

  /** The small bar under a node: a bin (Delete) and a menu (which has Edit); shown on hover and while it is selected. */
  #nodeBar(type) {
    const bar = document.createElement("div");
    bar.className = "ge-node-bar";
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", t("editor.canvas.node_actions"));
    const inner = document.createElement("div");
    inner.className = "ge-node-bar__inner";
    for (const [action, glyph, label] of [["delete", "trash", t("common.delete")], ["more", "more", t("editor.canvas.more_actions")]]) {
      if (action === "delete" && type.fixed) continue; // the trigger, the output and the end are part of the graph
      const button = document.createElement("button");
      button.type = "button";
      button.className = `icon-button icon-button--sm${action === "delete" ? " is-danger" : ""}`;
      button.dataset.nodeAction = action;
      button.title = label;
      button.setAttribute("aria-label", label);
      if (action === "more") button.setAttribute("aria-haspopup", "menu");
      button.append(icon(glyph));
      inner.append(button);
    }
    bar.append(inner);
    return bar;
  }

  #createNode(node) {
    const type = typeOf(node);
    const el = document.createElement(type.constructor.kind === "stage" ? "section" : "div");
    el.className = `ge-node ge-node--${node.kind}`;
    el.dataset.nodeId = node.id;
    el.tabIndex = 0;
    const name = document.createElement("strong");
    name.className = "ge-node__name";
    const caption = document.createElement("small");
    caption.className = "ge-node__kind";
    type.render(el, node, { name, caption });
    for (const port of type.ports()) el.append(this.#port(node, type, port));
    if (!this.readOnly) el.append(this.#nodeBar(type));
    if (!this.readOnly && type.behaviour === "stage") for (const side of ["e", "s", "se"]) el.append(this.#resizeHandle(side));
    return el;
  }

  /** A grip on the right edge (e), the bottom edge (s) or the corner (se) of a stage: it makes the stage larger or smaller. */
  #resizeHandle(side) {
    const el = document.createElement("span");
    el.className = `ge-resize ge-resize--${side}`;
    el.dataset.resize = side;
    el.tabIndex = 0;
    el.setAttribute("role", "separator");
    el.setAttribute("aria-orientation", side === "e" ? "vertical" : "horizontal");
    const label = { e: t("editor.canvas.resize_width"), s: t("editor.canvas.resize_height"), se: t("editor.canvas.resize_both") }[side];
    el.setAttribute("aria-label", label);
    el.title = label;
    if (side === "se") el.append(icon("resize-corner")); // the usual grip glyph: diagonal strokes in the lower right half
    return el;
  }

  /** A port dot. A stage's start and end work both ways ("both"): they receive and they feed. */
  #port(node, type, port) {
    const el = document.createElement("span");
    el.className = `ge-port ge-port--${port.name}`;
    el.dataset.port = port.name;
    el.dataset.slot = String(port.slot);
    el.dataset.nodeId = node.id;
    el.dataset.direction = port.direction;
    el.dataset.side = port.side;
    el.setAttribute("aria-hidden", "true");
    this.#name(el, node, type, port);
    return el;
  }

  /** Title and written label of a port (a Switch takes them from the value of its case). */
  #name(el, node, type, port) {
    const label = type.portLabel(port.name, node);
    el.title = label;
    if (type.labelled(port)) el.dataset.label = label;
  }

  #updateNode(node, el) {
    const type = typeOf(node);
    const { width, height } = sizeOf(node);
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y}px`;
    el.style.width = `${width}px`;
    el.style.height = `${height}px`;
    el.querySelector(".ge-node__name").textContent = displayName(node);
    el.setAttribute("aria-label", `${type.label}: ${displayName(node)}`);
    const caption = el.querySelector(".ge-node__kind");
    const text = type.caption(node);
    caption.textContent = text ?? "";
    caption.hidden = text === null;
    el.querySelectorAll(":scope > .ge-port").forEach((port) => {
      const at = type.portLocal(node, port.dataset.port, Number(port.dataset.slot), this.nodes);
      port.style.left = `${at.x}px`;
      port.style.top = `${at.y}px`;
      port.hidden = !type.isVisible(node, port.dataset.port);
      this.#name(port, node, type, { name: port.dataset.port });
    });
    el.classList.toggle("is-selected", this.multi.has(node.id));
    this.handlers.onNodeDrawn?.(node, el);
  }

  /** Redraw every edge (cheap: a handful of paths). */
  drawEdges() {
    this.edgeLayer.querySelectorAll(".ge-edge").forEach((el) => el.remove());
    const used = new Set();
    for (const edge of this.edges.values()) {
      const source = this.nodes.get(edge.source_id);
      const target = this.nodes.get(edge.target_id);
      if (!source || !target) continue;
      const attachment = edge.target_port === "tools"; // a tool hangs below its agent: dashed, no arrow
      const d = edgePath(portPoint(source, edge.source_port, this.nodes, edge.source_slot), portPoint(target, edge.target_port, this.nodes, edge.target_slot), boxOf(source, this.nodes), boxOf(target, this.nodes), { style: edge.style, attachment });
      const group = svg("g", { class: `ge-edge ge-edge--${attachment ? "attachment" : edge.source_port}`, "data-edge-id": edge.id });
      if (this.selection?.type === "edge" && this.selection.id === edge.id) group.classList.add("is-selected");
      const line = svg("path", attachment ? { class: "ge-edge__line", d } : { class: "ge-edge__line", d, "marker-end": `url(#ge-arrow-${FAILING_PORTS.includes(edge.source_port) ? "error" : "pass"})` });
      group.append(...(this.readOnly ? [line] : [svg("path", { class: "ge-edge__hit", d }), line]));
      this.edgeLayer.append(group);
      this.handlers.onEdgeDrawn?.(edge, group);
      used.add(`${edge.source_id}|${edge.source_port}|${edge.source_slot}`).add(`${edge.target_id}|${edge.target_port}|${edge.target_slot}`);
    }
    for (const el of this.nodeLayer.querySelectorAll(".ge-node--stage > .ge-port")) {
      el.classList.toggle("is-used", used.has(`${el.dataset.nodeId}|${el.dataset.port}|${el.dataset.slot}`));
    }
    this.#placeBar();
  }

  #markers() {
    const defs = svg("defs");
    for (const kind of ["pass", "error"]) {
      const marker = svg("marker", { id: `ge-arrow-${kind}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerUnits: "userSpaceOnUse", markerWidth: "10", markerHeight: "10", orient: "auto" });
      marker.append(svg("path", { d: "M 0 1 L 9 5 L 0 9 z", class: `ge-arrow ge-arrow--${kind}` }));
      defs.append(marker);
    }
    return defs;
  }

  /** Select one node or connection (or nothing); `multi` keeps a frame's selection of several nodes. */
  select(selection, { multi = null } = {}) {
    this.selection = selection;
    this.multi = multi ?? new Set(selection?.type === "node" ? [selection.id] : []);
    this.#paintSelection();
    this.drawEdges();
  }

  #paintSelection() {
    this.viewport.classList.toggle("has-multi", this.multi.size > 1); // several selected: no bar on each of them
    for (const [id, el] of this.elements) el.classList.toggle("is-selected", this.multi.has(id));
  }

  // ── the bar of a connection: a bin and a pencil, shown on hover and while it is selected ──

  #createEdgeBar() {
    const bar = document.createElement("div");
    bar.className = "ge-edge-bar";
    bar.hidden = true;
    const button = (className, label, content) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = className;
      el.setAttribute("aria-label", label);
      el.title = label;
      el.append(content);
      return el;
    };
    // a submenu of the pencil: centred below the bar, so the bar itself keeps its two buttons (more menus can follow the same way)
    const styles = document.createElement("span");
    styles.className = "ge-edge-bar__submenu";
    styles.hidden = true;
    const choices = document.createElement("span");
    choices.className = "ge-edge-bar__choices";
    styles.append(choices);
    for (const [value, label] of Object.entries(EDGE_STYLES)) {
      const choice = button("icon-button icon-button--sm ge-edge-bar__style", label, icon(`line-${value}`)); // a pictogram, its name is the tooltip
      choice.dataset.style = value;
      choices.append(choice);
    }
    const pencil = button("icon-button icon-button--sm ge-edge-bar__pencil", t("editor.canvas.change_line_style"), icon("pencil"));
    const bin = button("icon-button icon-button--sm is-danger ge-edge-bar__bin", t("editor.canvas.delete_connection"), icon("trash"));
    bar.append(pencil, bin, styles);
    bar.addEventListener("click", (event) => {
      const id = bar.dataset.edgeId;
      const edge = this.edges.get(id);
      if (!edge) return;
      if (event.target.closest(".ge-edge-bar__bin")) {
        this.hoverEdgeId = null;
        this.handlers.onEdgeDelete?.(id);
      } else if (event.target.closest(".ge-edge-bar__pencil")) {
        styles.hidden = !styles.hidden;
        this.#placeBar();
      } else if (event.target.closest(".ge-edge-bar__style")) {
        styles.hidden = true;
        this.handlers.onEdgeStyle?.(edge, event.target.closest(".ge-edge-bar__style").dataset.style);
      }
    });
    bar.addEventListener("pointerenter", () => clearTimeout(this.hideTimer));
    this.world.append(bar);
    return bar;
  }

  /** The pointer moved over the canvas: a connection under it (or its bar) is the one to show the bar for. */
  #trackEdge(event) {
    if (this.readOnly || this.gesture) return;
    const edge = event.target.closest(".ge-edge");
    if (edge) {
      clearTimeout(this.hideTimer);
      if (this.hoverEdgeId !== edge.dataset.edgeId) {
        this.hoverEdgeId = edge.dataset.edgeId;
        this.#placeBar();
      }
    } else if (!event.target.closest(".ge-edge-bar")) {
      this.#leaveEdge();
    }
  }

  /** The pointer left the connection: the bar stays a moment, so the pointer can reach it. */
  #leaveEdge() {
    if (!this.hoverEdgeId) return;
    clearTimeout(this.hideTimer);
    this.hideTimer = setTimeout(() => {
      this.hoverEdgeId = null;
      this.#placeBar();
    }, 250);
  }

  /** Show the bar in the middle of its connection (the hovered one, else the selected one), or hide it. */
  #placeBar() {
    const bar = this.edgeBar;
    if (!bar) return;
    const id = this.hoverEdgeId ?? (this.selection?.type === "edge" ? this.selection.id : null);
    const edge = id ? this.edges.get(id) : null;
    const line = edge && !this.gesture ? this.edgeLayer.querySelector(`.ge-edge[data-edge-id="${CSS.escape(id)}"] .ge-edge__line`) : null;
    if (!line) {
      bar.hidden = true;
      bar.querySelector(".ge-edge-bar__submenu").hidden = true;
      return;
    }
    if (bar.dataset.edgeId !== id) bar.querySelector(".ge-edge-bar__submenu").hidden = true;
    bar.dataset.edgeId = id;
    const middle = line.getPointAtLength(line.getTotalLength() / 2);
    bar.style.left = `${middle.x}px`;
    bar.style.top = `${middle.y}px`;
    bar.style.setProperty("--ge-inverse-zoom", String(1 / this.view.zoom)); // the bar keeps its size when the canvas zooms
    const attachment = edge.target_port === "tools"; // a tool's line has no style to choose
    bar.querySelector(".ge-edge-bar__pencil").hidden = attachment;
    for (const choice of bar.querySelectorAll(".ge-edge-bar__style")) choice.setAttribute("aria-pressed", String((edge.style || "curved") === choice.dataset.style));
    bar.hidden = false;
  }

  // ── view (pan / zoom) ──────────────────────────────────────────────

  #applyView() {
    const { x, y, zoom } = this.view;
    this.world.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
    this.world.style.setProperty("--ge-inverse-zoom", String(1 / zoom)); // bars under the nodes keep their size
    this.#placeBar();
    this.handlers.onZoom?.(zoom);
  }

  /** Canvas coordinates of a pointer position. */
  #toWorld(event) {
    const rect = this.viewport.getBoundingClientRect();
    return { x: (event.clientX - rect.left - this.view.x) / this.view.zoom, y: (event.clientY - rect.top - this.view.y) / this.view.zoom };
  }

  zoomBy(factor, anchor = null) {
    const rect = this.viewport.getBoundingClientRect();
    const px = anchor ? anchor.x : rect.width / 2;
    const py = anchor ? anchor.y : rect.height / 2;
    const zoom = Math.min(MAX_ZOOM, Math.max(this.minZoom, this.view.zoom * factor));
    const ratio = zoom / this.view.zoom;
    this.view = { x: px - (px - this.view.x) * ratio, y: py - (py - this.view.y) * ratio, zoom };
    this.#applyView();
  }

  /** Pan (not zoom) just enough to bring a node fully into view. */
  reveal(node) {
    const rect = this.viewport.getBoundingClientRect();
    const { x, y } = originOf(node, this.nodes);
    const { width, height } = sizeOf(node);
    const margin = 32;
    const { zoom } = this.view;
    const fix = (start, size, offset, extent) => {
      const low = start * zoom + offset;
      const high = (start + size) * zoom + offset;
      if (low < margin) return offset + (margin - low);
      if (high > extent - margin) return offset - (high - (extent - margin));
      return offset;
    };
    this.view = { ...this.view, x: fix(x, width, this.view.x, rect.width), y: fix(y, height, this.view.y, rect.height) };
    this.#applyView();
  }

  /**
   * Zoom and move so everything is visible (never zooms in beyond 100%). With `floor` it does not
   * zoom out below that: a wider graph then starts at its left edge and is panned, instead of
   * becoming too small to read.
   */
  fit({ floor = 0 } = {}) {
    const rect = this.viewport.getBoundingClientRect();
    if (this.nodes.size === 0 || rect.width === 0) return;
    let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
    for (const node of this.nodes.values()) {
      const { x, y } = originOf(node, this.nodes);
      const { width, height } = sizeOf(node);
      [minX, minY, maxX, maxY] = [Math.min(minX, x), Math.min(minY, y), Math.max(maxX, x + width), Math.max(maxY, y + height)];
    }
    const margin = 48;
    const zoom = Math.min(1, MAX_ZOOM, (rect.width - 2 * margin) / (maxX - minX), (rect.height - 2 * margin) / (maxY - minY));
    this.view = { zoom: Math.max(this.minZoom, floor, zoom), x: 0, y: 0 };
    this.view.x = Math.max(margin - minX * this.view.zoom, (rect.width - (maxX - minX) * this.view.zoom) / 2 - minX * this.view.zoom);
    this.view.y = (rect.height - (maxY - minY) * this.view.zoom) / 2 - minY * this.view.zoom;
    this.#applyView();
  }

  #onWheel(event) {
    event.preventDefault();
    const rect = this.viewport.getBoundingClientRect();
    this.zoomBy(event.deltaY < 0 ? 1.1 : 1 / 1.1, { x: event.clientX - rect.left, y: event.clientY - rect.top });
  }

  // ── pointer gestures ───────────────────────────────────────────────

  #onPointerDown(event) {
    if (this.gesture) return;
    if (!this.readOnly && event.button === 2) {
      event.preventDefault();
      // the right button drags the view, wherever it is; pressed and released on a node without moving it opens the node's menu
      return this.#startPan(event, null, { grab: true, contextNode: event.target.closest(".ge-node") });
    }
    if (event.button !== 0) return;
    if (this.readOnly) {
      if (event.target.closest("button, input, select, a")) return;
      return this.#startPan(event, event.target.closest(".ge-node")); // a click on a node activates it (see #onPointerUp)
    }
    if (event.target.closest(".ge-edge-bar")) return; // its buttons act on click; the bar is no place to pan from
    const grip = event.target.closest(".ge-resize");
    if (grip) return this.#startResize(event, grip);
    const port = event.target.closest(".ge-port");
    if (port) return this.#startConnect(event, port); // an input as well as an output: a press on a port never moves its node
    if (event.target.closest("button, input, select, a")) return;
    const edge = event.target.closest(".ge-edge");
    if (edge) {
      this.handlers.onSelect({ type: "edge", id: edge.dataset.edgeId });
      return;
    }
    const el = event.target.closest(".ge-node");
    if (el) return this.#startMove(event, this.nodes.get(el.dataset.nodeId));
    this.#startMarquee(event);
  }

  #startPan(event, nodeEl = null, { grab = false, contextNode = null } = {}) {
    this.gesture = { type: "pan", pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: { ...this.view }, moved: false, nodeEl, grab, contextNode };
    this.viewport.setPointerCapture(event.pointerId);
  }

  /** A press on a node: it moves (with the other selected nodes, if it is one of them) once the pointer has
   * travelled; a click selects it alone, or with Shift adds it to / takes it out of the selection. */
  #startMove(event, node) {
    if (event.shiftKey) {
      const multi = new Set(this.multi);
      if (!multi.delete(node.id)) multi.add(node.id);
      this.handlers.onSelect(multi.size ? { type: "node", id: multi.has(node.id) ? node.id : [...multi][0] } : null, { keepMulti: multi });
      return;
    }
    const group = this.multi.has(node.id) && this.multi.size > 1;
    if (!group) this.handlers.onSelect({ type: "node", id: node.id });
    // an action travels with its stage when both are selected: only the stage is moved
    const ids = group ? [...this.multi].filter((id) => !this.multi.has(this.nodes.get(id)?.stage_id)) : [node.id];
    const items = ids.map((id) => ({ node: this.nodes.get(id), origin: { x: this.nodes.get(id).x, y: this.nodes.get(id).y } }));
    this.gesture = { type: "move", pointerId: event.pointerId, node, items, group, startX: event.clientX, startY: event.clientY, moved: false };
    this.viewport.setPointerCapture(event.pointerId);
  }

  /** A press on a stage's grip: the stage follows the pointer, never smaller than its actions need. */
  #startResize(event, grip) {
    const node = this.nodes.get(grip.closest(".ge-node").dataset.nodeId);
    this.handlers.onSelect({ type: "node", id: node.id });
    this.viewport.classList.add("is-resizing");
    this.gesture = { type: "resize", pointerId: event.pointerId, node, side: grip.dataset.resize, origin: { width: node.width, height: node.height }, startX: event.clientX, startY: event.clientY, moved: false };
    this.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  /** Give a stage a size (not below what its actions need) and redraw it and its connections. */
  #resizeNode(node, width, height) {
    const least = minStageSize(actionsOf(node, this.nodes));
    node.width = Math.max(least.width, width);
    node.height = Math.max(least.height, height);
    this.#updateNode(node, this.elements.get(node.id));
    this.drawEdges();
  }

  /** The stage is exactly as large as its actions need (a double click on a grip). */
  fitToContent(node) {
    const least = minStageSize(actionsOf(node, this.nodes));
    this.#resizeNode(node, least.width, least.height);
    this.handlers.onResized?.(node);
  }

  /** A press on a stage's grip: the arrow keys resize it (Shift: four times as much), Enter or Home fits it to its actions. */
  #onGripKey(event, grip) {
    const node = this.nodes.get(grip.closest(".ge-node").dataset.nodeId);
    const step = event.shiftKey ? RESIZE_STEP * 4 : RESIZE_STEP;
    const grows = { ArrowRight: [step, 0], ArrowLeft: [-step, 0], ArrowDown: [0, step], ArrowUp: [0, -step] }[event.key];
    const side = grip.dataset.resize;
    if (grows) {
      event.preventDefault();
      this.#resizeNode(node, node.width + (side === "s" ? 0 : grows[0]), node.height + (side === "e" ? 0 : grows[1]));
      this.handlers.onResized?.(node);
    } else if (event.key === "Enter" || event.key === "Home") {
      event.preventDefault();
      this.fitToContent(node);
    }
  }

  /** A press on the background: a frame follows the pointer; on release it selects the nodes it touches. */
  #startMarquee(event) {
    const frame = document.createElement("div");
    frame.className = "ge-marquee";
    frame.hidden = true;
    this.viewport.append(frame);
    this.gesture = { type: "marquee", pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, frame, additive: event.shiftKey, moved: false };
    this.viewport.setPointerCapture(event.pointerId);
  }

  #drawMarquee(g, event) {
    const rect = this.viewport.getBoundingClientRect();
    const left = Math.min(g.startX, event.clientX);
    const top = Math.min(g.startY, event.clientY);
    g.box = { left, top, right: Math.max(g.startX, event.clientX), bottom: Math.max(g.startY, event.clientY) };
    Object.assign(g.frame.style, { left: `${left - rect.left}px`, top: `${top - rect.top}px`, width: `${g.box.right - left}px`, height: `${g.box.bottom - top}px` });
    g.frame.hidden = false;
  }

  /** The nodes under a frame: those it touches; a stage (a large container) only when it holds it whole. */
  #nodesInFrame(box) {
    const found = new Set();
    for (const [id, el] of this.elements) {
      const r = el.getBoundingClientRect();
      const touches = r.left < box.right && r.right > box.left && r.top < box.bottom && r.bottom > box.top;
      const whole = r.left >= box.left && r.right <= box.right && r.top >= box.top && r.bottom <= box.bottom;
      if (el.classList.contains("ge-node--stage") ? whole : touches) found.add(id);
    }
    return found;
  }

  #startConnect(event, port) {
    const node = this.nodes.get(port.dataset.nodeId);
    const slot = Number(port.dataset.slot);
    const from = portPoint(node, port.dataset.port, this.nodes, slot);
    const line = svg("path", { class: "ge-edge__line ge-edge__line--draft" });
    this.edgeLayer.append(line);
    // pressed at an input the line is drawn the other way round: it ends at an output that can feed this input
    const reverse = port.dataset.direction === "input";
    this.gesture = { type: "connect", pointerId: event.pointerId, node, port: port.dataset.port, slot, from, reverse, box: boxOf(node, this.nodes), line, direction: port.dataset.direction, startX: event.clientX, startY: event.clientY };
    const start = { node, port: port.dataset.port, direction: port.dataset.direction };
    for (const el of this.viewport.querySelectorAll(reverse ? '.ge-port:not([data-direction="input"])' : '.ge-port:not([data-direction="output"])')) {
      const other = { node: this.nodes.get(el.dataset.nodeId), port: el.dataset.port, direction: el.dataset.direction };
      el.classList.toggle("is-valid", el !== port && canConnectFrom(start, other));
    }
    this.viewport.classList.add("is-connecting");
    this.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  #onPointerMove(event) {
    this.#trackEdge(event);
    const g = this.gesture;
    if (!g || event.pointerId !== g.pointerId) return;
    if (g.type === "connect") {
      const to = this.#toWorld(event);
      const attachment = g.port === "tool" || g.port === "tools";
      g.line.setAttribute("d", g.reverse ? edgePath(to, g.from, g.box, g.box, { routed: false, attachment }) : edgePath(g.from, to, g.box, g.box, { routed: false, attachment }));
      const over = document.elementFromPoint(event.clientX, event.clientY)?.closest(".ge-port.is-valid");
      this.viewport.querySelectorAll(".ge-port.is-hover").forEach((el) => el.classList.toggle("is-hover", el === over));
      over?.classList.add("is-hover");
      return;
    }
    const dx = event.clientX - g.startX;
    const dy = event.clientY - g.startY;
    if (!g.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    g.moved = true;
    if (g.type === "pan") {
      if (g.grab) this.viewport.classList.add("is-panning");
      this.view = { ...g.origin, x: g.origin.x + dx, y: g.origin.y + dy };
      this.#applyView();
    } else if (g.type === "marquee") {
      this.#drawMarquee(g, event);
    } else if (g.type === "resize") {
      const [wide, tall] = [g.side !== "s", g.side !== "e"];
      this.#resizeNode(g.node, g.origin.width + (wide ? dx / this.view.zoom : 0), g.origin.height + (tall ? dy / this.view.zoom : 0));
    } else {
      for (const { node, origin } of g.items) this.#moveNode(node, origin.x + dx / this.view.zoom, origin.y + dy / this.view.zoom);
      this.#snap(g, event.altKey);
    }
  }

  /**
   * A dragged node settles level with a port it is connected to (so the line between them is straight) when it comes
   * within a few pixels; a thin dashed guide shows the alignment. Alt switches it off. The nodes moved together keep their
   * distances: the primary node decides.
   */
  #snap(g, off) {
    const moving = new Set(g.items.map((item) => item.node.id));
    // the ports it is connected to come first: with equally near candidates a connected one wins
    const pairs = off ? [] : [...this.#levelPairs(g.node, moving), ...slotPairs(g.node, this.nodes)];
    const hit = snapY(pairs, SNAP_DISTANCE / this.view.zoom);
    if (hit && hit.delta !== 0) for (const { node } of g.items) this.#moveNode(node, node.x, node.y + hit.delta);
    this.#guide(hit ? pairs.find((pair) => pair.other === hit.y) : null);
  }

  /** For each connection of `node` to a node that stays put (also its own stage, whose points no longer follow it): the height of its port, of the other port, and where both are. */
  #levelPairs(node, moving) {
    const pairs = [];
    for (const edge of this.edges.values()) {
      if (edge.target_port === "tools") continue; // a tool hangs below its agent
      const ends = edge.source_id === node.id ? ["source", "target"] : edge.target_id === node.id ? ["target", "source"] : null;
      if (!ends) continue;
      const other = this.nodes.get(edge[`${ends[1]}_id`]);
      // the actions of a stage move with it: aligning a stage with their ports would always match
      if (!other || moving.has(other.id) || other.stage_id === node.id) continue;
      const mine = portPoint(node, edge[`${ends[0]}_port`], this.nodes, edge[`${ends[0]}_slot`]);
      const theirs = portPoint(other, edge[`${ends[1]}_port`], this.nodes, edge[`${ends[1]}_slot`]);
      pairs.push({ own: mine.y, other: theirs.y, from: mine.x, to: theirs.x });
    }
    return pairs;
  }

  /** Show (or, given null, remove) the guide line of an alignment. */
  #guide(pair) {
    this.edgeLayer.querySelector(".ge-guide")?.remove();
    if (!pair) return;
    const [left, right] = [Math.min(pair.from, pair.to) - 24, Math.max(pair.from, pair.to) + 24];
    this.edgeLayer.append(svg("line", { class: "ge-guide", x1: left, x2: right, y1: pair.other, y2: pair.other }));
  }

  #onPointerUp(event) {
    const g = this.gesture;
    if (!g || event.pointerId !== g.pointerId) return;
    if (g.type === "connect") {
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".ge-port.is-valid");
      this.#cancelGesture();
      if (!target) this.#released(g, event);
      if (target) {
        const other = this.nodes.get(target.dataset.nodeId);
        const slots = { source_slot: g.slot, target_slot: Number(target.dataset.slot) };
        // stored in the normal direction, whichever end was pressed: source = the output, target = the input
        if (g.reverse) this.handlers.onConnect(other, target.dataset.port, g.node, g.port, { source_slot: slots.target_slot, target_slot: slots.source_slot });
        else this.handlers.onConnect(g.node, g.port, other, target.dataset.port, slots);
      }
      return;
    }
    this.gesture = null;
    this.viewport.releasePointerCapture?.(event.pointerId);
    this.viewport.classList.remove("is-panning");
    this.#guide(null);
    this.viewport.classList.remove("is-resizing");
    if (g.type === "resize") {
      if (g.moved) this.handlers.onResized?.(g.node);
      return;
    }
    if (g.type === "marquee") return this.#endMarquee(g);
    if (g.type === "pan" && !g.moved && g.nodeEl) {
      this.focusNode(g.nodeEl.dataset.nodeId);
      this.handlers.onOpen?.(this.nodes.get(g.nodeEl.dataset.nodeId));
    } else if (g.type === "pan" && !g.moved && g.grab && g.contextNode) {
      this.handlers.onNodeMenu?.(this.nodes.get(g.contextNode.dataset.nodeId), { x: event.clientX, y: event.clientY });
    } else if (g.type === "pan" && !g.moved && !g.grab) this.handlers.onSelect(null);
    if (g.type === "move" && g.moved) for (const { node } of g.items) this.handlers.onMoved(node);
    // a click on one node of a selection of several selects that node alone
    if (g.type === "move" && !g.moved && g.group) this.handlers.onSelect({ type: "node", id: g.node.id });
  }

  /** A line dragged from a port and released on the empty canvas (or an empty stretch of a stage): the editor opens the menu of what can be connected there. */
  #released(g, event) {
    if (this.readOnly || Math.hypot(event.clientX - g.startX, event.clientY - g.startY) < RELEASE_MIN) return;
    const over = document.elementFromPoint(event.clientX, event.clientY);
    if (!over || !this.viewport.contains(over) || over.closest(".ge-port, .ge-edge-bar, button, input")) return;
    const el = over.closest(".ge-node");
    if (el && !el.classList.contains("ge-node--stage")) return; // released on a node (not on a port that fits): nothing happens, as before
    this.handlers.onConnectRelease?.({
      node: g.node,
      port: g.port,
      slot: g.slot,
      direction: g.direction,
      point: { x: event.clientX, y: event.clientY },
      world: this.#toWorld(event),
      stageId: el?.dataset.nodeId ?? null,
    });
  }

  #endMarquee(g) {
    g.frame.remove();
    if (!g.moved) {
      if (!g.additive) this.handlers.onSelect(null); // a click on the background selects nothing
      return;
    }
    const found = this.#nodesInFrame(g.box);
    const multi = g.additive ? new Set([...this.multi, ...found]) : found;
    const first = [...multi][0];
    this.handlers.onSelect(first ? { type: "node", id: first } : null, { keepMulti: multi });
  }

  #cancelGesture() {
    const g = this.gesture;
    if (!g) return;
    this.gesture = null;
    this.viewport.classList.remove("is-panning");
    this.#guide(null);
    this.viewport.classList.remove("is-resizing");
    if (g.type === "resize") this.#resizeNode(g.node, g.origin.width, g.origin.height);
    if (g.type === "marquee") g.frame.remove();
    if (g.type === "connect") {
      g.line.remove();
      this.viewport.classList.remove("is-connecting");
      this.viewport.querySelectorAll(".ge-port.is-valid, .ge-port.is-hover").forEach((el) => el.classList.remove("is-valid", "is-hover"));
    }
  }

  /** Move a node; an action stays inside its stage and makes the stage grow if needed. */
  #moveNode(node, x, y) {
    if (node.stage_id) {
      Object.assign(node, clampInStage(x, y));
      const stage = this.nodes.get(node.stage_id);
      Object.assign(stage, fitStage(stage, actionsOf(stage, this.nodes)));
      this.#updateNode(stage, this.elements.get(stage.id));
    } else {
      node.x = x;
      node.y = y;
    }
    this.#updateNode(node, this.elements.get(node.id));
    this.drawEdges();
  }

  /** Arrow keys nudge the focused node; Delete removes it. */
  #onKeydown(event) {
    const grip = event.target.closest?.(".ge-resize");
    if (grip) {
      if (!this.readOnly) this.#onGripKey(event, grip);
      return;
    }
    const el = event.target.closest?.(".ge-node");
    if (!el || event.target.closest("input, select, button")) return;
    const node = this.nodes.get(el.dataset.nodeId);
    if (this.readOnly) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this.handlers.onOpen?.(node);
      }
      return;
    }
    const step = event.shiftKey ? NUDGE * 4 : NUDGE;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
    if (delta) {
      event.preventDefault();
      this.#moveNode(node, node.x + delta[0], node.y + delta[1]);
      this.handlers.onMoved(node);
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      this.handlers.onDelete({ type: "node", id: node.id });
    } else if (event.key === "Enter") {
      event.preventDefault();
      this.handlers.onSelect({ type: "node", id: node.id }, { focusInspector: true });
    }
  }

  focusNode(id) {
    this.elements.get(id)?.focus({ preventScroll: true });
  }
}
