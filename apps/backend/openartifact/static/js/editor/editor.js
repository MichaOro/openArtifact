/* The graph editor: owns the graph, talks to the API and connects canvas, toolbar and
 * inspector. Changes are saved at once; if the server refuses one, the graph is reloaded. */
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { InlineName } from "../components/inline-name.js";
import { Modal } from "../components/modal.js";
import { addNode, connect, createGraph, listGraphs, deleteNode, disconnect, loadGraph, renameGraph, restyleEdge, updateNode } from "./api.js";
import { Canvas } from "./canvas.js";
import { ACTION_GAP, EDGE_STYLES, displayName, PAD, TOP_LEVEL_GAP, canConnect, fitStage, sizeOf } from "./geometry.js";
import { InspectorBlocks, field, heading, note } from "./inspector.js";
import { addableIn, typeOf } from "./node-types.js";

const LAST_STAGE = "oa-last-pipeline"; // read by main.js
const EDITOR_PATHS = { pipeline: "/pipelines", action: "/actions" }; // where a pipeline / an action definition is edited

export class GraphEditor {
  /** @param {HTMLElement} root the element carrying data-graph-id */
  constructor(root) {
    this.id = root.dataset.graphId;
    this.root = root;
    this.kind = root.dataset.kind;
    this.isAction = this.kind === "action"; // an action definition: trigger and output are fixed
    this.graph = null;
    this.nodes = new Map();
    this.edges = new Map();
    this.selection = null;

    this.alert = root.querySelector("[data-editor-error]");
    this.inspector = root.querySelector("[data-inspector]");
    this.zoomLabel = root.querySelector("[data-zoom-label]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
    this.blocks = new InspectorBlocks(this.#blockActions());
    this.canvas = new Canvas({
      viewport: root.querySelector("[data-viewport]"),
      nodes: this.nodes,
      edges: this.edges,
      handlers: {
        onSelect: (selection, options) => this.select(selection, options),
        onMoved: (node) => this.#persistPosition(node),
        onConnect: (source, port, target, targetPort, slots) => this.#connect(source, port, target, targetPort, slots),
        onDelete: (selection) => this.requestDelete(selection),
        onZoom: (zoom) => (this.zoomLabel.textContent = `${Math.round(zoom * 100)}%`),
      },
    });

    this.#bindAddMenu();
    root.querySelector("[data-zoom-in]").addEventListener("click", () => this.canvas.zoomBy(1.2));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => this.canvas.zoomBy(1 / 1.2));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => this.canvas.fit());
    root.querySelector("[data-retry]").addEventListener("click", () => this.load());
    this.canvas.viewport.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-action]");
      if (add) this.#addAction(this.nodes.get(add.closest(".wf-node").dataset.nodeId));
    });
    this.canvas.viewport.addEventListener("keydown", (event) => {
      if ((event.key === "Delete" || event.key === "Backspace") && this.selection?.type === "edge" && !event.target.closest("input, select")) {
        event.preventDefault();
        this.#removeEdge(this.selection.id);
      }
    });
  }

  // ── loading ────────────────────────────────────────────────────────

  async load({ fit = false } = {}) {
    try {
      const graph = await loadGraph(this.kind, this.id);
      this.graph = graph.graph;
      this.nodes.clear();
      this.edges.clear();
      for (const node of graph.nodes) this.nodes.set(node.id, node);
      for (const edge of graph.edges) this.edges.set(edge.id, edge);
      this.alert.hidden = true;
      this.#showTitle();
      document.title = `${this.graph.name} · OpenArtifact`;
      this.canvas.sync();
      if (fit) this.canvas.fit();
      this.#renderInspector();
      if (!this.opened) this.#onFirstLoad();
      this.opened = true;
    } catch (error) {
      if (error.status === 404 && !this.isAction) localStorage.removeItem(LAST_STAGE);
      this.#showError(error.status === 404 ? "This pipeline or action does not exist." : "It could not be loaded.", true);
    }
  }

  /** Opened from a node of a pipeline: offer the way back; back in a pipeline: select that node again. */
  async #onFirstLoad() {
    const params = new URLSearchParams(window.location.search);
    this.#setupBack(params.get("from"), params.get("node")); // opened from a node of a pipeline
    if (this.isAction) return undefined;
    this.#remember(null);
    const wanted = params.get("select");
    if (wanted && this.nodes.has(wanted)) {
      this.select({ type: "node", id: wanted });
      this.canvas.reveal(this.nodes.get(wanted));
      window.history.replaceState(null, "", window.location.pathname);
    }
    return undefined;
  }

  async #setupBack(slug, nodeId) {
    if (!slug) return;
    const link = this.root.querySelector("[data-back]");
    link.href = `/pipelines/${encodeURIComponent(slug)}${nodeId ? `?select=${encodeURIComponent(nodeId)}` : ""}`;
    try {
      const pipeline = (await listGraphs("pipeline")).find((w) => w.slug === slug);
      link.textContent = pipeline ? `Back to ${pipeline.name}` : "Back to pipeline";
    } catch {
      link.textContent = "Back to pipeline";
    }
    link.hidden = false;
  }

  /** The navigation reopens the last stage with its action selected (see main.js). */
  #remember(nodeId) {
    if (this.isAction || !this.graph) return;
    try {
      localStorage.setItem(LAST_STAGE, JSON.stringify({ slug: this.graph.slug, node: nodeId }));
    } catch {
      /* storage unavailable: the navigation just shows the list */
    }
  }

  #showError(message, retry = false) {
    this.alert.querySelector("[data-editor-error-text]").textContent = message;
    this.alert.querySelector("[data-retry]").hidden = !retry;
    this.alert.hidden = false;
  }

  /** Run a change; on failure show why and return to what the server has. */
  async #save(change) {
    try {
      await change();
      this.alert.hidden = true;
      return true;
    } catch (error) {
      await this.load();
      this.#showError(error.status === 422 ? "That change is not allowed." : "The change could not be saved.");
      return false;
    }
  }

  // ── selection ──────────────────────────────────────────────────────

  select(selection, { focusInspector = false } = {}) {
    this.selection = selection;
    const picked = selection?.type === "node" ? this.nodes.get(selection.id) : null;
    this.#remember(picked?.kind === "action" ? picked.id : null);
    this.canvas.select(selection);
    if (selection?.type === "edge") this.canvas.viewport.focus({ preventScroll: true }); // so Delete reaches it
    this.#renderInspector();
    if (focusInspector) this.inspector.querySelector("input, select, button")?.focus();
  }

  // ── adding ─────────────────────────────────────────────────────────

  /** The "+" menu on the canvas offers every kind that can be added here (fixed kinds are always there). */
  #bindAddMenu() {
    const toggle = this.root.querySelector("[data-add-menu]");
    if (!toggle) return;
    const list = this.root.querySelector("[data-add-list]");
    for (const type of addableIn(this.kind)) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "wf-add__item";
      item.setAttribute("role", "menuitem");
      item.dataset.add = type.kind;
      item.textContent = type.label;
      list.append(item);
    }
    const setOpen = (open) => {
      list.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
    };
    toggle.addEventListener("click", () => {
      setOpen(list.hidden);
      if (!list.hidden) list.querySelector("button")?.focus();
    });
    list.addEventListener("click", (event) => {
      const item = event.target.closest("[data-add]");
      if (!item) return;
      setOpen(false);
      this.#addBeforeEnd(item.dataset.add);
    });
    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".wf-add")) setOpen(false);
    });
    this.root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !list.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  /**
   * A new stage (or timer) goes right of the last one, or of the trigger; the ending (complete, or the
   * output of an action definition) moves on if it is in the way.
   */
  async #addBeforeEnd(kind) {
    const nodes = [...this.nodes.values()];
    const widthOf = (n) => sizeOf(n).width;
    const before = nodes.filter((n) => typeOf(n).chain);
    const right = Math.max(...before.map((n) => n.x + widthOf(n)), 60);
    const created = await this.#create({ kind, x: Math.round(right + TOP_LEVEL_GAP), y: kind === "stage" ? 40 : 172 });
    if (!created) return;
    const ending = nodes.find((n) => typeOf(n).ending);
    const free = created.x + widthOf(created) + TOP_LEVEL_GAP;
    if (ending && ending.x < free) {
      ending.x = free;
      this.canvas.sync();
      await this.#save(() => updateNode(this.kind, this.id, ending.id, { x: free }));
    }
    this.canvas.reveal(created);
  }

  async #addAction(stage) {
    const actions = [...this.nodes.values()].filter((n) => n.stage_id === stage.id);
    // flows run left to right: a new action goes to the right of the last one
    const x = actions.length ? Math.max(...actions.map((a) => a.x + sizeOf(a).width)) + ACTION_GAP : PAD;
    const created = await this.#create({ kind: "action", stage_id: stage.id, x, y: PAD * 2 });
    if (created) await this.#growStage(stage);
  }

  async #create(fields) {
    let node = null;
    const saved = await this.#save(async () => {
      node = await addNode(this.kind, this.id, fields);
      this.nodes.set(node.id, node);
    });
    if (!saved || !node) return null;
    this.canvas.sync();
    this.select({ type: "node", id: node.id });
    this.canvas.focusNode(node.id);
    return node;
  }

  async #growStage(stage) {
    const actions = [...this.nodes.values()].filter((n) => n.stage_id === stage.id);
    const size = fitStage(stage, actions);
    if (size.width === stage.width && size.height === stage.height) return;
    Object.assign(stage, size);
    this.canvas.sync();
    await this.#save(() => updateNode(this.kind, this.id, stage.id, size));
  }

  // ── changing ───────────────────────────────────────────────────────

  async #persistPosition(node) {
    const fields = { x: Math.round(node.x), y: Math.round(node.y) };
    node.x = fields.x;
    node.y = fields.y;
    const stage = node.kind === "action" ? this.nodes.get(node.stage_id) : null;
    if (stage) {
      stage.width = Math.round(stage.width);
      stage.height = Math.round(stage.height);
    }
    await this.#save(async () => {
      await updateNode(this.kind, this.id, node.id, fields);
      if (stage) await updateNode(this.kind, this.id, stage.id, { width: stage.width, height: stage.height });
    });
  }

  /** The name in the page header, which can be renamed in place as well. */
  #showTitle() {
    const title = document.querySelector(".app-header__title");
    if (this.titleName) this.titleName.setText(this.graph.name);
    else {
      title.textContent = this.graph.name;
      this.titleName = new InlineName(title, { label: this.isAction ? "Action name" : "Pipeline name", onCommit: (name) => this.#renameGraph(name) });
    }
  }

  async #rename(node, name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === node.name) return this.#renderInspector();
    node.name = trimmed;
    this.canvas.sync();
    await this.#save(() => updateNode(this.kind, this.id, node.id, { name: trimmed }));
    this.#renderInspector();
  }

  /** Change a setting of the node's kind; connections at ports that are gone with it go too. */
  async #setSetting(node, key, value) {
    node[key] = value;
    const type = typeOf(node);
    for (const [id, edge] of this.edges) {
      const port = edge.source_id === node.id ? edge.source_port : edge.target_id === node.id ? edge.target_port : null;
      if (port && !type.isVisible(node, port)) this.edges.delete(id);
    }
    this.canvas.sync();
    this.#renderInspector();
    await this.#save(() => updateNode(this.kind, this.id, node.id, { [key]: value }));
  }

  async #renameGraph(name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === this.graph.name) return this.#renderInspector();
    this.graph.name = trimmed;
    this.#showTitle();
    const saved = await this.#save(async () => {
      this.graph = await renameGraph(this.kind, this.id, trimmed);
    });
    if (saved) {
      window.history.replaceState(null, "", `${window.location.pathname.replace(/[^/]+$/, "")}${encodeURIComponent(this.graph.slug)}`);
      this.#remember(this.selection?.type === "node" && this.nodes.get(this.selection.id)?.kind === "action" ? this.selection.id : null);
    }
  }

  async #connect(source, sourcePort, target, targetPort, slots = {}) {
    await this.#save(async () => {
      const previous = [...this.edges.values()].find((e) => e.source_id === source.id && e.source_port === sourcePort);
      const edge = await connect(this.kind, this.id, { source_id: source.id, source_port: sourcePort, target_id: target.id, target_port: targetPort, style: previous?.style, ...slots });
      for (const [id, old] of this.edges) if (old.source_id === source.id && old.source_port === sourcePort) this.edges.delete(id);
      this.edges.set(edge.id, edge);
    });
    this.canvas.drawEdges();
    this.#renderInspector();
  }

  async #removeEdge(id) {
    this.edges.delete(id);
    if (this.selection?.id === id) this.selection = null;
    this.canvas.select(this.selection);
    this.#renderInspector();
    await this.#save(() => disconnect(this.kind, this.id, id));
  }

  async #restyle(edge, style) {
    edge.style = style;
    this.canvas.drawEdges();
    this.#renderInspector();
    await this.#save(() => restyleEdge(this.kind, this.id, edge.id, style));
  }

  /** Fixed kinds (trigger, complete, output) come with the graph; the last one of each stays. */
  #isFixed(node) {
    if (!typeOf(node).fixed) return false;
    return [...this.nodes.values()].filter((n) => n.kind === node.kind).length <= 1;
  }

  /** Delete a node after confirming; a stage takes its actions with it. */
  requestDelete(selection) {
    if (selection.type === "edge") return this.#removeEdge(selection.id);
    const node = this.nodes.get(selection.id);
    if (!node || this.#isFixed(node)) return undefined;
    const inside = [...this.nodes.values()].filter((n) => n.stage_id === node.id).length;
    const extra = inside ? ` and its ${inside} action${inside === 1 ? "" : "s"}` : "";
    this.confirm.open({
      message: `Delete ${typeOf(node).label.toLowerCase()} "${displayName(node)}"${extra}? Its connections are removed too.`,
      onConfirm: async () => {
        await deleteNode(this.kind, this.id, node.id);
        await this.load();
        this.select(null);
      },
    });
    return undefined;
  }

  // ── inspector ──────────────────────────────────────────────────────

  #renderInspector() {
    const el = this.inspector;
    el.replaceChildren();
    const sel = this.selection;
    if (sel?.type === "node" && this.nodes.has(sel.id)) return this.#nodeInspector(this.nodes.get(sel.id));
    if (sel?.type === "edge" && this.edges.has(sel.id)) return this.#edgeInspector(this.edges.get(sel.id));
    return this.#graphInspector();
  }

  #graphInspector() {
    const count = (kind) => [...this.nodes.values()].filter((n) => n.kind === kind).length;
    this.inspector.append(
      heading(this.graph?.name ?? "Pipeline", "Draft", {
        label: this.isAction ? "Action name" : "Pipeline name",
        onCommit: (name) => this.#renameGraph(name),
      }),
      note(
        this.isAction
          ? "The trigger starts this action automatically; the output always offers On Pass and optionally On Fail."
          : `${count("stage")} stages, ${count("action")} actions. Select a node to edit it, drag from a port to connect.`,
      ),
    );
  }

  /** The title, then the building blocks the node's kind asks for (see node-types.js). */
  #nodeInspector(node) {
    const type = typeOf(node);
    const rename = type.renamable(node) ? { label: `${type.label} name`, onCommit: (name) => this.#rename(node, name) } : null;
    this.inspector.append(heading(displayName(node), type.caption(node) ?? type.label, rename));
    for (const block of type.sections(node, this.blocks)) if (block) this.inspector.append(block);
  }

  /** What the inspector blocks may do in this editor. */
  #blockActions() {
    return {
      currentId: this.id,
      setSetting: (node, key, value) => this.#setSetting(node, key, value),
      link: (node, targetId) => this.#link(node, targetId),
      askNew: (node) => this.#askNew(node),
      linkUrl: (node) => this.#linkUrl(node, node.definition_slug),
      remove: (node) => this.requestDelete({ type: "node", id: node.id }),
      addAction: (stage) => this.#addAction(stage),
      listTargets: (kind) => listGraphs(kind),
      showError: (message) => this.#showError(message),
    };
  }

  /** Where the thing a node links to is edited, with the way back to this node. */
  #linkUrl(node, slug) {
    const path = EDITOR_PATHS[typeOf(node).links_to];
    return `${path}/${encodeURIComponent(slug)}?from=${encodeURIComponent(this.graph.slug)}&node=${encodeURIComponent(node.id)}`;
  }

  async #link(node, targetId) {
    await this.#save(async () => {
      const updated = await updateNode(this.kind, this.id, node.id, { definition_id: targetId });
      Object.assign(node, {
        definition_id: updated.definition_id,
        definition_name: updated.definition_name,
        definition_slug: updated.definition_slug,
        definition_fail_enabled: updated.definition_fail_enabled,
      });
    });
    const type = typeOf(node);
    for (const [id, edge] of this.edges) {
      if (edge.source_id === node.id && !type.isVisible(node, edge.source_port)) this.edges.delete(id); // e.g. no On Fail
    }
    this.canvas.sync();
    this.#renderInspector();
  }

  /** The small window for the name of something new to link to (like creating an artifact on the board). */
  #askNew(node) {
    this.newDialog ??= this.#bindNewDialog();
    const what = typeOf(node).links_to === "action" ? "action" : "pipeline";
    this.newDialog.node = node;
    this.newDialog.title.textContent = `New ${what}`;
    this.newDialog.input.value = "";
    this.newDialog.error.hidden = true;
    this.newDialog.modal.open();
  }

  #bindNewDialog() {
    const root = document.getElementById("new-modal");
    const modal = new Modal(root);
    const input = document.getElementById("new-name");
    const error = document.getElementById("new-name-error");
    const dialog = { modal, input, error, title: root.querySelector(".modal__title"), node: null };
    input.addEventListener("input", () => (error.hidden = true));
    document.getElementById("new-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!input.value.trim()) {
        error.textContent = "Please enter a title.";
        error.hidden = false;
        input.focus();
        return;
      }
      modal.close();
      await this.#createAndOpen(dialog.node, input.value.trim());
    });
    return dialog;
  }

  /** Create what the node links to under the entered name, link the node to it and go and edit it. */
  async #createAndOpen(node, name) {
    let created = null;
    const saved = await this.#save(async () => {
      created = await createGraph(typeOf(node).links_to, name);
      await updateNode(this.kind, this.id, node.id, { definition_id: created.id });
    });
    if (saved && created) window.location.assign(this.#linkUrl(node, created.slug));
  }

  /** A select with every valid target of an output port: the keyboard way to connect.
   * Quarantined since 2026-11-21 (connections are made by dragging); see quarantine.json. */
  #routeSelect(node, port) {
    const select = document.createElement("select");
    select.className = "field__control";
    const none = new Option("Not connected", "");
    select.append(none);
    const current = [...this.edges.values()].find((e) => e.source_id === node.id && e.source_port === port);
    for (const target of this.nodes.values()) {
      for (const targetPort of typeOf(target).inputs.map((p) => p.name)) {
        if (!canConnect(node, port, target, targetPort)) continue;
        const label = targetPort === "end" ? `${target.name} · end of stage` : target.kind === "output" ? `${target.name} · ${typeOf(target).portLabel(targetPort)}` : displayName(target);
        const option = new Option(label, `${target.id}|${targetPort}`);
        select.append(option);
        if (current?.target_id === target.id && current.target_port === targetPort) option.selected = true;
      }
    }
    select.addEventListener("change", async () => {
      if (!select.value) {
        if (current) await this.#removeEdge(current.id);
        return;
      }
      const [targetId, targetPort] = select.value.split("|");
      await this.#connect(node, port, this.nodes.get(targetId), targetPort);
    });
    return select;
  }

  #edgeInspector(edge) {
    const source = this.nodes.get(edge.source_id);
    const target = this.nodes.get(edge.target_id);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button--ghost wf-delete";
    remove.textContent = "Delete connection";
    remove.addEventListener("click", () => this.#removeEdge(edge.id));
    const styles = document.createElement("div");
    styles.className = "wf-styles";
    styles.setAttribute("role", "group");
    styles.setAttribute("aria-label", "Line style");
    for (const [value, label] of Object.entries(EDGE_STYLES)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wf-style";
      button.dataset.style = value;
      button.textContent = label;
      button.setAttribute("aria-pressed", String(edge.style === value));
      button.addEventListener("click", () => this.#restyle(edge, value));
      styles.append(button);
    }
    this.inspector.append(
      heading("Connection", `${source ? displayName(source) : "?"} (${source ? typeOf(source).portLabel(edge.source_port) : "?"}) → ${target ? displayName(target) : "?"}`),
      field("Line", styles),
      remove,
    );
  }
}
