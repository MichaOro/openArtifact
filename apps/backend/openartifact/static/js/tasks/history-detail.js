/* One execution of the history: the summary and its steps in order. Everything is text (textContent,
 * never innerHTML): output, reasons and data come from what ran. A later stage that shows the process
 * flow of an execution extends this class: renderFacts() and renderStep() are the parts to override or
 * to add to; show() / update() are what the tab calls. */
import { icon } from "../components/icons.js";
import { executionSeconds, formatDuration, formatTime, originLabel, secondsBetween, setChip } from "./history-format.js";

const KIND_ICONS = { code: "code", http: "http", timer: "clock", trigger: "play", output: "check" };
const PORTS = { pass: "On Pass", fail: "On Fail", out: "Next" };

export class HistoryDetail {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the detail section
   * @param {() => void} options.onBack
   * @param {(execution: object) => void} options.onDelete
   */
  constructor({ root, onBack, onDelete }) {
    this.root = root;
    this.heading = root.querySelector("[data-detail-heading]");
    this.facts = root.querySelector("[data-detail-facts]");
    this.note = root.querySelector("[data-detail-note]");
    this.steps = root.querySelector("[data-detail-steps]");
    this.empty = root.querySelector("[data-detail-empty]");
    this.stepTemplate = document.getElementById("history-step-template");
    this.deleteButton = root.querySelector("[data-detail-delete]");
    this.execution = null;
    this.loaded = false;
    root.querySelector("[data-detail-back]").addEventListener("click", () => onBack());
    this.deleteButton.addEventListener("click", () => {
      if (this.deleteButton.getAttribute("aria-disabled") !== "true") onDelete(this.execution);
    });
  }

  get executionId() {
    return this.execution?.id ?? null;
  }

  /** Start showing an execution from its summary; the steps follow with update(). */
  show(summary) {
    this.execution = summary;
    this.loaded = false;
    this.steps.replaceChildren();
    this.empty.hidden = true;
    this.renderSummary(summary);
  }

  /** The summary changed (an execution.updated event); the steps are fetched again by the caller. */
  patchSummary(summary) {
    this.execution = { ...this.execution, ...summary };
    this.renderSummary(this.execution);
  }

  /** The execution with its steps. */
  update(detail) {
    this.execution = detail;
    this.loaded = true;
    this.renderSummary(detail);
    const open = new Set([...this.steps.querySelectorAll("details[open]")].map((block) => block.dataset.key));
    this.steps.replaceChildren(...(detail.steps ?? []).map((step) => this.renderStep(step, open)));
    this.empty.hidden = !this.loaded || this.steps.children.length > 0;
  }

  focusHeading() {
    this.heading.focus();
  }

  renderSummary(execution) {
    this.heading.textContent = `Execution #${execution.number}`;
    const running = execution.status === "running";
    this.deleteButton.setAttribute("aria-disabled", String(running));
    this.deleteButton.title = running ? "Stop it first" : "";
    this.note.textContent = execution.note ?? "";
    this.note.hidden = !execution.note;
    this.renderFacts(execution);
  }

  /** The summary list: a term and its value (text or a node) per line. */
  renderFacts(execution) {
    const chip = this.stepTemplate.content.querySelector("[data-step-outcome]").cloneNode(true);
    chip.removeAttribute("data-step-outcome");
    setChip(chip, execution.status);
    const startedAt = [execution.started_stage_name, execution.started_action_name].filter(Boolean).join(" › ");
    const rows = [
      ["Status", chip],
      ["Started", this.#time(execution.started_at)],
      ["Duration", formatDuration(executionSeconds(execution))],
      ["Pipeline", execution.pipeline_name ?? ""],
      ["Started at", startedAt],
      ["Started by", originLabel(execution.started_by)],
      ["Steps", String(execution.step_count ?? this.steps.children.length)],
    ];
    this.facts.replaceChildren(
      ...rows.filter(([, value]) => value !== "").flatMap(([term, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = term;
        const dd = document.createElement("dd");
        dd.append(value);
        return [dt, dd];
      }),
    );
  }

  #time(iso) {
    const time = document.createElement("time");
    time.textContent = formatTime(iso);
    time.title = iso;
    time.dateTime = iso;
    return time;
  }

  /** One step as a list item. `open` holds the keys of the blocks the user had opened. */
  renderStep(step, open = new Set()) {
    const item = this.stepTemplate.content.firstElementChild.cloneNode(true);
    item.dataset.stepId = step.id;
    item.dataset.outcome = step.outcome;
    item.dataset.kind = step.kind;
    item.style.setProperty("--depth", String(step.depth ?? 0));
    item.querySelector("[data-step-seq]").textContent = String(step.seq);
    item.querySelector("[data-step-kind-icon]").replaceChildren(icon(KIND_ICONS[step.kind] ?? "action"));
    item.querySelector("[data-step-name]").textContent = step.node_name ?? step.kind;
    item.querySelector("[data-step-kind]").textContent = step.kind;
    setChip(item.querySelector("[data-step-outcome]"), step.outcome);

    const where = [step.stage_name, step.action_name].filter(Boolean).join(" › ");
    const whereEl = item.querySelector("[data-step-where]");
    whereEl.textContent = where;
    whereEl.hidden = !where;

    const facts = [
      step.port ? `Port: ${PORTS[step.port] ?? step.port}` : null,
      step.exit_code != null ? `Exit code: ${step.exit_code}` : null,
      this.#stepDuration(step),
    ].filter(Boolean);
    const factsEl = item.querySelector("[data-step-facts]");
    factsEl.textContent = facts.join(" · ");
    factsEl.hidden = facts.length === 0;

    const reason = item.querySelector("[data-step-reason]");
    reason.textContent = step.reason ? `Reason: ${step.reason}` : "";
    reason.hidden = !step.reason;

    this.#block(item.querySelector("[data-step-output]"), `${step.id}:output`, step.output, open);
    item.querySelector("[data-step-truncated]").hidden = !step.output_truncated;
    this.#block(item.querySelector("[data-step-data]"), `${step.id}:data`, step.data == null ? "" : JSON.stringify(step.data, null, 2), open);
    return item;
  }

  #stepDuration(step) {
    const seconds = secondsBetween(step.started_at, step.finished_at);
    return seconds == null || !step.finished_at ? null : formatDuration(seconds);
  }

  #block(details, key, text, open) {
    details.hidden = !text;
    details.dataset.key = key;
    details.open = open.has(key);
    details.querySelector("pre").textContent = text;
  }
}
