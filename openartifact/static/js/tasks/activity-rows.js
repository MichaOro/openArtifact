/* The rows of the timeline that are not live executions: what changed on the artifact, and the quiet trace of an
 * execution that was deleted. They share one <ul> with the execution rows (HistoryList) and sit among them by time.
 * Built from <template id="activity-row-template"> and <template id="trace-row-template"> with textContent only;
 * nothing here is interactive. */
import { avatar } from "../components/avatar.js";
import { fillDuration, fillOrigin, fillTime, placeByTime } from "./history-row.js";
import { originLabel, setChip } from "./history-format.js";
import { kindOf } from "./comment-format.js";
import { sentenceOf, timeOf, traceAsExecution } from "./activity-model.js";
import { t } from "../i18n.js";

export class ActivityRows {
  /** @param {HTMLElement} root the <ul> of the timeline */
  constructor(root) {
    this.root = root;
    this.change = document.getElementById("activity-row-template");
    this.trace = document.getElementById("trace-row-template");
    /** @type {Map<string, HTMLElement>} */
    this.rows = new Map();
  }

  /** Show exactly these items ({type: "change"|"trace", key, at, entry}); rows of other items go. */
  render(items) {
    const keep = new Set(items.map((item) => item.key));
    for (const [key, row] of this.rows) {
      if (!keep.has(key)) {
        row.remove();
        this.rows.delete(key);
      }
    }
    for (const item of items) {
      let row = this.rows.get(item.key);
      if (!row) {
        row = (item.type === "trace" ? this.#trace(item.entry) : this.#change(item.entry));
        this.rows.set(item.key, row);
      }
      placeByTime(this.root, row, timeOf(item));
    }
  }

  clear() {
    this.render([]);
  }

  #change(entry) {
    const row = this.change.content.firstElementChild.cloneNode(true);
    row.dataset.kind = entry.kind;
    row.dataset.group = "change";
    const kind = kindOf({ author_kind: entry.actor_kind });
    row.querySelector("[data-event-avatar]").replaceWith(avatar({ kind: entry.actor_kind, label: kind.label, icon: kind.icon }));
    row.querySelector("[data-event-actor]").textContent = entry.actor_name;
    row.querySelector("[data-event-sentence]").textContent = sentenceOf(entry);
    fillTime(row.querySelector("[data-event-time]"), entry.created_at);
    return row;
  }

  #trace(entry) {
    const execution = traceAsExecution(entry);
    const row = this.trace.content.firstElementChild.cloneNode(true);
    row.dataset.group = "run";
    row.dataset.status = execution.status;
    row.dataset.executionId = execution.id ?? "";
    row.title = t("tasks.activity.execution_was_deleted");
    setChip(row.querySelector(".history-chip"), execution.status);
    row.querySelector("[data-row-number]").textContent = `#${execution.number}`;
    fillTime(row.querySelector("[data-row-time]"), execution.started_at);
    fillDuration(row.querySelector("[data-row-duration]"), execution);
    row.querySelector("[data-row-pipeline]").textContent = execution.pipeline_name;
    fillOrigin(row.querySelector("[data-row-meta]"), execution.started_by, `${originLabel(execution.started_by)} · ${t("tasks.activity.deleted")}`);
    return row;
  }
}
