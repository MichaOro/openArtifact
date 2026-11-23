/* The graph editor: connects the model, the canvas, the inspector and the dialogs. Changes are saved
 * at once; if the server refuses one, the graph is reloaded and the reason shown. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { InlineName } from "../components/inline-name.js";
import { Modal } from "../components/modal.js";
import { KEYS, readJson, removeStorage, writeJson } from "../storage.js";
import { ActionMenu } from "../components/action-menu.js";
import { AddMenu } from "./add-menu.js";
import { createGraph, listGraphs } from "./api.js";
import { Canvas } from "./canvas.js";
import { copyOf, pastePlan } from "./clipboard.js";
import { TOP_LEVEL_GAP, actionsOf, displayName, fitStage, nextActionPosition, nextToolPosition, nextTopLevelPosition, sizeOf } from "./geometry.js";
import { GraphModel } from "./graph-model.js";
import { InspectorBlocks } from "./inspector.js";
import { InspectorPanel } from "./inspector-panel.js";
import { rememberPipeline, setupBack, setupBackToAgent } from "./navigation.js";
import { addableIn, typeOf } from "./node-types.js";

export class GraphEditor {
  #pasteQueue = Promise.resolve(); // pastes run one after the other, so each sees the names the one before made
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
    this.settingsModal = new Modal(document.getElementById("node-modal"));
    this.inspector = new InspectorPanel(document.querySelector("#node-modal [data-inspector]"), this.blocks, this.model);
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
        onNodeAction: (action, node, button) => this.#nodeAction(action, node, button),
        onNodeMenu: (node, point) => this.#openNodeMenu(node, point),
      },
    });
    this.menu = new ActionMenu();
    this.pastes = 0; // how often the same copy was pasted: each paste is placed a little further

    new AddMenu(root, this.model.kind, (kind) => (typeOf(kind).tool ? this.#addTool(kind) : this.#addBeforeEnd(kind)));
    root.querySelector("[data-zoom-in]").addEventListener("click", () => this.canvas.zoomBy(1.2));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => this.canvas.zoomBy(1 / 1.2));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => this.canvas.fit());
    this.canvas.viewport.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-action]");
      if (add) this.#addAction(this.nodes.get(add.closest(".ge-node").dataset.nodeId));
    });
    this.canvas.viewport.addEventListener("dblclick", (event) => this.#openSettingsAt(event));
    document.addEventListener("keydown", (event) => this.#onShortcut(event)); // wherever the focus is, as long as nothing else wants the key
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
    const back = this.root.querySelector("[data-back]");
    if (params.get("agent")) setupBackToAgent(back, params.get("agent")); // opened from the agent's "Used by"
    else setupBack(back, this.paths.pipeline, params.get("from"), params.get("node")); // opened from a node of a pipeline
    if (!this.model.isAction) this.#remember(null);
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

  /** Select a node or a connection (or nothing). `keepMulti`: the selection holds several nodes (a frame was drawn);
   * `focusInspector` (Enter on a node) opens the node's settings. */
  select(selection, { focusInspector = false, keepMulti = null } = {}) {
    this.selection = selection;
    const picked = selection?.type === "node" ? this.nodes.get(selection.id) : null;
    this.#remember(picked?.kind === "action" ? picked.id : null);
    this.canvas.select(selection, { multi: keepMulti });
    if (selection?.type === "edge") this.canvas.viewport.focus({ preventScroll: true }); // so Delete reaches it
    if (!picked) this.settingsModal.close();
    else if (focusInspector) this.#openSettings(picked);
    else this.#renderInspector();
  }

  /** The settings of a node in an overlay: the node's title (renamed in place) and what its kind offers. */
  #openSettings(node, { rename = false } = {}) {
    if (this.selection?.id !== node.id) this.select({ type: "node", id: node.id });
    this.settingsModal.dialog.querySelector(".modal__title").textContent = typeOf(node).label;
    this.inspector.render(this.selection);
    this.settingsModal.open();
    this.inspector.focusFirst();
    if (rename) this.settingsModal.dialog.querySelector(".ge-inspector__heading h2")?.click(); // the title is edited in place
  }

  #renderInspector() {
    if (!this.settingsModal.isOpen) return;
    if (this.selection?.type !== "node" || !this.nodes.has(this.selection.id)) return this.settingsModal.close();
    return this.inspector.render(this.selection);
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
    const several = [...this.canvas.multi].filter((id) => this.nodes.has(id) && !typeOf(this.nodes.get(id)).fixed);
    if (several.length > 1 && this.canvas.multi.has(selection.id)) return this.#deleteMany(several);
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

  // ── the bar, the menu and the keys of a node ───────────────────────

  /** The nodes an action is for: the selected ones when the node is one of them, else the node alone. */
  #targets(node) {
    const chosen = [...this.canvas.multi].map((id) => this.nodes.get(id)).filter(Boolean);
    return chosen.length > 1 && this.canvas.multi.has(node.id) ? chosen : [node];
  }

  #nodeAction(action, node, button) {
    if (action === "edit") this.#openSettings(node);
    else if (action === "delete") this.#deleteTargets(this.#targets(node));
    else this.#openNodeMenu(node, null, button);
  }

  /** The menu of a node: opened by a right click (at the pointer) or by the "..." of its bar (under it). */
  #openNodeMenu(node, point, trigger = null) {
    if (!this.canvas.multi.has(node.id)) this.select({ type: "node", id: node.id });
    const targets = this.#targets(node);
    const several = targets.length > 1;
    const fixed = targets.some((n) => typeOf(n).fixed);
    const copyable = targets.some((n) => !typeOf(n).fixed);
    const reasonFixed = "The trigger, the output and the end are part of the graph";
    const renameReason = several ? "Select one node to rename it" : typeOf(node).renamable(node) ? undefined : "This node is named by what it links to";
    const items = [
      { label: "Edit", icon: "pencil", shortcut: "Enter", disabledReason: several ? "Select one node to edit it" : undefined, onSelect: () => this.#openSettings(node) },
      { label: "Rename", icon: "tag", shortcut: "F2", disabledReason: renameReason, onSelect: () => this.#openSettings(node, { rename: true }) },
      { label: "Copy", icon: "copy", shortcut: "Ctrl+C", disabledReason: copyable ? undefined : reasonFixed, onSelect: () => this.#copy(targets) },
      { label: "Cut", icon: "copy", shortcut: "Ctrl+X", disabledReason: copyable && !fixed ? undefined : reasonFixed, onSelect: () => this.#cut(targets) },
      { label: "Duplicate", icon: "layers", shortcut: "Ctrl+D", disabledReason: copyable ? undefined : reasonFixed, onSelect: () => this.#duplicate(targets) },
      { label: "Delete", icon: "trash", shortcut: "Del", danger: true, disabledReason: fixed ? reasonFixed : undefined, onSelect: () => this.#deleteTargets(targets) },
    ];
    const anchor = trigger ?? this.canvas.elements.get(node.id);
    this.menu.toggle(anchor, items, `Actions of ${displayName(node)}`, point ? { at: point } : {});
  }

  /** Ctrl+C / X / V / D, F2 and Delete on the canvas. */
  #onShortcut(event) {
    if (event.target.closest("input, select, textarea, button, [contenteditable]") || this.menu.isOpen || document.querySelector("dialog[open]")) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    const chosen = [...this.canvas.multi].map((id) => this.nodes.get(id)).filter(Boolean);
    if (mod && key === "v") {
      event.preventDefault();
      this.#paste();
    } else if (mod && (key === "c" || key === "x" || key === "d") && chosen.length) {
      event.preventDefault();
      if (key === "c") this.#copy(chosen);
      else if (key === "x") this.#cut(chosen);
      else this.#duplicate(chosen);
    } else if (event.key === "F2" && chosen.length === 1 && typeOf(chosen[0]).renamable(chosen[0])) {
      event.preventDefault();
      this.#openSettings(chosen[0], { rename: true });
    }
  }

  #deleteTargets(targets) {
    const deletable = targets.filter((n) => !typeOf(n).fixed);
    if (deletable.length > 1) return this.#deleteMany(deletable.map((n) => n.id));
    if (deletable.length === 1) return this.requestDelete({ type: "node", id: deletable[0].id });
    this.#showError("The trigger, the output and the end cannot be deleted.");
    return undefined;
  }

  #deleteMany(ids) {
    const nodes = ids.map((id) => this.nodes.get(id)).filter(Boolean);
    this.confirm.open({
      message: `Delete ${nodes.length} nodes? Their connections are removed too.`,
      onConfirm: async () => {
        for (const node of nodes) if (this.nodes.has(node.id)) await this.model.deleteNode(node.id);
        await this.load();
        this.select(null);
      },
      onClose: () => this.canvas.viewport.focus({ preventScroll: true }),
    });
  }

  // ── copy, cut, paste, duplicate ────────────────────────────────────

  #copy(targets) {
    const copy = copyOf([...this.nodes.values()], [...this.edges.values()], targets.map((n) => n.id), this.model.kind);
    if (!copy) {
      this.#showError("The trigger, the output and the end cannot be copied.");
      return false;
    }
    writeJson(KEYS.nodeClipboard, copy);
    this.pastes = 0;
    this.alert.show(`${copy.nodes.length} ${copy.nodes.length === 1 ? "node" : "nodes"} copied. Paste with Ctrl+V.`, { autoHide: 2500 });
    return true;
  }

  async #cut(targets) {
    if (!this.#copy(targets)) return;
    const gone = targets.filter((n) => !typeOf(n).fixed);
    await this.#save(async () => {
      for (const node of gone) if (this.nodes.has(node.id)) await this.model.deleteNode(node.id);
    });
    await this.load();
    this.select(null);
    this.canvas.viewport.focus({ preventScroll: true }); // the node that had focus is gone: keys keep working
  }

  async #duplicate(targets) {
    const copy = copyOf([...this.nodes.values()], [...this.edges.values()], targets.map((n) => n.id), this.model.kind);
    if (copy) await this.#pasteCopy(copy, 1);
  }

  async #paste() {
    const copy = readJson(KEYS.nodeClipboard);
    if (!copy?.nodes?.length) {
      this.#showError("Nothing copied yet: select a node and press Ctrl+C.");
      return;
    }
    this.pastes += 1;
    await this.#pasteCopy(copy, this.pastes);
  }

  /** Create what a copy holds, with its connections, and select it. `times` places repeated pastes further along. */
  #pasteCopy(copy, times) {
    this.#pasteQueue = this.#pasteQueue.then(() => this.#doPaste(copy, times));
    return this.#pasteQueue;
  }

  async #doPaste(copy, times) {
    const selected = this.selection?.type === "node" ? this.nodes.get(this.selection.id) : null;
    const stages = [...this.nodes.values()].filter((n) => n.kind === "stage");
    const plan = pastePlan(copy, {
      offset: 40 * times,
      names: new Set([...this.nodes.values()].map((n) => n.name)),
      stageFor: (old) => (this.nodes.has(old) ? old : selected?.kind === "stage" ? selected.id : selected?.stage_id ?? null),
      allowed: new Set([...addableIn(this.model.kind).map((t) => t.kind), ...(this.model.kind === "pipeline" ? ["action"] : [])]), // an action is made inside its stage, not by the menu
    });
    if (plan.error) return this.#showError(plan.error);
    if (!plan.items.length) return this.#showError(`${plan.skipped.map((k) => typeOf(k)?.label ?? k).join(", ")} cannot be added here.`);
    const made = new Map();
    const saved = await this.#save(async () => {
      for (const item of plan.items) {
        const fields = { kind: item.kind, name: item.name, x: item.x, y: item.y, config: item.config };
        const parent = item.stage ? made.get(item.stage) : item.existingStage;
        if (parent) fields.stage_id = parent;
        if (item.seconds != null) fields.seconds = item.seconds;
        const node = await this.model.addNode(fields);
        const extra = {};
        if (item.definition_id) extra.definition_id = item.definition_id;
        if (item.kind === "stage" && item.width) Object.assign(extra, { width: item.width, height: item.height });
        Object.assign(node, Object.keys(extra).length ? await this.model.updateNode(node.id, extra) : {});
        this.nodes.set(node.id, node);
        made.set(item.key, node.id);
      }
      for (const link of plan.edges) {
        const edge = await this.model.connect({ source_id: made.get(link.source), source_port: link.source_port, source_slot: link.source_slot, target_id: made.get(link.target), target_port: link.target_port, target_slot: link.target_slot, style: link.style });
        this.edges.set(edge.id, edge);
      }
      // a tool pasted without its agent hangs on the agent it was copied from, if that agent is in this graph
      for (const item of plan.items.filter((i) => typeOf(i.kind)?.tool)) {
        const agent = copy.attached?.[item.key];
        if (agent && this.nodes.has(agent)) {
          const edge = await this.model.connect({ source_id: made.get(item.key), source_port: "tool", target_id: agent, target_port: "tools" });
          this.edges.set(edge.id, edge);
        }
      }
    });
    if (!saved) return undefined;
    this.canvas.sync();
    const ids = new Set(made.values());
    const first = [...ids][0];
    this.select({ type: "node", id: first }, { keepMulti: ids });
    this.canvas.focusNode(first); // so the bar of the node it was copied from goes away
    if (plan.skipped.length) this.#showError(`${plan.skipped.map((k) => typeOf(k)?.label ?? k).join(", ")} cannot be added here and was left out.`);
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

  /** A double click on a node opens its settings (an action or pipeline node offers "Edit" there to open what it links to). */
  #openSettingsAt(event) {
    // the canvas captures the pointer while a gesture runs, which makes the viewport the target of the click: look under the pointer
    const under = document.elementFromPoint(event.clientX, event.clientY);
    const el = under?.closest(".ge-node");
    if (!el || under.closest("button, input, select, a, .ge-port")) return;
    const node = this.nodes.get(el.dataset.nodeId);
    if (node) this.#openSettings(node);
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
