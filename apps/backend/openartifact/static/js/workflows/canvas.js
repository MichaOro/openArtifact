/* The workflow canvas: renders nodes (HTML) and edges (SVG) inside a pannable, zoomable world and
 * turns pointer input into callbacks. It owns no data: nodes/edges are the editor's Maps.
 *
 *  - drag a node to move it (an action stays inside its stage, which grows as needed);
 *  - drag from an output port to an input port to connect;
 *  - drag the background to pan, wheel or the zoom buttons to zoom;
 *  - click a node or an edge to select it. */
import { PAD, boxOf, displayName, canConnect, edgePath, fitStage, originOf, portPoint, sizeOf } from "./graph.js";
import { typeOf } from "./node-types.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const DRAG_THRESHOLD = 4;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const NUDGE = 8;

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
   * @param {object} options.handlers onSelect(selection|null), onMoved(node), onConnect(source, port, target, port),
   *   onAddAction(stage), onDelete(selection), onZoom(zoom)
   */
  constructor({ viewport, nodes, edges, handlers }) {
    this.viewport = viewport;
    this.nodes = nodes;
    this.edges = edges;
    this.handlers = handlers;
    this.view = { x: 40, y: 40, zoom: 1 };
    this.selection = null;
    this.elements = new Map();
    this.gesture = null;

    this.world = viewport.querySelector("[data-world]");
    this.nodeLayer = viewport.querySelector("[data-nodes]");
    this.edgeLayer = viewport.querySelector("[data-edges]");
    this.edgeLayer.append(this.#markers());

    viewport.addEventListener("pointerdown", (event) => this.#onPointerDown(event));
    viewport.addEventListener("pointermove", (event) => this.#onPointerMove(event));
    viewport.addEventListener("pointerup", (event) => this.#onPointerUp(event));
    viewport.addEventListener("pointercancel", () => this.#cancelGesture());
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
      const host = node.stage_id ? this.elements.get(node.stage_id)?.querySelector(".wf-stage__body") : this.nodeLayer;
      if (host && el.parentElement !== host) host.append(el);
      this.#updateNode(node, el);
    }
    this.drawEdges();
  }

  #createNode(node) {
    const type = typeOf(node);
    const el = document.createElement(type.constructor.kind === "stage" ? "section" : "div");
    el.className = `wf-node wf-node--${node.kind}`;
    el.dataset.nodeId = node.id;
    el.tabIndex = 0;
    const name = document.createElement("strong");
    name.className = "wf-node__name";
    const caption = document.createElement("small");
    caption.className = "wf-node__kind";
    type.render(el, node, { name, caption });
    for (const port of type.ports()) el.append(this.#port(node, type, port));
    return el;
  }

  /** A port dot. A stage's start and end work both ways ("both"): they receive and they feed. */
  #port(node, type, port) {
    const el = document.createElement("span");
    el.className = `wf-port wf-port--${port.name}`;
    el.dataset.port = port.name;
    el.dataset.slot = String(port.slot);
    el.dataset.nodeId = node.id;
    el.dataset.direction = port.direction;
    el.dataset.side = port.side;
    el.setAttribute("aria-hidden", "true");
    el.title = port.label;
    if (type.constructor.portLabels) el.dataset.label = port.label;
    return el;
  }

  #updateNode(node, el) {
    const type = typeOf(node);
    const { width, height } = sizeOf(node);
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y}px`;
    el.style.width = `${width}px`;
    el.style.height = `${height}px`;
    el.querySelector(".wf-node__name").textContent = displayName(node);
    el.setAttribute("aria-label", `${type.label}: ${displayName(node)}`);
    const caption = el.querySelector(".wf-node__kind");
    const text = type.caption(node);
    caption.textContent = text ?? "";
    caption.hidden = text === null;
    el.querySelectorAll(":scope > .wf-port").forEach((port) => {
      const at = type.portLocal(node, port.dataset.port, Number(port.dataset.slot));
      port.style.left = `${at.x}px`;
      port.style.top = `${at.y}px`;
      port.hidden = !type.isVisible(node, port.dataset.port);
    });
    el.classList.toggle("is-selected", this.selection?.type === "node" && this.selection.id === node.id);
  }

  /** Redraw every edge (cheap: a handful of paths). */
  drawEdges() {
    this.edgeLayer.querySelectorAll(".wf-edge").forEach((el) => el.remove());
    const used = new Set();
    for (const edge of this.edges.values()) {
      const source = this.nodes.get(edge.source_id);
      const target = this.nodes.get(edge.target_id);
      if (!source || !target) continue;
      const d = edgePath(portPoint(source, edge.source_port, this.nodes, edge.source_slot), portPoint(target, edge.target_port, this.nodes, edge.target_slot), boxOf(source, this.nodes), boxOf(target, this.nodes), { style: edge.style });
      const group = svg("g", { class: `wf-edge wf-edge--${edge.source_port}`, "data-edge-id": edge.id });
      if (this.selection?.type === "edge" && this.selection.id === edge.id) group.classList.add("is-selected");
      group.append(svg("path", { class: "wf-edge__hit", d }), svg("path", { class: "wf-edge__line", d, "marker-end": `url(#wf-arrow-${edge.source_port === "error" ? "error" : "pass"})` }));
      this.edgeLayer.append(group);
      used.add(`${edge.source_id}|${edge.source_port}|${edge.source_slot}`).add(`${edge.target_id}|${edge.target_port}|${edge.target_slot}`);
    }
    for (const el of this.nodeLayer.querySelectorAll(".wf-node--stage > .wf-port")) {
      el.classList.toggle("is-used", used.has(`${el.dataset.nodeId}|${el.dataset.port}|${el.dataset.slot}`));
    }
  }

  #markers() {
    const defs = svg("defs");
    for (const kind of ["pass", "error"]) {
      const marker = svg("marker", { id: `wf-arrow-${kind}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerUnits: "userSpaceOnUse", markerWidth: "10", markerHeight: "10", orient: "auto" });
      marker.append(svg("path", { d: "M 0 1 L 9 5 L 0 9 z", class: `wf-arrow wf-arrow--${kind}` }));
      defs.append(marker);
    }
    return defs;
  }

  select(selection) {
    this.selection = selection;
    for (const [id, el] of this.elements) el.classList.toggle("is-selected", selection?.type === "node" && selection.id === id);
    this.drawEdges();
  }

  // ── view (pan / zoom) ──────────────────────────────────────────────

  #applyView() {
    const { x, y, zoom } = this.view;
    this.world.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
    this.viewport.style.setProperty("--wf-zoom", String(zoom));
    this.handlers.onZoom?.(zoom);
  }

  /** Canvas coordinates of a pointer position. */
  #toWorld(event) {
    const rect = this.viewport.getBoundingClientRect();
    return { x: (event.clientX - rect.left - this.view.x) / this.view.zoom, y: (event.clientY - rect.top - this.view.y) / this.view.zoom };
  }

  /** The canvas point in the middle of the visible area. */
  center() {
    const rect = this.viewport.getBoundingClientRect();
    return { x: (rect.width / 2 - this.view.x) / this.view.zoom, y: (rect.height / 2 - this.view.y) / this.view.zoom };
  }

  zoomBy(factor, anchor = null) {
    const rect = this.viewport.getBoundingClientRect();
    const px = anchor ? anchor.x : rect.width / 2;
    const py = anchor ? anchor.y : rect.height / 2;
    const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, this.view.zoom * factor));
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

  /** Zoom and move so everything is visible (never zooms in beyond 100%). */
  fit() {
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
    this.view = { zoom: Math.max(MIN_ZOOM, zoom), x: 0, y: 0 };
    this.view.x = (rect.width - (maxX - minX) * this.view.zoom) / 2 - minX * this.view.zoom;
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
    if (event.button !== 0 || this.gesture) return;
    const port = event.target.closest(".wf-port");
    if (port && port.dataset.direction !== "input") return this.#startConnect(event, port);
    if (event.target.closest("button, input, select, a")) return;
    const edge = event.target.closest(".wf-edge");
    if (edge) {
      this.handlers.onSelect({ type: "edge", id: edge.dataset.edgeId });
      return;
    }
    const el = event.target.closest(".wf-node");
    if (el) return this.#startMove(event, this.nodes.get(el.dataset.nodeId));
    this.gesture = { type: "pan", pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, origin: { ...this.view }, moved: false };
    this.viewport.setPointerCapture(event.pointerId);
  }

  #startMove(event, node) {
    this.gesture = { type: "move", pointerId: event.pointerId, node, startX: event.clientX, startY: event.clientY, origin: { x: node.x, y: node.y }, moved: false };
    this.viewport.setPointerCapture(event.pointerId);
    this.handlers.onSelect({ type: "node", id: node.id });
  }

  #startConnect(event, port) {
    const node = this.nodes.get(port.dataset.nodeId);
    const slot = Number(port.dataset.slot);
    const from = portPoint(node, port.dataset.port, this.nodes, slot);
    const line = svg("path", { class: "wf-edge__line wf-edge__line--draft" });
    this.edgeLayer.append(line);
    this.gesture = { type: "connect", pointerId: event.pointerId, node, port: port.dataset.port, slot, from, box: boxOf(node, this.nodes), line };
    for (const el of this.viewport.querySelectorAll('.wf-port:not([data-direction="output"])')) {
      const target = this.nodes.get(el.dataset.nodeId);
      el.classList.toggle("is-valid", canConnect(node, port.dataset.port, target, el.dataset.port));
    }
    this.viewport.classList.add("is-connecting");
    this.viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  #onPointerMove(event) {
    const g = this.gesture;
    if (!g || event.pointerId !== g.pointerId) return;
    if (g.type === "connect") {
      const to = this.#toWorld(event);
      g.line.setAttribute("d", edgePath(g.from, to, g.box, g.box, { routed: false }));
      const over = document.elementFromPoint(event.clientX, event.clientY)?.closest(".wf-port.is-valid");
      this.viewport.querySelectorAll(".wf-port.is-hover").forEach((el) => el.classList.toggle("is-hover", el === over));
      over?.classList.add("is-hover");
      return;
    }
    const dx = event.clientX - g.startX;
    const dy = event.clientY - g.startY;
    if (!g.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    g.moved = true;
    if (g.type === "pan") {
      this.view = { ...g.origin, x: g.origin.x + dx, y: g.origin.y + dy };
      this.#applyView();
    } else {
      this.#moveNode(g.node, g.origin.x + dx / this.view.zoom, g.origin.y + dy / this.view.zoom);
    }
  }

  #onPointerUp(event) {
    const g = this.gesture;
    if (!g || event.pointerId !== g.pointerId) return;
    if (g.type === "connect") {
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".wf-port.is-valid");
      this.#cancelGesture();
      if (target) {
        this.handlers.onConnect(g.node, g.port, this.nodes.get(target.dataset.nodeId), target.dataset.port, { source_slot: g.slot, target_slot: Number(target.dataset.slot) });
      }
      return;
    }
    this.gesture = null;
    this.viewport.releasePointerCapture?.(event.pointerId);
    if (g.type === "pan" && !g.moved) this.handlers.onSelect(null);
    if (g.type === "move" && g.moved) this.handlers.onMoved(g.node);
  }

  #cancelGesture() {
    const g = this.gesture;
    if (!g) return;
    this.gesture = null;
    if (g.type === "connect") {
      g.line.remove();
      this.viewport.classList.remove("is-connecting");
      this.viewport.querySelectorAll(".wf-port.is-valid, .wf-port.is-hover").forEach((el) => el.classList.remove("is-valid", "is-hover"));
    }
  }

  /** Move a node; an action stays inside its stage and makes the stage grow if needed. */
  #moveNode(node, x, y) {
    if (node.stage_id) {
      node.x = Math.max(PAD / 2, x);
      node.y = Math.max(PAD / 2, y);
      const stage = this.nodes.get(node.stage_id);
      const actions = [...this.nodes.values()].filter((n) => n.stage_id === stage.id);
      Object.assign(stage, fitStage(stage, actions));
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
    const el = event.target.closest?.(".wf-node");
    if (!el || event.target.closest("input, select, button")) return;
    const node = this.nodes.get(el.dataset.nodeId);
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
