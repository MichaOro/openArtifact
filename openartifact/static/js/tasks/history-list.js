/* The rows of the history list: one per execution, newest first, kept in place as executions are
 * created, change status or are deleted. Rows are built from <template id="history-row-template">
 * with textContent only. What a click does is up to the caller (onOpen, onDelete). */
import { originLabel, plural, setChip } from "./history-format.js";
import { fillDeleteButton, fillDuration, fillOrigin, fillTime, placeByTime, RunningClock } from "./history-row.js";
import { markerOf } from "./activity-model.js";
import { setMarker } from "./history-marker.js";

export class HistoryList {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the <ul>
   * @param {(execution: object) => void} options.onOpen a row was activated
   * @param {(execution: object) => void} options.onDelete the delete button of a row was pressed
   */
  constructor({ root, onOpen, onDelete }) {
    this.root = root;
    this.root.tabIndex = -1; // focus goes here when no row is left
    this.template = document.getElementById("history-row-template");
    this.onOpen = onOpen;
    this.onDelete = onDelete;
    /** @type {Map<string, {execution: object, row: HTMLElement}>} */
    this.entries = new Map();
    this.clock = new RunningClock(() => {
      for (const entry of this.entries.values()) if (entry.execution.status === "running") this.#duration(entry.row, entry.execution);
    });
    root.addEventListener("click", (event) => {
      const row = event.target.closest(".history-row");
      const entry = row && [...this.entries.values()].find((e) => e.row === row);
      if (!entry) return;
      if (event.target.closest("[data-row-delete]")) {
        if (event.target.closest("[data-row-delete]").getAttribute("aria-disabled") !== "true") this.onDelete(entry.execution);
      } else if (event.target.closest(".history-row__open")) this.onOpen(entry.execution);
    });
  }

  get size() {
    return this.entries.size;
  }

  get executions() {
    return [...this.entries.values()].map((entry) => entry.execution);
  }

  get(id) {
    return this.entries.get(id)?.execution;
  }

  /** Replace everything shown with `executions` (any order). */
  render(executions) {
    const keep = new Set(executions.map((execution) => execution.id));
    for (const id of [...this.entries.keys()]) if (!keep.has(id)) this.remove(id);
    for (const execution of executions) this.upsert(execution);
  }

  /** Add the execution, or update its row in place. */
  upsert(execution) {
    let entry = this.entries.get(execution.id);
    if (!entry) {
      entry = { execution, row: this.template.content.firstElementChild.cloneNode(true) };
      this.entries.set(execution.id, entry);
    }
    entry.execution = execution;
    this.#fill(entry);
    this.#place(entry);
    this.#tickWhileRunning();
  }

  remove(id) {
    const entry = this.entries.get(id);
    if (!entry) return;
    entry.row.remove();
    this.entries.delete(id);
    this.#tickWhileRunning();
  }

  /** The id of the row after (else before) this one, so focus can move on when it is deleted. */
  neighbour(id) {
    const row = this.entries.get(id)?.row;
    const idOf = new Map([...this.entries].map(([key, entry]) => [entry.row, key]));
    // the rows of changes and traces sit in the same list: only an execution row can take the focus
    for (const step of ["nextElementSibling", "previousElementSibling"]) {
      for (let el = row?.[step]; el; el = el[step]) if (idOf.has(el)) return idOf.get(el);
    }
    return null;
  }

  /** Focus a row's open button; the list itself when there is no such row. */
  focus(id, part = ".history-row__open") {
    (this.entries.get(id)?.row.querySelector(part) ?? this.root).focus();
  }

  /** Stop the clock of the running rows (the dialog closed). */
  dispose() {
    this.clock.dispose();
  }

  #fill({ execution: e, row }) {
    row.dataset.executionId = e.id;
    row.dataset.status = e.status;
    setMarker(row, markerOf({ type: "execution", execution: e }));
    setChip(row.querySelector(".history-chip"), e.status);
    row.querySelector("[data-row-number]").textContent = `#${e.number}`;
    row.querySelector("[data-row-dry]").hidden = !e.dry_run;
    fillTime(row.querySelector("[data-row-time]"), e.started_at);
    this.#duration(row, e);
    row.querySelector("[data-row-pipeline]").textContent = e.pipeline_name ?? "";
    fillOrigin(row.querySelector("[data-row-meta]"), e.started_by, `${originLabel(e.started_by)} · ${plural(e.step_count, "step")}`);
    const note = row.querySelector("[data-row-note]");
    note.textContent = e.note ?? "";
    note.hidden = !e.note;
    fillDeleteButton(row.querySelector("[data-row-delete]"), e, `execution #${e.number}`);
  }

  #duration(row, execution) {
    fillDuration(row.querySelector("[data-row-duration]"), execution);
  }

  /** Newest first, among the activity entries of the timeline too (they share this list, see activity-rows.js). */
  #place({ execution, row }) {
    row.dataset.number = String(execution.number);
    row.dataset.group = "runs";
    placeByTime(this.root, row, new Date(execution.started_at).getTime());
  }

  #tickWhileRunning() {
    this.clock.update(this.executions.some((execution) => execution.status === "running"));
  }
}
