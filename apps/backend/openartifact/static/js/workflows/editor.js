/* The workflow editor: owns the graph, talks to the API and connects canvas, toolbar and
 * inspector. Changes are saved at once; if the server refuses one, the graph is reloaded. */
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { addNode, connect, createWorkflow, listWorkflows, deleteNode, disconnect, loadWorkflow, renameWorkflow, restyleEdge, updateNode } from "./api.js";
import { Canvas } from "./canvas.js";
import { ACTION_GAP, EDGE_STYLES, INPUTS, displayName, OUTPUTS, PAD, PORT_LABELS, SIZE, TOP_LEVEL_GAP, canConnect, fitStage } from "./graph.js";

const LAST_STAGE = "oa-last-stage"; // read by main.js
const KIND_LABELS = { trigger: "Trigger", stage: "Stage", action: "Action", complete: "Complete", output: "Output" };

export class WorkflowEditor {
  /** @param {HTMLElement} root the element carrying data-workflow-id */
  constructor(root) {
    this.id = root.dataset.workflowId;
    this.root = root;
    this.isAction = root.dataset.kind === "action"; // an action definition: trigger and output are fixed
    this.workflow = null;
    this.nodes = new Map();
    this.edges = new Map();
    this.selection = null;

    this.alert = root.querySelector("[data-editor-error]");
    this.inspector = root.querySelector("[data-inspector]");
    this.zoomLabel = root.querySelector("[data-zoom-label]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
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
      const toggle = event.target.closest("[data-toggle-fail]");
      if (toggle) {
        const output = this.nodes.get(toggle.closest(".wf-node").dataset.nodeId);
        this.#setFail(output, !output.fail_enabled);
      }
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
      const graph = await loadWorkflow(this.id);
      this.workflow = graph.workflow;
      this.nodes.clear();
      this.edges.clear();
      for (const node of graph.nodes) this.nodes.set(node.id, node);
      for (const edge of graph.edges) this.edges.set(edge.id, edge);
      this.alert.hidden = true;
      document.querySelector(".app-header__title").textContent = this.workflow.name;
      document.title = `${this.workflow.name} · OpenArtifact`;
      this.canvas.sync();
      if (fit) this.canvas.fit();
      this.#renderInspector();
      if (!this.opened) this.#onFirstLoad();
      this.opened = true;
    } catch (error) {
      if (error.status === 404 && !this.isAction) localStorage.removeItem(LAST_STAGE);
      this.#showError(error.status === 404 ? "This workflow does not exist." : "The workflow could not be loaded.", true);
    }
  }

  /** Coming back from an action definition: offer the way back, or select the action that was being defined. */
  async #onFirstLoad() {
    const params = new URLSearchParams(window.location.search);
    if (this.isAction) return this.#setupBack(params.get("from"), params.get("node"));
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
    link.href = `/stages/${encodeURIComponent(slug)}${nodeId ? `?select=${encodeURIComponent(nodeId)}` : ""}`;
    try {
      const stage = (await listWorkflows("workflow")).find((w) => w.slug === slug);
      link.textContent = stage ? `Back to ${stage.name}` : "Back to stage";
    } catch {
      link.textContent = "Back to stage";
    }
    link.hidden = false;
  }

  /** The navigation reopens the last stage with its action selected (see main.js). */
  #remember(nodeId) {
    if (this.isAction || !this.workflow) return;
    try {
      localStorage.setItem(LAST_STAGE, JSON.stringify({ slug: this.workflow.slug, node: nodeId }));
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

  /** The "+" menu on the canvas; trigger and complete are always there, so it only offers stages. */
  #bindAddMenu() {
    const toggle = this.root.querySelector("[data-add-menu]");
    if (!toggle) return;
    const list = this.root.querySelector("[data-add-list]");
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
      this.#addStage();
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

  /** A new stage goes right of the last stage (or of the trigger); complete moves on if it is in the way. */
  async #addStage() {
    const nodes = [...this.nodes.values()];
    const before = nodes.filter((n) => n.kind === "stage" || n.kind === "trigger");
    const right = Math.max(...before.map((n) => n.x + (n.kind === "stage" ? n.width : SIZE.trigger.width)), 60);
    const created = await this.#create({ kind: "stage", x: Math.round(right + TOP_LEVEL_GAP), y: 40 });
    if (!created) return;
    const complete = nodes.find((n) => n.kind === "complete");
    const free = created.x + created.width + TOP_LEVEL_GAP;
    if (complete && complete.x < free) {
      complete.x = free;
      this.canvas.sync();
      await this.#save(() => updateNode(this.id, complete.id, { x: free }));
    }
    this.canvas.reveal(created);
  }

  async #addAction(stage) {
    const actions = [...this.nodes.values()].filter((n) => n.stage_id === stage.id);
    // flows run left to right: a new action goes to the right of the last one
    const x = actions.length ? Math.max(...actions.map((a) => a.x + SIZE.action.width)) + ACTION_GAP : PAD;
    const created = await this.#create({ kind: "action", stage_id: stage.id, x, y: PAD * 2 });
    if (created) await this.#growStage(stage);
  }

  async #create(fields) {
    let node = null;
    const saved = await this.#save(async () => {
      node = await addNode(this.id, fields);
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
    await this.#save(() => updateNode(this.id, stage.id, size));
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
      await updateNode(this.id, node.id, fields);
      if (stage) await updateNode(this.id, stage.id, { width: stage.width, height: stage.height });
    });
  }

  async #rename(node, name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === node.name) return this.#renderInspector();
    node.name = trimmed;
    this.canvas.sync();
    await this.#save(() => updateNode(this.id, node.id, { name: trimmed }));
    this.#renderInspector();
  }

  async #setFail(node, enabled) {
    node.fail_enabled = enabled;
    this.canvas.sync();
    this.#renderInspector();
    await this.#save(() => updateNode(this.id, node.id, { fail_enabled: enabled }));
  }

  async #renameWorkflow(name) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === this.workflow.name) return this.#renderInspector();
    this.workflow.name = trimmed;
    document.querySelector(".app-header__title").textContent = trimmed;
    const saved = await this.#save(async () => {
      this.workflow = await renameWorkflow(this.id, trimmed);
    });
    if (saved) {
      window.history.replaceState(null, "", `${window.location.pathname.replace(/[^/]+$/, "")}${encodeURIComponent(this.workflow.slug)}`);
      this.#remember(this.selection?.type === "node" && this.nodes.get(this.selection.id)?.kind === "action" ? this.selection.id : null);
    }
  }

  async #connect(source, sourcePort, target, targetPort, slots = {}) {
    await this.#save(async () => {
      const previous = [...this.edges.values()].find((e) => e.source_id === source.id && e.source_port === sourcePort);
      const edge = await connect(this.id, { source_id: source.id, source_port: sourcePort, target_id: target.id, target_port: targetPort, style: previous?.style, ...slots });
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
    await this.#save(() => disconnect(this.id, id));
  }

  async #restyle(edge, style) {
    edge.style = style;
    this.canvas.drawEdges();
    this.#renderInspector();
    await this.#save(() => restyleEdge(this.id, edge.id, style));
  }

  /** Trigger, complete and output come with the workflow; the last one of each stays. */
  #isFixed(node) {
    if (!["trigger", "complete", "output"].includes(node.kind)) return false;
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
      message: `Delete ${KIND_LABELS[node.kind].toLowerCase()} "${node.name}"${extra}? Its connections are removed too.`,
      onConfirm: async () => {
        await deleteNode(this.id, node.id);
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
    return this.#workflowInspector();
  }

  #heading(text, caption) {
    const wrap = document.createElement("div");
    wrap.className = "wf-inspector__heading";
    const title = document.createElement("h2");
    title.textContent = text;
    const small = document.createElement("p");
    small.textContent = caption;
    wrap.append(title, small);
    return wrap;
  }

  #field(label, control) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const text = document.createElement("label");
    text.className = "field__label";
    text.textContent = label;
    control.id = control.id || `wf-field-${Math.random().toString(36).slice(2, 8)}`;
    text.htmlFor = control.id;
    wrap.append(text, control);
    return wrap;
  }

  #nameInput(value, onCommit) {
    const input = document.createElement("input");
    input.className = "field__control";
    input.type = "text";
    input.maxLength = 255;
    input.value = value;
    input.autocomplete = "off";
    input.addEventListener("change", () => onCommit(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") input.blur();
    });
    return input;
  }

  #workflowInspector() {
    const count = (kind) => [...this.nodes.values()].filter((n) => n.kind === kind).length;
    this.inspector.append(
      this.#heading(this.workflow?.name ?? "Workflow", "Draft"),
      this.#field("Name", this.#nameInput(this.workflow?.name ?? "", (name) => this.#renameWorkflow(name))),
      this.#note(
        this.isAction
          ? "The trigger starts this action automatically; the output always offers On Pass and optionally On Fail."
          : `${count("stage")} stages, ${count("action")} actions. Select a node to edit it, drag from a port to connect.`,
      ),
    );
  }

  #note(text) {
    const p = document.createElement("p");
    p.className = "wf-inspector__note";
    p.textContent = text;
    return p;
  }

  #nodeInspector(node) {
    const el = this.inspector;
    const shell = node.kind === "action" && !this.isAction;
    el.append(this.#heading(displayName(node), shell && !node.definition_id ? "Empty action" : KIND_LABELS[node.kind]));
    if (!shell) el.append(this.#field("Name", this.#nameInput(node.name, (name) => this.#rename(node, name))));
    if (shell) el.append(this.#definitionSection(node));

    const outputs = shell ? [] : OUTPUTS[node.kind];
    if (outputs.length) {
      const routing = document.createElement("div");
      routing.className = "wf-inspector__section";
      const title = document.createElement("h3");
      title.textContent = "Routing";
      routing.append(title);
      for (const port of outputs) routing.append(this.#field(PORT_LABELS[port], this.#routeSelect(node, port)));
      el.append(routing);
    }
    if (node.kind === "stage") {
      const add = document.createElement("button");
      add.type = "button";
      add.className = "button button--ghost";
      add.textContent = "Add action";
      add.addEventListener("click", () => this.#addAction(node));
      el.append(add);
    }
    if (node.kind === "output") el.append(this.#failToggle(node));
    if (shell || this.#isFixed(node)) return;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button--ghost wf-delete";
    remove.textContent = `Delete ${KIND_LABELS[node.kind].toLowerCase()}`;
    remove.addEventListener("click", () => this.requestDelete({ type: "node", id: node.id }));
    el.append(remove);
  }

  /** An action in a stage is an empty shell until it is linked to an action definition. */
  #definitionSection(node) {
    const section = document.createElement("div");
    section.className = "wf-inspector__section";
    const title = document.createElement("h3");
    title.textContent = "Definition";
    const select = document.createElement("select");
    select.className = "field__control";
    select.append(new Option("Not defined", ""));
    select.addEventListener("change", () => this.#link(node, select.value || null));
    section.append(title, this.#field("Action", select));
    listWorkflows("action").then((definitions) => {
      for (const definition of definitions) {
        const option = new Option(definition.name, definition.id);
        option.selected = definition.id === node.definition_id;
        select.append(option);
      }
    }).catch(() => this.#showError("The actions could not be loaded."));

    section.append(this.#actionBar(node));
    return section;
  }

  /** New, Edit and Delete in one compact row: icon and a short text each. */
  #actionBar(node) {
    const bar = document.createElement("div");
    bar.className = "wf-actionbar";
    const make = (tag, icon, text, className = "") => {
      const el = document.createElement(tag);
      el.className = `button button--ghost button--sm ${className}`.trim();
      if (tag === "button") el.type = "button";
      const glyph = document.getElementById("wf-icons").content.querySelector(`[data-icon=${icon}]`).cloneNode(true);
      el.append(glyph, document.createTextNode(text));
      return el;
    };
    const create = make("button", "plus", "New");
    create.addEventListener("click", () => this.#askNewAction(node));
    const edit = make("a", "pencil", "Edit");
    if (node.definition_id) edit.href = this.#definitionUrl(node, node.definition_slug);
    else edit.setAttribute("aria-disabled", "true");
    const remove = make("button", "trash", "Delete", "wf-delete");
    remove.addEventListener("click", () => this.requestDelete({ type: "node", id: node.id }));
    bar.append(create, edit, remove);
    return bar;
  }

  /** The small window for the title of a new action (like creating an artifact on the board). */
  #askNewAction(node) {
    this.newAction ??= this.#bindNewActionDialog();
    this.newAction.node = node;
    this.newAction.input.value = "";
    this.newAction.error.hidden = true;
    this.newAction.modal.open();
  }

  #bindNewActionDialog() {
    const modal = new Modal(document.getElementById("action-modal"));
    const input = document.getElementById("action-name");
    const error = document.getElementById("action-name-error");
    const dialog = { modal, input, error, node: null };
    input.addEventListener("input", () => (error.hidden = true));
    document.getElementById("action-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!input.value.trim()) {
        error.textContent = "Please enter a title.";
        error.hidden = false;
        input.focus();
        return;
      }
      modal.close();
      await this.#createDefinition(dialog.node, input.value);
    });
    return dialog;
  }

  #definitionUrl(node, definitionSlug) {
    return `/actions/${encodeURIComponent(definitionSlug)}?from=${encodeURIComponent(this.workflow.slug)}&node=${encodeURIComponent(node.id)}`;
  }

  async #link(node, definitionId) {
    await this.#save(async () => {
      const updated = await updateNode(this.id, node.id, { definition_id: definitionId });
      Object.assign(node, { definition_id: updated.definition_id, definition_name: updated.definition_name, definition_slug: updated.definition_slug, definition_fail_enabled: updated.definition_fail_enabled });
    });
    if (node.definition_fail_enabled === false) {
      for (const [id, edge] of this.edges) if (edge.source_id === node.id && edge.source_port === "error") this.edges.delete(id);
    }
    this.canvas.sync();
    this.#renderInspector();
  }

  /** Create an action definition under the entered name, link the shell to it and go and define it. */
  async #createDefinition(node, name) {
    const trimmed = name.trim();
    if (!trimmed) return;
    let created = null;
    const saved = await this.#save(async () => {
      created = await createWorkflow(trimmed, "action");
      await updateNode(this.id, node.id, { definition_id: created.id });
    });
    if (saved && created) window.location.assign(this.#definitionUrl(node, created.slug));
  }

  /** The keyboard way to switch On Fail on or off; On Pass is always there. */
  #failToggle(node) {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = node.fail_enabled;
    input.addEventListener("change", () => this.#setFail(node, input.checked));
    const field = this.#field("Provide On Fail", input);
    field.classList.add("field--inline");
    return field;
  }

  /** A select with every valid target of an output port: the keyboard way to connect. */
  #routeSelect(node, port) {
    const select = document.createElement("select");
    select.className = "field__control";
    const none = new Option("Not connected", "");
    select.append(none);
    const current = [...this.edges.values()].find((e) => e.source_id === node.id && e.source_port === port);
    for (const target of this.nodes.values()) {
      for (const targetPort of INPUTS[target.kind]) {
        if (!canConnect(node, port, target, targetPort)) continue;
        const label = targetPort === "end" ? `${target.name} · end of stage` : target.name;
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
      this.#heading("Connection", `${source?.name ?? "?"} (${PORT_LABELS[edge.source_port]}) → ${target?.name ?? "?"}`),
      this.#field("Line", styles),
      remove,
    );
  }
}
