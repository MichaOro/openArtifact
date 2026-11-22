/* The side panel of the flow page: what the shown visit is, the nodes it walked in order (the
 * primary alternative to the canvas: focusable, readable by a screen reader) and the details of the
 * selected one. Everything shown is text (textContent): names, outputs and reasons come from what ran. */
import { icon } from "../components/icons.js";
import { typeOf } from "../editor/node-types.js";
import { formatDuration, formatTime, secondsBetween, setChip } from "../tasks/history-format.js";
import { fillStep, stepDuration } from "../tasks/history-step.js";
import { STATES } from "./flow-view.js";
import { nameOf } from "./visit-model.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const WORKS = ["code", "http", "timer"]; // a trigger or an output takes no time worth showing
const visitSeconds = (visit) => (visit.started_at ? secondsBetween(visit.started_at, visit.finished_at) : null);

export class FlowPanel {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the <aside>
   * @param {HTMLTemplateElement} options.stepTemplate
   * @param {(step: object) => Promise<object>} options.loadStep the step with its whole output (only when it is opened)
   * @param {(nodeId: string) => void} options.onSelect
   * @param {(visit: object) => void} options.onOpen go down into a visit
   * @param {(visit: object) => void} options.onPass show another pass
   */
  constructor({ root, stepTemplate, loadStep, onSelect, onOpen, onPass }) {
    this.root = root;
    this.stepTemplate = stepTemplate;
    this.loadStep = loadStep;
    this.handlers = { onSelect, onOpen, onPass };
    this.kind = root.querySelector("[data-panel-kind]");
    this.title = root.querySelector("[data-panel-title]");
    this.chips = root.querySelector("[data-panel-chips]");
    this.facts = root.querySelector("[data-panel-facts]");
    this.passes = root.querySelector("[data-panel-passes]");
    this.passText = root.querySelector("[data-pass-text]");
    this.path = root.querySelector("[data-panel-path]");
    this.pathEmpty = root.querySelector("[data-panel-path-empty]");
    this.detail = root.querySelector("[data-panel-detail]");
    this.outputs = new Map(); // step id -> the loaded step
    this.view = null;
    root.querySelector("[data-pass-prev]").addEventListener("click", () => this.#pass(-1));
    root.querySelector("[data-pass-next]").addEventListener("click", () => this.#pass(1));
    this.path.addEventListener("keydown", (event) => this.#onKeydown(event));
  }

  /**
   * @param {object} view
   * @param {import("./visit-model.js").FlowModel} view.model
   * @param {object} view.visit
   * @param {{entries: object[], states: Map}} view.walk
   * @param {string|null} view.selected node id
   */
  render(view) {
    this.view = view;
    const { model, visit, walk } = view;
    const refocus = this.path.contains(document.activeElement) ? document.activeElement.closest("[data-position]")?.dataset.position : null;
    const title = model.titleOf(visit);
    this.kind.textContent = title.graph.kind === "action" ? "Action" : "Pipeline";
    this.title.textContent = title.stage ? `${title.stage} › ${title.name}` : title.name;

    const chip = el("span", "history-chip");
    chip.append(el("span"), el("span"));
    chip.firstElementChild.dataset.chipIcon = "";
    chip.lastElementChild.dataset.chipText = "";
    setChip(chip, visit.outcome ?? "stopped");
    this.chips.replaceChildren(chip);
    this.#facts(visit);
    this.#passes(model, visit);
    this.#path(walk, view.selected);
    this.#details(view);
    if (refocus != null) this.path.querySelector(`[data-position="${refocus}"] .ef-path__main`)?.focus({ preventScroll: true });
  }

  focusTitle() {
    this.title.focus();
  }

  /** Move the focus to the entry of a node (the first time it was reached). */
  focusNode(nodeId) {
    this.path.querySelector(`[data-node-id="${CSS.escape(nodeId)}"] .ef-path__main`)?.focus();
  }

  #facts(visit) {
    const rows = [
      ["Started", visit.started_at ? formatTime(visit.started_at) : ""],
      ["Duration", visit.started_at && visit.finished_at ? formatDuration(visitSeconds(visit)) : ""],
      ["Left by", visit.left_port ? (visit.left_port === "error" ? "On Error" : "On Pass") : ""],
    ].filter(([, value]) => value !== "");
    this.facts.replaceChildren(...rows.flatMap(([term, value]) => [el("dt", "", term), el("dd", "", value)]));
  }

  #passes(model, visit) {
    const all = model.passes(visit);
    this.passes.hidden = all.length < 2;
    if (all.length < 2) return;
    const at = all.indexOf(visit);
    this.passText.textContent = `Pass ${at + 1} of ${all.length}`;
    this.passes.querySelector("[data-pass-prev]").disabled = at === 0;
    this.passes.querySelector("[data-pass-next]").disabled = at === all.length - 1;
  }

  #pass(step) {
    const all = this.view.model.passes(this.view.visit);
    const next = all[all.indexOf(this.view.visit) + step];
    if (next) this.handlers.onPass(next);
  }

  // ── the walked nodes ────────────────────────────────────────────────

  #path(walk, selected) {
    this.pathEmpty.hidden = walk.entries.length > 0;
    const items = walk.entries.map((entry) => this.#pathItem(entry, selected));
    this.path.replaceChildren(...items);
    this.#roving(selected);
  }

  #pathItem(entry, selected) {
    const { node } = entry;
    const li = el("li", "ef-path__item");
    li.dataset.position = String(entry.position);
    li.dataset.nodeId = entry.id;
    li.dataset.state = entry.state;
    li.classList.toggle("is-selected", entry.id === selected);

    const main = el("button", "ef-path__main");
    main.type = "button";
    const kind = typeOf(node);
    const exit = entry.step?.exit_code != null ? `exit code ${entry.step.exit_code}` : null;
    const took = entry.step && WORKS.includes(entry.step.kind) ? stepDuration(entry.step) : null;
    main.setAttribute("aria-label", [`${entry.position + 1} ${kind.label}: ${nameOf(node)}`, STATES[entry.state][1], exit, took, entry.children.length ? "Enter opens it" : null].filter(Boolean).join(", "));
    main.setAttribute("aria-current", String(entry.id === selected));
    const seq = el("span", "ef-path__seq", String(entry.position + 1));
    const name = el("span", "ef-path__name");
    name.append(el("span", "ef-path__label", nameOf(node)), el("span", "ef-path__kind", kind.label));
    const facts = [exit && exit.replace("exit code", "exit"), took].filter(Boolean).join(" · ");
    main.append(seq, name, this.#stateChip(entry.state), ...(facts ? [el("span", "ef-path__facts", facts)] : []));
    main.addEventListener("click", () => this.handlers.onSelect(entry.id));
    li.append(main);

    entry.children.forEach((child, i) => {
      const open = el("button", "button button--ghost button--sm ef-path__open", entry.children.length > 1 ? `Open pass ${i + 1}` : "Open");
      open.type = "button";
      open.setAttribute("aria-label", `Open ${nameOf(node)}${entry.children.length > 1 ? `, pass ${i + 1}` : ""}`);
      open.addEventListener("click", () => this.handlers.onOpen(child));
      li.append(open);
    });
    return li;
  }

  #stateChip(state) {
    const [word, , glyph] = STATES[state];
    const chip = el("span", "history-chip ef-path__state");
    chip.dataset.status = state === "pass" || state === "fail" || state === "running" ? state : "stopped";
    const symbol = el("span");
    if (glyph) symbol.append(icon(glyph));
    chip.append(symbol, el("span", "", word));
    return chip;
  }

  /** Only the selected (else the first) entry is in the tab order; the arrow keys move between them. */
  #roving(selected) {
    const mains = [...this.path.querySelectorAll(".ef-path__main")];
    const current = mains.find((m) => m.closest("[data-node-id]").dataset.nodeId === selected) ?? mains[0];
    for (const main of mains) main.tabIndex = main === current ? 0 : -1;
  }

  #onKeydown(event) {
    const main = event.target.closest(".ef-path__main");
    if (!main) return;
    const mains = [...this.path.querySelectorAll(".ef-path__main")];
    const at = mains.indexOf(main);
    const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: mains.length - 1 }[event.key];
    if (to !== undefined) {
      event.preventDefault();
      const next = mains[Math.min(Math.max(to, 0), mains.length - 1)];
      for (const m of mains) m.tabIndex = m === next ? 0 : -1;
      next.focus();
      this.handlers.onSelect(next.closest("[data-node-id]").dataset.nodeId);
    } else if (event.key === "Enter") {
      const entry = this.view.walk.entries[Number(main.closest("[data-position]").dataset.position)];
      if (entry.children.length) {
        event.preventDefault();
        this.handlers.onOpen(entry.children[0]);
      }
    }
  }

  // ── the selected node ───────────────────────────────────────────────

  #details(view) {
    const open = new Set([...this.detail.querySelectorAll("details[open]")].map((block) => block.dataset.key));
    const { model, visit, walk, selected } = view;
    const node = selected ? model.graph(visit).nodes.find((n) => n.id === selected) : null;
    if (!node) {
      this.detail.replaceChildren(el("p", "ef-panel__note", "Select a node of the path or of the canvas to see what happened there."));
      return;
    }
    const info = walk.states.get(node.id);
    const entries = walk.entries.filter((e) => e.id === node.id);
    const body = [el("h4", "ef-detail__name", nameOf(node)), el("p", "ef-panel__note", `${typeOf(node).label} · ${STATES[info.state][0]}`)];
    if (info.state === "not-run" || info.state === "skipped") {
      body.push(el("p", "ef-panel__note", info.state === "skipped" ? "The execution started after this node, so it was skipped." : "This node did not run in this pass."));
    }
    for (const entry of entries) {
      if (entry.step) body.push(this.#step(entry.step, open));
      for (const [i, child] of entry.children.entries()) {
        const button = el("button", "button button--ghost button--sm", entry.children.length > 1 ? `Open pass ${i + 1}` : `Open ${typeOf(node).label.toLowerCase()}`);
        button.type = "button";
        button.addEventListener("click", () => this.handlers.onOpen(child));
        body.push(button);
      }
      if (!entry.step && !entry.children.length && (node.kind === "action" || node.kind === "pipeline")) {
        body.push(el("p", "ef-panel__note", node.definition_id ? "It ran no steps." : "This action has no definition, so nothing ran."));
      }
    }
    this.detail.replaceChildren(...body);
  }

  /** A step as in the History tab; its output is fetched when the block is opened, not before. */
  #step(step, open) {
    const item = fillStep(this.stepTemplate, this.outputs.get(step.id) ?? step, open);
    const block = item.querySelector("[data-step-output]");
    const pre = block.querySelector("pre");
    const truncated = item.querySelector("[data-step-truncated]");
    const load = async () => {
      if (this.outputs.has(step.id) || block.dataset.loading) return;
      block.dataset.loading = "1";
      pre.textContent = "Loading...";
      try {
        const full = await this.loadStep(step);
        this.outputs.set(step.id, full);
        pre.textContent = full.output;
        truncated.hidden = !full.output_truncated;
      } catch {
        pre.textContent = "The output could not be loaded. Close and open it to try again.";
      } finally {
        delete block.dataset.loading;
      }
    };
    block.addEventListener("toggle", () => block.open && load());
    if (block.open && !block.hidden) load();
    return item;
  }
}
