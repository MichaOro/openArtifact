/* The graph editor: connects the model, the canvas, the inspector and the dialogs. Changes are saved
 * at once; if the server refuses one, the graph is reloaded and the reason shown. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { InlineName } from "../components/inline-name.js";
import { Modal } from "../components/modal.js";
import { KEYS, removeStorage } from "../storage.js";
import { AddMenu } from "./add-menu.js";
import { createGraph, listGraphs } from "./api.js";
import { Canvas } from "./canvas.js";
import { TOP_LEVEL_GAP, actionsOf, displayName, fitStage, nextActionPosition, nextToolPosition, nextTopLevelPosition, sizeOf } from "./geometry.js";
import { GraphModel } from "./graph-model.js";
import { InspectorBlocks } from "./inspector.js";
import { InspectorPanel } from "./inspector-panel.js";
import { rememberPipeline, setupBack } from "./navigation.js";
import { typeOf } from "./node-types.js";

export class GraphEditor {
  #linkTurns = new Map(); // node id -> the number of the newest link request
  #linkQueue = new Map(); // node id -> the link request in flight (or done)

  /** @param {HTMLElement} root the element carrying data-graph-id */
  constructor(root) {
    this.root = root;
    this.model = new GraphModel(root.dataset.kind, root.dataset.graphId);
    this.nodes = this.model.nodes;
    this.edges = this.model.edges;
    this.paths = { pipeline: root.dataset.pipelinesPath, action: root.dataset.actionsPath }; // where each kind is edited
    this.selection = null;
    this.opened = false;
    this.titleName = null;
    this.targets = {}; // kind -> the pipelines / action definitions a node may link to

    this.alert = new AlertBar(root.querySelector("[data-alert]"));
    this.alert.onRetry(() => this.load());
    this.zoomLabel = root.querySelector("[data-zoom-label]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
    this.nameDialog = new FormDialog(new Modal(document.getElementById("new-modal")));
    this.blocks = new InspectorBlocks(this.#blockActions(), this.model);
    this.inspector = new InspectorPanel(root.querySelector("[data-inspector]"), this.blocks, this.model);
    this.canvas = new Canvas({
      viewport: root.querySelector("[data-viewport]"),
      nodes: this.nodes,
      edges: this.edges,
      handlers: {
        onSelect: (selection, options) => this.select(selection, options),
        onMoved: (node) => this.#persistPosition(node),
        onConnect: (source, port, target, targetPort, slots) => this.#connect(source, port, target, targetPort, slots),
        onDelete: (selection) => this.requestDelete(selection),
        onEdgeDelete: (id) => this.#removeEdge(id),
        onEdgeStyle: (edge, style) => this.#restyle(edge, style),
        onZoom: (zoom) => (this.zoomLabel.textContent = `${Math.round(zoom * 100)}%`),
      },
    });

    new AddMenu(root, this.model.kind, (kind) => (typeOf(kind).tool ? this.#addTool(kind) : this.#addBeforeEnd(kind)));
    root.querySelector("[data-zoom-in]").addEventListener("click", () => this.canvas.zoomBy(1.2));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => this.canvas.zoomBy(1 / 1.2));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => this.canvas.fit());
    this.canvas.viewport.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-action]");
      if (add) this.#addAction(this.nodes.get(add.closest(".ge-node").dataset.nodeId));
    });
    this.canvas.viewport.addEventListener("keydown", (event) => {
      // a focused node handles Delete itself (canvas.js); this is for a selected connection
      const deletes = event.key === "Delete" || event.key === "Backspace";
      if (deletes && this.selection?.type === "edge" && !event.target.closest(".ge-node, input, select")) {
        event.preventDefault();
        this.#removeEdge(this.selection.id);
      }
    });
  }

  // ── loading ────────────────────────────────────────────────────────

  async load({ fit = false } = {}) {
    try {
      await this.model.load();
      this.alert.hide();
      this.#showTitle();
      document.title = `${this.model.graph.name} · OpenArtifact`;
      this.canvas.sync();
      if (fit) this.canvas.fit();
      this.#renderInspector();
      if (!this.opened) this.#onFirstLoad();
      this.opened = true;
    } catch (error) {
      if (error.status === 404 && !this.model.isAction) removeStorage(KEYS.lastPipeline);
      this.#showError(error.status === 404 ? "This pipeline or action does not exist." : "It could not be loaded.", true);
    }
  }

  /** Opened from a node of a pipeline: offer the way back; back in a pipeline: select that node again. */
  async #onFirstLoad() {
    const params = new URLSearchParams(window.location.search);
    setupBack(this.root.querySelector("[data-back]"), this.paths.pipeline, params.get("from"), params.get("node")); // opened from a node of a pipeline
    if (this.model.isAction) return;
    this.#remember(null);
    const wanted = params.get("select");
    if (wanted && this.nodes.has(wanted)) {
      this.select({ type: "node", id: wanted });
      this.canvas.reveal(this.nodes.get(wanted));
      window.history.replaceState(null, "", window.location.pathname);
    }
  }

  /** The navigation reopens the last stage with its action selected. */
  #remember(nodeId) {
    if (!this.model.isAction && this.model.graph) rememberPipeline(this.model.graph.slug, nodeId);
  }

  #showError(message, retry = false) {
    this.alert.show(message, { retry });
  }

  /** Run a change; on failure show why and return to what the server has. */
  async #save(change) {
    try {
      await change();
      this.alert.hide();
      return true;
    } catch (error) {
      await this.load();
      this.#showError(error.detail ?? (error.status === 422 ? "That change is not allowed." : "The change could not be saved."));
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
    if (focusInspector) this.inspector.focusFirst();
  }

  #renderInspector() {
    this.inspector.render(this.selection);
  }

  // ── adding ─────────────────────────────────────────────────────────

  /** A new stage (or timer) goes right of the last one; the ending moves on if it is in the way. */
  async #addBeforeEnd(kind) {
    const created = await this.#create({ kind, ...nextTopLevelPosition(this.nodes, kind) });
    if (!created) return;
    const ending = [...this.nodes.values()].find((n) => typeOf(n).ending);
    const free = created.x + sizeOf(created).width + TOP_LEVEL_GAP;
    if (ending && ending.x < free) {
      ending.x = free;
      this.canvas.sync();
      await this.#save(() => this.model.updateNode(ending.id, { x: free }));
    }
    this.canvas.reveal(created);
  }

  /** A new tool hangs below the selected agent (or the last one, or the agent of the selected tool) and
   * is attached to it at once; without an agent it goes on the main line like any node. */
  async #addTool(kind) {
    let selected = this.selection?.type === "node" ? this.selection.id : null;
    const attached = [...this.edges.values()].find((e) => e.source_id === selected && e.target_port === "tools");
    if (attached) selected = attached.target_id;
    const spot = nextToolPosition(this.nodes, this.edges, selected);
    if (!spot) return this.#addBeforeEnd(kind);
    const created = await this.#create({ kind, x: spot.x, y: spot.y });
    if (!created) return;
    await this.#connect(created, "tool", this.nodes.get(spot.agentId), "tools");
    this.select({ type: "node", id: created.id });
    this.canvas.reveal(created);
  }

  async #addAction(stage) {
    const created = await this.#create({ kind: "action", stage_id: stage.id, ...nextActionPosition(stage, this.nodes) });
    if (created) await this.#growStage(stage);
  }

  async #create(fields) {
    let node = null;
    const saved = await this.#save(async () => {
      node = await this.model.addNode(fields);
      this.nodes.set(node.id, node);
    });
    if (!saved || !node) return null;
    this.canvas.sync();
    this.select({ type: "node", id: node.id });
    this.canvas.focusNode(node.id);
    return node;
  }

  async #growStage(stage) {
    const size = fitStage(stage, actionsOf(stage, this.nodes));
    if (size.width === stage.width && size.height === stage.height) return;
    Object.assign(stage, size);
    this.canvas.sync();
    await this.#save(() => this.model.updateNode(stage.id, size));
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
      await this.model.updateNode(node.id, fields);
      if (stage) await this.model.updateNode(stage.id, { width: stage.width, height: stage.height });
    });
  }

  /** The name in the page header, which can be renamed in place as well. */
  #showTitle() {
    const { graph, isAction } = this.model;
    if (this.titleName) {
      this.titleName.setText(graph.name);
      return;
    }
    const title = document.querySelector(".app-header__title");
    title.textContent = graph.name;
    this.titleName = new InlineName(title, { label: isAction ? "Action name" : "Pipeline name", onCommit: (name) => this.#renameGraph(name) });
  }

  async #rename(node, name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === node.name) return this.#renderInspector();
    node.name = trimmed;
    this.canvas.sync();
    await this.#save(() => this.model.updateNode(node.id, { name: trimmed }));
    return this.#renderInspector();
  }

  /**
   * Save one setting of a node: a column of the node, or a key of its `config` (the server's
   * description says which). Resolves to null, or to why the server refused it; a refusal changes
   * nothing here, so what the user typed stays in the inspector.
   */
  async #saveSetting(node, setting, value) {
    const inConfig = setting.stored_in === "config";
    try {
      const updated = await this.model.updateNode(node.id, inConfig ? { config: { [setting.key]: value } } : { [setting.key]: value });
      if (inConfig) node.config = updated.config;
      else node[setting.key] = updated[setting.key];
    } catch (error) {
      return error.detail ?? Object.values(error.fieldErrors ?? {})[0] ?? error.message;
    }
    this.model.dropHiddenEdges(node); // connections at ports that are gone with it (e.g. no On Fail)
    this.canvas.sync();
    this.alert.hide();
    return null;
  }

  async #renameGraph(name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === this.model.graph.name) return this.#renderInspector();
    this.model.graph.name = trimmed;
    this.#showTitle();
    const saved = await this.#save(async () => {
      this.model.graph = await this.model.rename(trimmed);
    });
    if (saved) {
      window.history.replaceState(null, "", `${window.location.pathname.replace(/[^/]+$/, "")}${encodeURIComponent(this.model.graph.slug)}`);
      this.#remember(this.selection?.type === "node" && this.nodes.get(this.selection.id)?.kind === "action" ? this.selection.id : null);
    }
    return undefined;
  }

  async #connect(source, sourcePort, target, targetPort, slots = {}) {
    await this.#save(async () => {
      const previous = this.model.edgeFrom(source.id, sourcePort);
      const edge = await this.model.connect({ source_id: source.id, source_port: sourcePort, target_id: target.id, target_port: targetPort, style: previous?.style, ...slots });
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
    await this.#save(() => this.model.disconnect(id));
  }

  async #restyle(edge, style) {
    edge.style = style;
    this.canvas.drawEdges();
    this.#renderInspector();
    await this.#save(() => this.model.restyle(edge.id, style));
  }

  /** Delete a node after confirming; a stage takes its actions with it. */
  requestDelete(selection) {
    if (selection.type === "edge") return this.#removeEdge(selection.id);
    const node = this.nodes.get(selection.id);
    if (!node) return undefined;
    if (this.model.isFixed(node)) {
      this.#showError(`The ${typeOf(node).label.toLowerCase()} cannot be deleted.`);
      return undefined;
    }
    const inside = actionsOf(node, this.nodes).length;
    const extra = inside ? ` and its ${inside} action${inside === 1 ? "" : "s"}` : "";
    this.confirm.open({
      message: `Delete ${typeOf(node).label.toLowerCase()} "${displayName(node)}"${extra}? Its connections are removed too.`,
      onConfirm: async () => {
        await this.model.deleteNode(node.id);
        await this.load();
        this.select(null);
      },
      onClose: () => this.canvas.viewport.focus({ preventScroll: true }), // the node that had focus is gone
    });
    return undefined;
  }

  // ── what the inspector may do ──────────────────────────────────────

  #blockActions() {
    return {
      saveSetting: (node, setting, value) => this.#saveSetting(node, setting, value),
      suggestions: (node) => ({ nodes: () => [...this.nodes.values()], exceptId: node.id }),
      link: (node, targetId) => this.#link(node, targetId),
      askNew: (node) => this.#askNew(node),
      linkUrl: (node) => this.#linkUrl(node, node.definition_slug),
      remove: (node) => this.requestDelete({ type: "node", id: node.id }),
      addAction: (stage) => this.#addAction(stage),
      listTargets: (kind) => this.#listTargets(kind),
      showError: (message) => this.#showError(message),
      renameNode: (node, name) => this.#rename(node, name),
      renameGraph: (name) => this.#renameGraph(name),
      removeEdge: (id) => this.#removeEdge(id),
      restyle: (edge, style) => this.#restyle(edge, style),
    };
  }

  /** The things a node may link to, fetched once until something new is created. */
  #listTargets(kind) {
    this.targets[kind] ??= listGraphs(kind).catch((error) => {
      delete this.targets[kind];
      throw error;
    });
    return this.targets[kind];
  }

  /** Where the thing a node links to is edited, with the way back to this node. */
  #linkUrl(node, slug) {
    const path = this.paths[typeOf(node).links_to];
    return `${path}/${encodeURIComponent(slug)}?from=${encodeURIComponent(this.model.graph.slug)}&node=${encodeURIComponent(node.id)}`;
  }

  /** Links of one node are sent one after the other, and only the newest one is shown, so the screen
   * always agrees with the server's last word however quickly the choice is changed. */
  #link(node, targetId) {
    const turn = (this.#linkTurns.get(node.id) ?? 0) + 1;
    this.#linkTurns.set(node.id, turn);
    const queued = (this.#linkQueue.get(node.id) ?? Promise.resolve()).then(() => this.#sendLink(node, targetId, turn));
    this.#linkQueue.set(node.id, queued);
    return queued;
  }

  async #sendLink(node, targetId, turn) {
    const newest = () => this.#linkTurns.get(node.id) === turn;
    await this.#save(async () => {
      const updated = await this.model.updateNode(node.id, { definition_id: targetId });
      if (!newest()) return; // a later choice is already queued: its answer is the one to show
      Object.assign(node, {
        definition_id: updated.definition_id,
        definition_name: updated.definition_name,
        definition_slug: updated.definition_slug,
        definition_fail_enabled: updated.definition_fail_enabled,
      });
    });
    if (!newest()) return;
    this.model.dropHiddenEdges(node); // e.g. no On Fail
    this.canvas.sync();
    this.#renderInspector();
  }

  /** Ask for the name of something new to link to (like creating an artifact on the board). */
  #askNew(node) {
    const what = typeOf(node).links_to === "action" ? "action" : "pipeline";
    this.nameDialog.open({ title: `New ${what}`, onSubmit: ({ name }) => this.#createAndOpen(node, name) });
  }

  /** Create what the node links to under the entered name, link the node to it and go and edit it. */
  async #createAndOpen(node, name) {
    const created = await createGraph(typeOf(node).links_to, name);
    this.targets = {};
    await this.model.updateNode(node.id, { definition_id: created.id });
    window.location.assign(this.#linkUrl(node, created.slug));
  }
}
