/* The flow page of one execution: loads it, keeps it current while it runs and ties the parts
 * together (header, breadcrumb, canvas, panel). The place shown is one visit; it is kept in the URL
 * (?visit=N) so a reload, a shared link and the browser's Back button all restore it. Nothing here
 * changes anything on the server. */
import { AlertBar } from "../components/alert-bar.js";
import { loadNodeTypes } from "../editor/node-types.js";
import { connectEvents } from "../tasks/events.js";
import { executionSeconds, formatDuration, formatTime, originLabel, setChip } from "../tasks/history-format.js";
import { Breadcrumb } from "./breadcrumb.js";
import { loadFlow, loadStep, loadTask } from "./flow-client.js";
import { FlowPanel } from "./flow-panel.js";
import { FlowView } from "./flow-view.js";
import { FlowModel } from "./visit-model.js";

const REFETCH_MS = 300;
const root = document.querySelector("[data-flow]");

class FlowPage {
  constructor() {
    this.ref = root.dataset.taskRef;
    this.executionId = root.dataset.executionId;
    this.model = null;
    this.task = null;
    this.visit = null; // the visit shown
    this.selected = null; // node id
    this.timer = null;
    this.gone = false;

    this.alert = new AlertBar(root.querySelector("[data-alert]"));
    this.alert.onRetry(() => this.load());
    this.live = root.querySelector("[data-live]");
    this.up = root.querySelector("[data-up]");
    this.zoomLabel = root.querySelector("[data-zoom-label]");
    this.crumbs = new Breadcrumb(root.querySelector("[data-crumbs]"), (visit) => this.go(visit));
    this.view = new FlowView({
      viewport: root.querySelector("[data-viewport]"),
      onActivate: (node) => this.activate(node.id),
      onClear: () => this.select(null),
      onZoom: (zoom) => (this.zoomLabel.textContent = `${Math.round(zoom * 100)}%`),
    });
    this.panel = new FlowPanel({
      root: root.querySelector("[data-panel]"),
      stepTemplate: document.getElementById("history-step-template"),
      loadStep: (step) => loadStep(this.ref, this.executionId, step.id),
      onSelect: (nodeId) => this.select(nodeId),
      onOpen: (visit) => this.go(visit),
      onPass: (visit) => this.go(visit, { keepSelection: true }),
    });

    this.up.addEventListener("click", () => this.goUp());
    root.querySelector("[data-zoom-in]").addEventListener("click", () => this.view.zoomBy(1.2));
    root.querySelector("[data-zoom-out]").addEventListener("click", () => this.view.zoomBy(1 / 1.2));
    root.querySelector("[data-zoom-fit]").addEventListener("click", () => this.view.fit());
    window.addEventListener("popstate", () => this.#show(this.#visitFromUrl(), { fit: true }));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !event.defaultPrevented && !event.target.closest?.("input, select, textarea") && this.visit?.parent != null) {
        event.preventDefault();
        this.goUp();
      }
    });
  }

  // ── loading ─────────────────────────────────────────────────────────

  async load() {
    try {
      const [flow, task] = await Promise.all([loadFlow(this.ref, this.executionId), this.task ? this.task : loadTask(this.ref).catch(() => null)]);
      this.task = task;
      this.alert.hide();
      const first = this.model === null;
      this.model = new FlowModel(flow);
      root.querySelector("[data-body]").hidden = false;
      this.#renderHead();
      this.#show(first ? this.#visitFromUrl() : this.visit && this.model.visit(this.visit.index), { fit: first });
    } catch (error) {
      if (error.status === 404) this.#vanished(this.model ? "This execution was deleted." : "This execution does not exist. It was deleted, or the link is not right.");
      else this.alert.show(error.message || "The flow could not be loaded.", { retry: true });
    }
  }

  /** The execution is gone: say so, with the way back. */
  #vanished(text) {
    this.gone = true;
    window.clearTimeout(this.timer);
    root.querySelector("[data-body]").hidden = true;
    root.querySelector("[data-head]").hidden = true;
    root.querySelector("[data-gone]").hidden = false;
    root.querySelector("[data-gone-text]").textContent = text;
    this.alert.hide();
    this.#announce(text);
    root.querySelector("[data-gone-title]").focus();
  }

  /** The live updates of the page's event stream (connectEvents, as the board uses it). */
  handleEvent(type, data) {
    if (!this.model || this.gone) return;
    const taskId = this.model.execution.task_id;
    if (type === "execution.deleted") {
      if (data.task_id === taskId && data.id === this.executionId) this.#vanished("This execution was deleted.");
    } else if (type === "execution.updated") {
      if (data.task_id === taskId && data.execution.id === this.model.execution.id) this.#refetch();
    } else if (type === "run.updated") {
      if (data.task_id === taskId && this.model.execution.status === "running") this.#refetch();
    }
  }

  #refetch() {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => this.load(), REFETCH_MS);
  }

  // ── where we are ────────────────────────────────────────────────────

  #visitFromUrl() {
    const index = Number(new URLSearchParams(window.location.search).get("visit"));
    return (Number.isInteger(index) && this.model.visit(index)) || this.model.root;
  }

  #url(visit) {
    return visit.parent === null ? window.location.pathname : `${window.location.pathname}?visit=${visit.index}`;
  }

  /** Go to a visit (a step down, another pass, a breadcrumb item); the browser's Back returns. */
  go(visit, { keepSelection = false, select = null } = {}) {
    if (!visit || visit === this.visit) return;
    window.history.pushState(null, "", this.#url(visit));
    this.selected = keepSelection ? this.selected : select;
    this.#show(visit, { fit: true, announce: true, focus: true });
  }

  goUp() {
    const from = this.visit;
    if (!from || from.parent === null) return;
    this.go(this.model.visit(from.parent), { select: from.entered_via?.node_id ?? null });
    if (this.selected) this.panel.focusNode(this.selected);
  }

  /** A node was clicked (or Enter on it): select it and, if something was entered from it, go there. */
  activate(nodeId) {
    this.select(nodeId);
    const child = this.model.childrenVia(this.visit, nodeId)[0];
    if (child) this.go(child);
  }

  select(nodeId) {
    this.selected = nodeId;
    this.view.select(nodeId);
    this.#renderPanel();
  }

  #show(visit, { fit = false, announce = false, focus = false } = {}) {
    if (!visit) visit = this.model.root;
    if (!visit) return;
    const changed = visit.index !== this.visit?.index;
    this.visit = visit;
    if (changed && !this.model.graph(visit).nodes.some((n) => n.id === this.selected)) this.selected = null;
    this.walk = this.model.describe(visit);
    this.view.show(this.model.graph(visit), this.walk, { fit: fit || changed });
    this.view.select(this.selected);
    this.#renderPanel();
    this.#renderBar();
    this.up.hidden = visit.parent === null;
    if (announce) this.#announce(this.#where(visit));
    if (focus) this.panel.focusTitle();
  }

  #renderPanel() {
    this.panel.render({ model: this.model, visit: this.visit, walk: this.walk, selected: this.selected });
  }

  #renderBar() {
    const chain = this.model.chain(this.visit);
    this.crumbs.render(
      chain.map((visit) => {
        const title = this.model.titleOf(visit);
        const all = this.model.passes(visit);
        return { visit, href: this.#url(visit), name: title.name, stage: title.stage, pass: all.length > 1 ? `pass ${all.indexOf(visit) + 1} of ${all.length}` : null };
      }),
    );
  }

  #where(visit) {
    const title = this.model.titleOf(visit);
    const all = this.model.passes(visit);
    const parts = [`${title.graph.kind === "action" ? "Action" : "Pipeline"} ${title.name}`, `level ${visit.level + 1}`, all.length > 1 ? `pass ${all.indexOf(visit) + 1} of ${all.length}` : null];
    return `Showing ${parts.filter(Boolean).join(", ")}`;
  }

  #announce(message) {
    this.live.textContent = "";
    window.requestAnimationFrame(() => (this.live.textContent = message));
  }

  // ── the header ──────────────────────────────────────────────────────

  #renderHead() {
    const { execution } = this.model;
    const artifact = this.task ? `#${this.task.number} ${this.task.title}` : null;
    root.querySelector("[data-head-title]").textContent = `Execution #${execution.number}${artifact ? ` of ${artifact}` : ""}`;
    document.title = `Execution #${execution.number}${artifact ? ` · ${artifact}` : ""} · OpenArtifact`;
    const chip = root.querySelector("[data-head-chip]");
    chip.hidden = false;
    setChip(chip, execution.status);
    const startedAt = [execution.started_stage_name, execution.started_action_name].filter(Boolean).join(" › ");
    const rows = [
      ["Pipeline", execution.pipeline_name],
      ["Started", formatTime(execution.started_at)],
      ["Duration", formatDuration(executionSeconds(execution))],
      ["Started by", originLabel(execution.started_by)],
      ["Started at", startedAt],
    ].filter(([, value]) => value);
    root.querySelector("[data-head-facts]").replaceChildren(
      ...rows.map(([term, value]) => {
        const fact = document.createElement("div");
        fact.className = "ef-fact";
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.textContent = value;
        fact.append(dt, dd);
        return fact;
      }),
    );
  }
}

const page = new FlowPage();
loadNodeTypes()
  .then(() => page.load())
  .then(() => {
    let connected = false;
    return connectEvents({
      onEvent: (type, data) => page.handleEvent(type, data),
      onOpen: () => {
        if ((connected || page.model?.execution.status === "running") && page.model) page.load(); // a reconnect (or a run that went on meanwhile): what was missed is not replayed
        connected = true;
      },
      onClosed: () => page.alert.show("Live updates stopped. Reload the page or sign in again."),
    });
  })
  .catch(() => page.alert.show("The page could not be loaded.", { retry: true }));
