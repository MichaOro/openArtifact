/* One execution of the history: the summary and its steps in order. Everything is text (textContent,
 * never innerHTML): output, reasons and data come from what ran. renderFacts() and renderStep() are
 * the parts to override or to add to; show() / update() are what the tab calls. The flow of the
 * execution is a page of its own (static/js/execution/); this view links to it ("Open flow"). */
import { executionSeconds, formatDuration, formatTime, originLabel, setChip } from "./history-format.js";
import { contextBlock } from "./context-block.js";
import { getStep } from "./history-api.js";
import { fillStep } from "./history-step.js";
import { t } from "../i18n.js";

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
    this.contextHost = root.querySelector("[data-detail-context]");
    this.stepTemplate = document.getElementById("history-step-template");
    this.deleteButton = root.querySelector("[data-detail-delete]");
    this.flowLink = root.querySelector("[data-detail-flow]");
    this.taskNumber = null; // set by the tab: the flow page's URL names the artifact by its number
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
    this.contextHost.replaceChildren();
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
    this.renderContext(detail.context);
  }

  /** The run context of the execution, read-only and collapsed (kept open if the user had opened it). */
  renderContext(context) {
    const wasOpen = this.contextHost.querySelector("details")?.open ?? false;
    const block = contextBlock({ key: "context", open: wasOpen });
    block.show(context);
    this.contextHost.replaceChildren(block);
  }

  focusHeading() {
    this.heading.focus();
  }

  renderSummary(execution) {
    this.heading.textContent = t("tasks.history_detail.execution_number", { number: execution.number });
    const running = execution.status === "running";
    this.deleteButton.setAttribute("aria-disabled", String(running));
    this.deleteButton.title = running ? t("tasks.history_detail.stop_first") : "";
    this.flowLink.href = this.flowHref(execution);
    this.note.textContent = execution.note ?? "";
    this.note.hidden = !execution.note;
    this.renderFacts(execution);
  }

  /** Where the read-only flow of the execution is shown (a page of its own; the same URL the global menu will use). */
  flowHref(execution) {
    return `/artifacts/${encodeURIComponent(this.taskNumber ?? execution.task_id)}/executions/${encodeURIComponent(execution.id)}`;
  }

  /** The summary list: a term and its value (text or a node) per line. */
  renderFacts(execution) {
    const chip = this.stepTemplate.content.querySelector("[data-step-outcome]").cloneNode(true);
    chip.removeAttribute("data-step-outcome");
    setChip(chip, execution.status);
    const startedAt = [execution.started_stage_name, execution.started_action_name].filter(Boolean).join(" › ");
    const rows = [
      [t("common.status"), chip],
      [t("executions.started"), this.#time(execution.started_at)],
      [t("executions.duration"), formatDuration(executionSeconds(execution))],
      [t("common.pipeline"), execution.pipeline_name ?? ""],
      [t("execution.flow_page.started_at"), startedAt],
      [t("executions.started_by"), originLabel(execution.started_by)],
      [t("common.steps"), String(execution.step_count ?? this.steps.children.length)],
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
    const execution = this.execution;
    return fillStep(this.stepTemplate, step, open, { loadDetail: (one) => getStep(execution.task_id, execution.id, one.id) });
  }
}
