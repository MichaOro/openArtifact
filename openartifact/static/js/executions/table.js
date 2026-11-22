/* The rows of the global execution list, newest first, built from <template id="ex-row-template"> with
 * textContent only. Rows are appended in the order the server gives them (pages follow one another) and
 * updated in place afterwards; they never move, so nothing shifts under the cursor.
 *
 * The execution link of a row is its primary action (it opens the flow). A click anywhere else on the row
 * does the same for the mouse; the artifact and pipeline links and the delete button keep their own meaning. */
import { setChip, plural } from "../tasks/history-format.js";
import { fillDeleteButton, fillDuration, fillOrigin, fillTime, RunningClock } from "../tasks/history-row.js";

export const flowUrl = (e) => `/artifacts/${e.task.number}/executions/${encodeURIComponent(e.id)}`;
export const artifactUrl = (e) => `/?artifact=${e.task.number}`;
export const pipelineUrl = (e) => `/pipelines/${encodeURIComponent(e.pipeline_id)}`;

export class ExecutionTable {
  /**
   * @param {object} options
   * @param {HTMLElement} options.body the <tbody>
   * @param {(execution: object) => void} options.onDelete the delete button of a row was pressed
   * @param {(url: string) => void} options.onNavigate a click on the row itself (not on a link or button)
   */
  constructor({ body, onDelete, onNavigate = (url) => window.location.assign(url) }) {
    this.body = body;
    this.template = document.getElementById("ex-row-template");
    /** @type {Map<string, {execution: object, row: HTMLElement}>} */
    this.entries = new Map();
    this.clock = new RunningClock(() => {
      for (const { execution, row } of this.entries.values()) if (execution.status === "running") fillDuration(row.querySelector("[data-duration]"), execution);
    });
    body.addEventListener("click", (event) => {
      const row = event.target.closest(".ex-row");
      const entry = row && this.entries.get(row.dataset.executionId);
      if (!entry) return;
      const button = event.target.closest("[data-delete]");
      if (button) {
        if (button.getAttribute("aria-disabled") !== "true") onDelete(entry.execution);
      } else if (!event.target.closest("a") && !window.getSelection()?.toString()) onNavigate(flowUrl(entry.execution));
    });
  }

  get size() {
    return this.entries.size;
  }

  /** The oldest start among the rows (ms since the epoch); null when empty. */
  get oldestStart() {
    const times = [...this.entries.values()].map(({ execution }) => Date.parse(execution.started_at));
    return times.length ? Math.min(...times) : null;
  }

  get(id) {
    return this.entries.get(id)?.execution;
  }

  /** Replace everything shown. */
  replace(executions) {
    for (const { row } of this.entries.values()) row.remove();
    this.entries.clear();
    this.append(executions);
  }

  /** Add rows at the end (the next page); a row that is already there is updated instead. */
  append(executions) {
    const fresh = [];
    for (const execution of executions) {
      const row = this.upsert(execution);
      if (row) fresh.push(row);
    }
    return fresh;
  }

  /** Update the row of a known execution in place with new summary fields; returns false if it is not shown. */
  patch(summary) {
    const entry = this.entries.get(summary.id);
    if (!entry) return false;
    this.upsert({ ...entry.execution, ...summary, task: entry.execution.task, pipeline_exists: entry.execution.pipeline_exists });
    return true;
  }

  /** Add the row at the end if new, else update it; returns the new row (undefined for an update). */
  upsert(execution) {
    let entry = this.entries.get(execution.id);
    const isNew = !entry;
    if (!entry) {
      entry = { execution, row: this.template.content.firstElementChild.cloneNode(true) };
      this.entries.set(execution.id, entry);
      this.body.append(entry.row);
    }
    entry.execution = execution;
    this.#fill(entry);
    this.clock.update(this.#anyRunning());
    return isNew ? entry.row : undefined;
  }

  remove(id) {
    const entry = this.entries.get(id);
    if (!entry) return;
    entry.row.remove();
    this.entries.delete(id);
    this.clock.update(this.#anyRunning());
  }

  /** The id of the row after (else before) this one, so focus can move on when it is deleted. */
  neighbour(id) {
    const row = this.entries.get(id)?.row;
    const near = row?.nextElementSibling ?? row?.previousElementSibling;
    return near?.dataset.executionId ?? null;
  }

  /** Focus a row's primary link (the table body when there is no such row). */
  focus(id) {
    (this.entries.get(id)?.row.querySelector("[data-open]") ?? this.body).focus();
  }

  dispose() {
    this.clock.dispose();
  }

  #anyRunning() {
    return [...this.entries.values()].some(({ execution }) => execution.status === "running");
  }

  #fill({ execution: e, row }) {
    row.dataset.executionId = e.id;
    row.dataset.status = e.status;
    setChip(row.querySelector(".history-chip"), e.status);
    const artifact = row.querySelector("[data-artifact]");
    artifact.textContent = `#${e.task.number} ${e.task.title}`;
    artifact.href = artifactUrl(e);
    artifact.title = "Open the artifact on the board";
    const open = row.querySelector("[data-open]");
    open.textContent = `#${e.number}`;
    open.href = flowUrl(e);
    open.setAttribute("aria-label", `Open the flow of execution #${e.number} of #${e.task.number}`);
    const link = row.querySelector("[data-pipeline-link]");
    const text = row.querySelector("[data-pipeline-text]");
    link.hidden = !e.pipeline_exists;
    text.hidden = e.pipeline_exists;
    (e.pipeline_exists ? link : text).textContent = e.pipeline_name;
    if (e.pipeline_exists) {
      link.href = pipelineUrl(e);
      link.title = "Open the pipeline in the editor";
    }
    row.querySelector("[data-pipeline-gone]").hidden = e.pipeline_exists;
    fillTime(row.querySelector("[data-time]"), e.started_at);
    fillDuration(row.querySelector("[data-duration]"), e);
    fillOrigin(row.querySelector("[data-origin]"), e.started_by);
    row.querySelector("[data-steps]").textContent = String(e.step_count);
    row.querySelector("[data-steps]").title = plural(e.step_count, "step");
    const note = row.querySelector("[data-note]");
    note.textContent = e.note ?? "";
    note.title = e.note ?? "";
    fillDeleteButton(row.querySelector("[data-delete]"), e, `execution #${e.number} of #${e.task.number}`);
  }
}
