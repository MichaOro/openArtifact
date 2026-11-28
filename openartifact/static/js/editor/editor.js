/* The graph editor: connects the model, the canvas, the inspector and the dialogs. Changes are saved
 * at once; if the server refuses one, the graph is reloaded and the reason shown. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { setCredentialConfirm } from "../components/credential-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { InlineName } from "../components/inline-name.js";
import { Modal } from "../components/modal.js";
import { WindowLayout } from "../components/window-layout.js";
import { KEYS, readJson, removeStorage, writeJson } from "../storage.js";
import { ActionMenu } from "../components/action-menu.js";
import { AddMenu } from "./add-menu.js";
import { getAgent } from "../agents/api.js";
import { createGraph, listGraphs, loadContract, loadGraph } from "./api.js";
import { Canvas } from "./canvas.js";
import { ATTACHMENT_SOURCE_PORT, ATTACHMENT_TARGET_PORT, attachmentLink, kindOfEdge } from "./edge-kinds.js";
import { copyOf, pastePlan, remappedConfig } from "./clipboard.js";
import { ConnectMenu } from "./connect-menu.js";
import { choosePort, connectionFor, placement, replacedEdges } from "./connect-plan.js";
import { TOP_LEVEL_GAP, actionsOf, displayName, fitStage, nextActionPosition, nextToolPosition, nextTopLevelPosition, sizeOf } from "./geometry.js";
import { GraphModel } from "./graph-model.js";
import { DryRunPanel } from "./dry-run-panel.js";
import { StatusBar } from "../components/status-bar.js";
import { LAST } from "../components/icon-list-model.js";
import { StatusPopup } from "../components/status-popup.js";
import { ObserveBar } from "./observe-bar.js";
import { ObserveStore } from "./observe-store.js";
import { PublicationControl } from "./publication-control.js";
import { lastResult } from "./api.js";
import { mockActive, mockable } from "./mock-model.js";
import { drawPencil, drawPin } from "./mock-chrome.js";
import { InspectorBlocks, joinFooter } from "./inspector.js";
import { InspectorPanel } from "./inspector-panel.js";
import { flushDirty } from "./persist-policy.js";
import { rememberPipeline, setupBack, setupBackToAgent, setupBackToGuard } from "./navigation.js";
import { EditorGuards } from "./guards.js";
import { nodeWindowStructure } from "./node-layout.js";
import { addableIn, loadNodeTypes, placeholderOf, typeOf } from "./node-types.js";
import { forgetOpened } from "./settings-layout.js";
import { followContracts, followGraphChanges, needsReload, noticeText } from "./error-output-sync.js";
import { t, tn } from "../i18n.js";

export class GraphEditor {
  #pasteQueue = Promise.resolve(); // pastes run one after the other, so each sees the names the one before made
  #linkTurns = new Map(); // node id -> the number of the newest link request
  #linkQueue = new Map(); // node id -> the link request in flight (or done)
  #lastLinkAnswer = null; // the server's answer to the newest link request (its notices)

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
    this.publication = null; // the mark in the toolbar and its popup (publication-control.js)
    this.targets = {}; // kind -> the pipelines / action definitions a node may link to

    this.alert = new AlertBar(root.querySelector("[data-alert]"));
    this.alert.onRetry(() => this.load());
    this.zoomLabel = root.querySelector("[data-zoom-label]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
    setCredentialConfirm((options) => this.confirm.open({ ...options, tone: "primary" })); // the credential window asks before it resets its layout
    this.nameDialog = new FormDialog(new Modal(document.getElementById("new-modal")));
    this.blocks = new InspectorBlocks(this.#blockActions(), this.model);
    this.settingsModal = new Modal(document.getElementById("node-modal"));
    this.inspector = new InspectorPanel(document.querySelector("#node-modal [data-inspector]"), this.blocks, this.model);
    // the layout handle of a node's settings window (ADR-063): arranging its sides and settings, saved for the kind
    this.layout = new WindowLayout({
      panel: this.settingsModal.dialog.querySelector(".modal__panel"),
      content: this.inspector.element,
      window: null,
      structure: () => nodeWindowStructure(this.#layoutType()),
      customised: () => Boolean(this.#layoutType()?.layout_customised),
      reload: async () => {
        await loadNodeTypes();
        if (this.settingsModal.isOpen) this.#renderSettings();
      },
      confirm: ({ message, confirmLabel, onConfirm }) => this.confirm.open({ message, confirmLabel, tone: "primary", onConfirm: async () => onConfirm() }),
    });
    this.settingsModal.dialog.addEventListener("close", () => this.layout.cancel());
    const canClose = this.settingsModal.canClose;
    this.settingsModal.canClose = () => {
      flushDirty(); // text typed and not left yet is saved first: a blur may not come when the dialog goes away
      return this.layout.guardClose(() => this.settingsModal.close()) && canClose();
    };
    this.canvas = new Canvas({
      viewport: root.querySelector("[data-viewport]"),
      nodes: this.nodes,
      edges: this.edges,
      handlers: {
        onSelect: (selection, options) => this.select(selection, options),
        onMoved: (node) => this.#persistPosition(node),
        onResized: (node) => this.#persistSize(node),
        onConnect: (source, port, target, targetPort, slots) => this.#connect(source, port, target, targetPort, slots),
        onConnectRelease: (origin) => this.connectMenu.open(origin),
        onDelete: (selection) => this.requestDelete(selection),
        onEdgeDelete: (id) => this.#removeEdge(id),
        onEdgeStyle: (edge, style) => this.#restyle(edge, style),
        onZoom: (zoom) => (this.zoomLabel.textContent = `${Math.round(zoom * 100)}%`),
        onNodeAction: (action, node, button) => this.#nodeAction(action, node, button),
        onNodeMenu: (node, point) => this.#openNodeMenu(node, point),
        onNodeDrawn: (node, el) => {
          this.guards?.decorate(node, el);
          this.#drawMockPin(node, el);
        },
      },
    });
    this.menu = new ActionMenu();
    this.pastes = 0; // how often the same copy was pasted: each paste is placed a little further

    const addMenu = new AddMenu(
      root,
      this.model.kind,
      (kind) => (typeOf(kind).tool ? this.#addTool(kind) : this.#addBeforeEnd(kind)),
      (key) => key === "guard" && this.guards?.add(this.guards.rootType, this.model.graph.id, root.querySelector("[data-add-menu]")),
    );
    // a line released on the empty canvas opens the same menu at the pointer (connect-menu.js)
    this.addMenu = addMenu;
    this.connectMenu = new ConnectMenu({ addMenu, scope: this.model.kind, nodes: this.nodes, onChoose: (choice) => this.#addFromPort(choice), purpose: () => this.model.graph?.purpose ?? null });
    this.#setUpBar(root);
    this.#setUpGuards(root);
    followGraphChanges(this.model.id, () => this.load()); // a definition or a use changed elsewhere (ADR-061 addendum)
    followContracts((graphId) => this.#contractChanged(graphId)); // an action this pipeline places was published or its draft discarded (ADR-083 add. 2)
    root.querySelector("[data-zoom-in]").addEventListener("click", () => this.canvas.zoomBy(1.2));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => this.canvas.zoomBy(1 / 1.2));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => this.canvas.fit());
    this.canvas.viewport.addEventListener("click", (event) => {
      const add = event.target.closest("[data-stage-add]");
      if (add) this.#openStageAddMenu(this.nodes.get(add.closest(".ge-node").dataset.nodeId), add);
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
      await this.#loadContracts();
      await this.#loadAnswerFormats();
      this.addMenu.setPurpose(this.model.graph?.purpose ?? null); // an action for guards offers the kinds for guards
      this.alert.hide();
      this.#showTitle();
      this.#showPublication();
      document.title = t("editor.editor.name_openartifact", { name: this.model.graph.name });
      this.canvas.sync();
      if (fit) this.canvas.fit();
      this.#renderInspector();
      this.guards?.load(); // after a node went, the guards attached to it went too
      this.observe?.refresh(); // the draft may differ from the published mode now
      if (!this.opened) this.#onFirstLoad();
      this.opened = true;
    } catch (error) {
      if (error.status === 404 && !this.model.isAction) removeStorage(KEYS.lastPipeline);
      this.#showError(error.status === 404 ? t("editor.editor.pipeline_action_does_not_exist") : t("editor.editor.could_not_be_loaded"), true);
    }
  }

  /** The inputs and outputs the action definitions of this pipeline declare (ADR-083), by definition id, as the version that RUNS declares them
   * (published, not the draft: ADR-083 add. 2): what the reference list offers of a placement and what its mapping rows ask. A definition that
   * cannot be read is simply not in it. */
  async #loadContracts() {
    this.contracts = new Map();
    if (this.model.isAction) return;
    const placed = [...this.nodes.values()].filter((n) => (n.kind === "action" || n.kind === "pipeline") && n.definition_id);
    const found = new Map(placed.map((n) => [n.definition_id, n.kind]));
    await Promise.allSettled(
      [...found].map(async ([id, kind]) => {
        // the contract of the version that RUNS: the published one while the action has unpublished changes (ADR-083 add. 2)
        const found = await loadContract(kind, id);
        this.contracts.set(id, { inputs: found.inputs ?? [], outputs: (found.outputs ?? []).map((o) => o.name) });
      }),
    );
  }

  /** The answer format of each agent an agent node of this graph runs (ADR-085), by agent id: its published format, as far as the reference
   * list offers `data.NAME` of such a node. An agent that cannot be read is simply not in it. */
  async #loadAnswerFormats() {
    this.answerFormats = new Map();
    const ids = new Set([...this.nodes.values()].filter((n) => n.kind === "agent" && n.config?.agent_id).map((n) => n.config.agent_id));
    await Promise.allSettled(
      [...ids].map(async (id) => {
        const detail = await getAgent(id);
        this.answerFormats.set(id, (detail.published?.answer_format ?? []).map((f) => f.name));
      }),
    );
  }

  /** The names of the fields an agent node reports as its data: its own format when it sets one (an empty one switches the agent's off),
   * else the agent's. */
  #answersOf(node) {
    if (node.kind !== "agent") return [];
    const own = node.config?.answer_format;
    if (Array.isArray(own)) return own.map((f) => f.name);
    return this.answerFormats?.get(node.config?.agent_id) ?? [];
  }

  /** An action this pipeline places was published, or its draft was discarded: read the contracts again and draw the open window anew, so the
   * mapping rows show the inputs of what runs now. Nothing else of the editor moves. */
  async #contractChanged(graphId) {
    if (this.model.isAction || !this.contracts?.has(graphId)) return;
    await this.#loadContracts();
    this.inspector.render(this.selection);
  }

  /** What an action or pipeline node reads as a contract: `{outputs}` when what it runs declares inputs or outputs, else null. */
  #contractOf(node) {
    const found = (node.kind === "action" || node.kind === "pipeline") && node.definition_id ? this.contracts?.get(node.definition_id) : null;
    return found && (found.inputs.length || found.outputs.length) ? { outputs: found.outputs } : null;
  }

  /** Opened from a node of a pipeline: offer the way back; back in a pipeline: select that node again. */
  async #onFirstLoad() {
    const params = new URLSearchParams(window.location.search);
    const back = this.root.querySelector("[data-back]");
    if (params.get("agent")) setupBackToAgent(back, params.get("agent")); // opened from the agent's "Used by"
    else if (params.get("guard")) setupBackToGuard(back, params.get("guard")); // opened from the guard editor (ADR-060)
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
      this.#showError(error.detail ?? (error.status === 422 ? t("editor.editor.change_not_allowed") : t("editor.editor.change_could_not_be_saved")));
      return false;
    }
  }

  // ── selection ──────────────────────────────────────────────────────

  /** Select a node or a connection (or nothing). `keepMulti`: the selection holds several nodes (a frame was drawn);
   * `focusInspector` (Enter on a node) opens the node's settings. */
  select(selection, { focusInspector = false, keepMulti = null } = {}) {
    if (this.selection?.id !== selection?.id) flushDirty(); // unsaved text of the node that is left is saved first
    this.selection = selection;
    const picked = selection?.type === "node" ? this.nodes.get(selection.id) : null;
    this.#remember(picked?.kind === "action" ? picked.id : null);
    this.canvas.select(selection, { multi: keepMulti });
    if (selection?.type === "edge") this.canvas.viewport.focus({ preventScroll: true }); // so Delete reaches it
    if (!picked) this.settingsModal.close();
    else if (focusInspector) this.#openNode(picked);
    else this.#renderInspector();
  }

  /**
   * What opening a node does (a double click, Enter, the menu's Edit): a node that links to an action or a pipeline opens
   * what it links to in its own editor (what "Edit" in its settings does); a node that links to nothing yet, and every
   * other kind, opens its settings. The settings of a linking node (which definition, New, Delete) stay one menu entry away.
   */
  #openNode(node) {
    if (typeOf(node).links_to && node.definition_id && node.definition_slug) {
      window.location.assign(this.#linkUrl(node, node.definition_slug));
      return;
    }
    this.nodeTab = "settings"; // a window opened by a double click starts at the settings (the pin and the pencil open the Mock tab)
    this.#openSettings(node);
  }

  /** The settings of a node in an overlay: the node's title (renamed in place) and what its kind offers. */
  #openSettings(node) {
    if (this.selection?.id !== node.id) this.select({ type: "node", id: node.id });
    this.layoutKind = node.kind;
    drawPencil(this.settingsModal.dialog, mockable(typeOf(node), node), () => {
      this.nodeTab = "mock";
      this.#renderSettings();
    });
    this.layout.setWindow(typeOf(node).settings?.length ? `nodes/${node.kind}` : null);
    this.settingsModal.dialog.querySelector(".modal__title").textContent = typeOf(node).label;
    forgetOpened(node.id); // what was added but never given a value is not kept
    this.#renderSettings();
    this.settingsModal.open();
    this.inspector.focusFirst();
  }

  /** The view of the kind whose settings window is open (what the layout handle arranges). */
  #layoutType() {
    return typeOf(this.layoutKind);
  }

  #renderInspector() {
    if (!this.settingsModal.isOpen) return;
    if (this.selection?.type !== "node" || !this.nodes.has(this.selection.id)) return this.settingsModal.close();
    this.#renderSettings();
  }

  /** The settings of the selected node; the settings of what a guard can watch (an action in a pipeline, a node in an
   * action) end with the guards that watch it (ADR-060). */
  #renderSettings() {
    this.inspector.onDrawn = () => {
      const node = this.selection?.type === "node" ? this.nodes.get(this.selection.id) : null;
      const watchable = node && ["action", "node"].includes(this.guards?.scopeTypeOf(node));
      if (watchable) {
        this.inspector.element.append(this.guards.section(node));
        joinFooter(this.inspector.element);
      }
    };
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
    const attached = [...this.edges.values()].find((e) => e.source_id === selected && kindOfEdge(e).hangs);
    if (attached) selected = attached.target_id;
    const spot = nextToolPosition(this.nodes, this.edges, selected);
    if (!spot) return this.#addBeforeEnd(kind);
    const created = await this.#create({ kind, x: spot.x, y: spot.y });
    if (!created) return;
    await this.#connect(created, ATTACHMENT_SOURCE_PORT, this.nodes.get(spot.agentId), ATTACHMENT_TARGET_PORT);
    this.select({ type: "node", id: created.id });
    this.canvas.reveal(created);
  }

  async #addAction(stage) {
    const created = await this.#create({ kind: "action", stage_id: stage.id, ...nextActionPosition(stage, this.nodes) });
    if (created) await this.#growStage(stage);
  }

  /**
   * A kind chosen from the menu of a line released on the canvas (connect-menu.js): make the node where the line ended and
   * connect it at once. The connection that already left the dragged output is dissolved (the server replaces it) and the
   * notice names it; if the server refuses, its message is shown, the new node is taken back and nothing else changed.
   */
  async #addFromPort({ origin, kind, stage }) {
    const port = choosePort(origin, kind, stage);
    if (!port) return;
    const spec = placement({ origin, kind, release: origin.world, nodes: this.nodes, edges: this.edges, stage });
    const replaced = replacedEdges(origin, this.edges, this.nodes);
    const created = await this.#create(spec);
    if (!created) return;
    if (spec.stage_id) await this.#growStage(stage);
    const link = connectionFor(origin, created, port.name);
    const saved = await this.#save(async () => {
      const previous = this.model.edgeFrom(link.source_id, link.source_port);
      const edge = await this.model.connect({ ...link, style: previous?.style });
      for (const [id, old] of this.edges) if (old.source_id === link.source_id && old.source_port === link.source_port) this.edges.delete(id);
      this.edges.set(edge.id, edge);
    });
    if (!saved) {
      try {
        await this.model.deleteNode(created.id);
      } catch {
        /* the graph was reloaded from the server: what it still holds is what it shows */
      }
      this.nodes.delete(created.id);
      this.canvas.sync();
      return;
    }
    this.canvas.drawEdges();
    this.#renderInspector();
    if (replaced.length) this.alert.show(t("editor.connect_menu.disconnected", { names: replaced.map((r) => `'${r.name}'`).join(", ") }), { autoHide: 6000 });
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

  /** A stage the user resized: its size is saved once, when the pointer is released. */
  async #persistSize(stage) {
    stage.width = Math.round(stage.width);
    stage.height = Math.round(stage.height);
    await this.#save(() => this.model.updateNode(stage.id, { width: stage.width, height: stage.height }));
  }

  /** The name in the page header, which can be renamed in place as well. */
  /** The mark beside "All pipelines": "Draft" or "v3 published" (ADR-070). It follows every change the server accepts, so it turns to "Draft"
   * as soon as something is changed after a publication. */
  #showPublication() {
    const mark = this.root.querySelector("[data-publication]");
    if (!mark) return;
    mark.hidden = false;
    this.publication ??= new PublicationControl(mark, { kind: this.model.kind, id: this.model.id, beforeAct: () => flushDirty(), onChanged: () => this.load(), confirmFindings: (options) => this.#askFindings(options) });
    this.publication.update(this.model.graph);
    if (!this.model.onChange) {
      this.model.onChange = () => this.#refreshPublication();
      // a publication happens on the management page: coming back to this tab asks again
      window.addEventListener("focus", () => this.#refreshPublication());
    }
  }

  #refreshPublication() {
    window.clearTimeout(this.publicationTimer);
    this.publicationTimer = window.setTimeout(async () => {
      try {
        const { graph } = await loadGraph(this.model.kind, this.model.id);
        Object.assign(this.model.graph, { published_version: graph.published_version, draft_changed: graph.draft_changed });
        this.#showPublication();
        this.observe?.refresh();
      } catch {
        /* the mark keeps what it showed: it is a hint, not the editor's state */
      }
    }, 250);
  }

  #showTitle() {
    const { graph, isAction } = this.model;
    if (this.titleName) {
      this.titleName.setText(graph.name);
      return;
    }
    const title = document.querySelector(".app-header__title");
    title.textContent = graph.name;
    this.titleName = new InlineName(title, { label: isAction ? t("editor.editor.action_name") : t("editor.editor.pipeline_name"), onCommit: (name) => this.#renameGraph(name) });
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
    let updated;
    try {
      updated = await this.model.updateNode(node.id, inConfig ? { config: { [setting.key]: value } } : { [setting.key]: value });
      // a reload may have replaced the node while the text was typed: both the node of the control and the current one take it
      for (const holder of new Set([node, this.nodes.get(node.id)])) {
        if (!holder) continue;
        if (inConfig) holder.config = updated.config;
        else holder[setting.key] = updated[setting.key];
      }
    } catch (error) {
      return error.detail ?? Object.values(error.fieldErrors ?? {})[0] ?? error.message;
    }
    this.model.dropHiddenEdges(node); // connections at ports that are gone with it (e.g. no On Fail)
    this.canvas.sync();
    this.alert.hide();
    if (node.kind === "agent" && setting.key === "agent_id") await this.#loadAnswerFormats(); // the reference list follows the agent chosen
    await this.#announce(updated);
    return null;
  }

  /** What a change did beyond the node (the error output is shared by a definition and its uses): reload the graph when
   * other nodes or connections changed, then say what happened, calmly and only when something did. */
  async #announce(answer) {
    const text = noticeText(answer.notices);
    if (needsReload(answer)) await this.load();
    if (text) this.alert.show(text, { autoHide: 9000, tone: "info" });
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
      this.#showError(t("editor.editor.cannot_delete_kind", { kind: typeOf(node).label.toLowerCase() }));
      return undefined;
    }
    const inside = actionsOf(node, this.nodes).length;
    const extra = inside ? tn("editor.editor.and_its_actions", inside) : "";
    this.confirm.open({
      message: t("editor.editor.delete_kind_confirm", { kind: typeOf(node).label.toLowerCase(), name: displayName(node), extra }),
      onConfirm: async () => {
        await this.model.deleteNode(node.id);
        await this.load();
        this.select(null);
      },
      onClose: () => this.canvas.viewport.focus({ preventScroll: true }), // the node that had focus is gone
    });
    return undefined;
  }

  /** The window before a publish over findings (ADR-082): resolves true when the user publishes anyway, false when the window is closed. */
  #askFindings(options) {
    return new Promise((resolve) => {
      let confirmed = false;
      this.confirm.open({ ...options, onConfirm: async () => (confirmed = true) });
      this.confirm.modal.dialog.addEventListener("close", () => resolve(confirmed), { once: true });
    });
  }

  // ── the bar, the menu and the keys of a node ───────────────────────

  /** The nodes an action is for: the selected ones when the node is one of them, else the node alone. */
  #targets(node) {
    const chosen = [...this.canvas.multi].map((id) => this.nodes.get(id)).filter(Boolean);
    return chosen.length > 1 && this.canvas.multi.has(node.id) ? chosen : [node];
  }

  #nodeAction(action, node, button) {
    if (action === "delete") this.#deleteTargets(this.#targets(node));
    else this.#openNodeMenu(node, null, button);
  }

  /** The "+" of a stage: a small menu to add an Action, or a Guard that watches the stage (ADR-060). */
  #openStageAddMenu(stage, trigger) {
    const guard = placeholderOf("guard");
    const items = [{ label: typeOf("action").label, icon: typeOf("action").menu_icon, onSelect: () => this.#addAction(stage) }];
    if (guard && this.guards) items.push({ label: guard.label, icon: guard.icon, onSelect: () => this.guards.add("stage", stage.id, trigger) });
    this.menu.toggle(trigger, items, t("editor.node_types.add_to_stage"));
  }

  // ── guards (ADR-060) ───────────────────────────────────────────────

  /** The guards of this graph: in a pipeline shields on the pipeline, its stages and actions (counting the guards inside
   * the actions' definitions), in an action definition shields on the action as a whole and on its nodes. */
  #setUpGuards(root) {
    this.guards = new EditorGuards(root, {
      graphId: root.dataset.graphId,
      isAction: this.model.isAction,
      scopeName: (type, id) => (type === "pipeline" || type === "definition" ? (this.model.graph?.name ?? "") : displayName(this.nodes.get(id) ?? { name: "" })),
      guardable: (node) => Boolean(typeOf(node).guardable),
      definitionOf: (nodeId) => this.nodes.get(nodeId)?.definition_id ?? null,
      actionsPath: this.paths.action,
      pipelineSlug: () => (this.model.isAction ? "" : (this.model.graph?.slug ?? "")),
      confirm: (message, action, options = {}) => this.confirm.open({ message, onConfirm: action, ...options }),
      showError: (message) => this.alert.show(message, { autoHide: 6000 }),
      redraw: () => this.canvas.sync(),
      bar: this.bar,
    });
  }

  /** The status bar in the corner of the canvas (components/status-bar.js): the eye of the observe mode (a pipeline only), the shield of the guards and the "+" menu,
   * in this order and only while active; the "+" is always the last. */
  #setUpBar(root) {
    this.bar = new StatusBar(root.querySelector(".ge-add__row"));
    this.bar.add({ key: "guard", order: 20, element: root.querySelector("[data-pipeline-shield]"), visible: false });
    this.bar.add({ key: "add", order: LAST, element: root.querySelector("[data-add-menu]"), visible: true });
    if (this.model.isAction) return;
    this.observe = new ObserveStore(this.model.id);
    this.observeBar = new ObserveBar({
      bar: this.bar,
      popup: new StatusPopup(),
      store: this.observe,
      openSettings: () => this.#openObserveSettings(),
      draftChanged: () => this.#refreshPublication(),
    });
  }

  /** The Trigger window at its Dry run tab, where the observe mode is set. */
  #openObserveSettings() {
    const trigger = [...this.nodes.values()].find((node) => node.kind === "trigger");
    if (!trigger) return;
    this.dryRunTab = "dry-run";
    this.nodeTab = "settings";
    this.#openSettings(trigger);
  }

  /** The menu of a node: opened by a right click (at the pointer) or by the "..." of its bar (under it). */
  #openNodeMenu(node, point, trigger = null) {
    if (!this.canvas.multi.has(node.id)) this.select({ type: "node", id: node.id });
    const targets = this.#targets(node);
    const several = targets.length > 1;
    const fixed = targets.some((n) => typeOf(n).fixed);
    const copyable = targets.some((n) => !typeOf(n).fixed);
    const reasonFixed = t("editor.editor.trigger_output_end_part_graph");
    const renameReason = several ? t("editor.editor.select_one_node_rename") : typeOf(node).renamable(node) ? undefined : t("editor.editor.node_named_by_what_links");
    const items = [
      { label: t("common.edit"), icon: "pencil", shortcut: "Enter", disabledReason: several ? t("editor.editor.select_one_node_edit") : undefined, onSelect: () => this.#openNode(node) },
      ...(typeOf(node).links_to
        ? [{ label: t("common.settings"), icon: "settings", disabledReason: several ? t("editor.editor.select_one_node_edit") : undefined, onSelect: () => this.#openSettings(node) }]
        : []),
      { label: t("graph_list.rename"), icon: "tag", shortcut: "F2", disabledReason: renameReason, onSelect: () => this.#askRename(node) },
      { label: t("credentials.copy"), icon: "copy", shortcut: "Ctrl+C", disabledReason: copyable ? undefined : reasonFixed, onSelect: () => this.#copy(targets) },
      { label: t("editor.editor.cut"), icon: "copy", shortcut: "Ctrl+X", disabledReason: copyable && !fixed ? undefined : reasonFixed, onSelect: () => this.#cut(targets) },
      { label: t("editor.editor.duplicate"), icon: "layers", shortcut: "Ctrl+D", disabledReason: copyable ? undefined : reasonFixed, onSelect: () => this.#duplicate(targets) },
      { label: t("common.delete"), icon: "trash", shortcut: "Del", danger: true, disabledReason: fixed ? reasonFixed : undefined, onSelect: () => this.#deleteTargets(targets) },
    ];
    const guard = placeholderOf("guard");
    const watches = this.guards?.scopeTypeOf(node);
    if (guard && this.guards && !several && (watches === "action" || watches === "node")) {
      // a guard that watches this action (in a pipeline) or this node (in an action), before Delete
      const anchor = trigger ?? this.canvas.elements.get(node.id);
      items.splice(items.length - 1, 0, { label: guard.label, icon: guard.icon, onSelect: () => this.guards.add(watches, node.id, anchor.isConnected ? anchor : this.canvas.elements.get(node.id)) });
    }
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
      this.#askRename(chosen[0]);
    }
  }

  /** Rename a node in a small dialog of its own (the settings are Edit, not Rename). */
  #askRename(node) {
    this.nameDialog.open({
      title: `Rename ${typeOf(node).label.toLowerCase()}`,
      values: { name: node.name },
      submitLabel: t("graph_list.rename"),
      onSubmit: ({ name }) => this.#rename(node, name),
    });
  }

  #deleteTargets(targets) {
    const deletable = targets.filter((n) => !typeOf(n).fixed);
    if (deletable.length > 1) return this.#deleteMany(deletable.map((n) => n.id));
    if (deletable.length === 1) return this.requestDelete({ type: "node", id: deletable[0].id });
    this.#showError(t("editor.editor.trigger_output_end_cannot_be"));
    return undefined;
  }

  #deleteMany(ids) {
    const nodes = ids.map((id) => this.nodes.get(id)).filter(Boolean);
    this.confirm.open({
      message: t("editor.editor.delete_length_nodes_their_connections", { length: nodes.length }),
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
      this.#showError(t("editor.editor.trigger_output_end_cannot_be_2"));
      return false;
    }
    writeJson(KEYS.nodeClipboard, copy);
    this.pastes = 0;
    this.alert.show(tn("editor.editor.copied", copy.nodes.length), { autoHide: 2500 });
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
      this.#showError(t("editor.editor.nothing_copied_yet_select_node"));
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
    const plan = pastePlan(copy, {
      offset: 40 * times,
      names: new Set([...this.nodes.values()].map((n) => n.name)),
      stageFor: (old) => (this.nodes.has(old) ? old : selected?.kind === "stage" ? selected.id : selected?.stage_id ?? null),
      allowed: new Set([...addableIn(this.model.kind, this.model.graph?.purpose ?? null).map((t) => t.kind), ...(this.model.kind === "pipeline" ? ["action"] : [])]), // an action is made inside its stage, not by the menu
    });
    if (plan.error) return this.#showError(plan.error);
    if (!plan.items.length) return this.#showError(t("editor.editor.cannot_add_here", { kinds: plan.skipped.map((k) => typeOf(k)?.label ?? k).join(", ") }));
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
      // the copy reads its own copy of a node it refers to, not the original (ADR-082): ids in the settings follow the new nodes
      for (const item of plan.items) {
        const changed = remappedConfig(item.config, made);
        if (changed) Object.assign(this.nodes.get(made.get(item.key)), await this.model.updateNode(made.get(item.key), { config: changed }));
      }
      for (const link of plan.edges) {
        const edge = await this.model.connect({ source_id: made.get(link.source), source_port: link.source_port, source_slot: link.source_slot, target_id: made.get(link.target), target_port: link.target_port, target_slot: link.target_slot, style: link.style });
        this.edges.set(edge.id, edge);
      }
      // a tool pasted without its agent hangs on the agent it was copied from, if that agent is in this graph
      for (const item of plan.items.filter((i) => typeOf(i.kind)?.tool)) {
        const agent = copy.attached?.[item.key];
        if (agent && this.nodes.has(agent)) {
          const edge = await this.model.connect(attachmentLink(made.get(item.key), agent));
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
    if (plan.skipped.length) this.#showError(t("editor.editor.cannot_add_left_out", { kinds: plan.skipped.map((k) => typeOf(k)?.label ?? k).join(", ") }));
    return undefined;
  }

  // ── what the inspector may do ──────────────────────────────────────

  #blockActions() {
    return {
      saveSetting: (node, setting, value) => this.#saveSetting(node, setting, value),
      suggestions: (node) => ({ nodes: () => [...this.nodes.values()], exceptId: node.id, contracts: (n) => this.#contractOf(n), answers: (n) => this.#answersOf(n), node, inputsOf: (n) => this.contracts?.get(n.definition_id)?.inputs ?? [] }),
      link: (node, targetId) => this.#link(node, targetId),
      askNew: (node) => this.#askNew(node),
      linkUrl: (node) => this.#linkUrl(node, node.definition_slug),
      remove: (node) => this.requestDelete({ type: "node", id: node.id }),
      confirm: (options) => this.confirm.open(options),
      addAction: (stage) => this.#addAction(stage),
      listTargets: (kind) => this.#listTargets(kind),
      showError: (message) => this.#showError(message),
      refresh: () => this.#renderInspector(),
      renameNode: (node, name) => this.#rename(node, name),
      saveMock: (node, mock) => this.#saveMock(node, mock),
      lastResult: (node) => lastResult(this.model.kind, this.model.id, node.id),
      saveCases: (node, cases) => this.#saveCases(node, cases),
      nodeTab: () => this.nodeTab,
      setNodeTab: (name) => {
        this.nodeTab = name;
      },
      dryRunPanel: (node) => this.#dryRunPanel(node),
      dryRunTab: () => this.dryRunTab,
      setDryRunTab: (name) => {
        this.dryRunTab = name;
      },
    };
  }

  /** Store (or with `null` remove) the mock of a node in the draft (ADR-087); resolves to null, or to why the server refused it. */
  async #saveMock(node, mock) {
    try {
      const updated = await this.model.updateNode(node.id, { mock });
      for (const holder of new Set([node, this.nodes.get(node.id)])) if (holder) holder.mock = updated.mock;
    } catch (error) {
      return error.detail ?? Object.values(error.fieldErrors ?? {})[0] ?? error.message;
    }
    this.canvas.sync(); // the pin on the card follows the switch
    this.alert.hide();
    return null;
  }

  /** Store the test cases of a Trigger in the draft (ADR-087); resolves to null, or to why the server refused them. */
  async #saveCases(node, cases) {
    try {
      const updated = await this.model.updateNode(node.id, { cases });
      for (const holder of new Set([node, this.nodes.get(node.id)])) if (holder) holder.cases = updated.cases;
    } catch (error) {
      return error.detail ?? Object.values(error.fieldErrors ?? {})[0] ?? error.message;
    }
    return null;
  }

  /** The pin on the card of a node whose mock is switched on: the dry run uses a stored result there. */
  #drawMockPin(node, el) {
    drawPin(el, mockable(typeOf(node), node) && mockActive(node), () => this.#openMockOf(node));
  }

  /** The pin on a card opens the window of the node at its Mock tab. */
  #openMockOf(node) {
    this.nodeTab = "mock";
    this.#openSettings(node);
  }

  /** The panel of the Dry run tab of the Trigger window (ADR-086), one for the page; none for a graph for guards (they run on their own, not on a card). */
  #dryRunPanel(node) {
    if (this.model.graph?.purpose === "guard") return null;
    this.dryRun ??= new DryRunPanel({
      kind: this.model.kind,
      id: this.model.id,
      contract: async () => (await loadContract(this.model.kind, this.model.id)).inputs ?? [],
      observe: this.observe ?? null,
      draftChanged: () => this.#refreshPublication(),
    });
    return this.dryRun.show(node.config?.inputs ?? [], { list: () => this.nodes.get(node.id)?.cases ?? [], save: (cases) => this.#saveCases(node, cases) });
  }

  /** The things a node may link to, fetched once until something new is created. */
  #listTargets(kind) {
    // a stage takes the actions for pipelines, never an action that is for guards (ADR-067)
    this.targets[kind] ??= listGraphs(kind, kind === "action" ? "pipeline" : null).catch((error) => {
      delete this.targets[kind];
      throw error;
    });
    return this.targets[kind];
  }

  /** A double click on a node opens it: an action or pipeline node opens what it links to, any other node its settings. */
  #openSettingsAt(event) {
    // the canvas captures the pointer while a gesture runs, which makes the viewport the target of the click: look under the pointer
    const under = document.elementFromPoint(event.clientX, event.clientY);
    const el = under?.closest(".ge-node");
    if (!el || under.closest("button, input, select, a, .ge-port, .ge-resize")) return;
    const node = this.nodes.get(el.dataset.nodeId);
    if (node) this.#openNode(node);
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
      this.#lastLinkAnswer = updated;
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
    await this.#announce(this.#lastLinkAnswer ?? {});
  }

  /** Ask for the name of something new to link to (like creating an artifact on the board). */
  #askNew(node) {
    const what = typeOf(node).links_to === "action" ? "action" : "pipeline";
    this.nameDialog.open({ title: t("editor.editor.new_what", { what }), onSubmit: ({ name }) => this.#createAndOpen(node, name) });
  }

  /** Create what the node links to under the entered name, link the node to it and go and edit it. */
  async #createAndOpen(node, name) {
    const created = await createGraph(typeOf(node).links_to, name);
    this.targets = {};
    await this.model.updateNode(node.id, { definition_id: created.id });
    window.location.assign(this.#linkUrl(node, created.slug));
  }
}
