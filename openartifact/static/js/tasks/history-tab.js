/* The History tab of the artifact dialog: one timeline of what happened to the shown artifact: its executions (live
 * rows you can open and delete) and the changes made to it, with the quiet trace an execution leaves when it is
 * deleted (ADR-058). Orchestrates the rows (HistoryList for executions, ActivityRows for the rest) and one execution
 * (HistoryDetail); owns what they share: the loaded data, the filter, the live events and the confirmation of deletes.
 *
 * The tab follows the artifact the dialog shows (show / hide) and is kept current by the page's one event stream:
 * execution.updated, execution.deleted and activity.created reach it through handleEvent(). */
import { AlertBar } from "../components/alert-bar.js";
import { listActivity } from "./activity-api.js";
import { ActivityRows } from "./activity-rows.js";
import { filterTimeline, mergeTimeline, withEntry } from "./activity-model.js";
import { clearExecutions, deleteExecution, getExecution, listExecutions } from "./history-api.js";
import { HistoryDetail } from "./history-detail.js";
import { plural } from "./history-format.js";
import { HistoryList } from "./history-list.js";
import { t } from "../i18n.js";

const REFETCH_MS = 300;

export class HistoryTab {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the panel (templates/components/history_panel.html)
   * @param {HTMLElement} options.badge the count on the tab
   * @param {import("../components/confirm-dialog.js").ConfirmDialog} options.confirm
   */
  constructor({ root, badge, confirm }) {
    this.root = root;
    this.badge = badge;
    this.confirm = confirm;
    this.taskId = null;
    this.total = 0;
    this.limit = 100;
    this.token = 0;
    this.refetchTimer = null;
    this.deleted = new Set(); // ids deleted here: a late status event must not bring them back
    this.notice = "";
    this.activity = []; // the activity entries loaded, newest first
    this.next = null; // the cursor of the next, older page of them
    this.filter = "all";

    this.alert = new AlertBar(root.querySelector("[data-history-alert]"));
    this.alert.onRetry(() => this.#retry());
    this.live = root.querySelector("[data-history-live]");
    this.listView = root.querySelector("[data-history-list-view]");
    this.summary = root.querySelector("[data-history-summary]");
    this.empty = root.querySelector("[data-history-empty]");
    this.more = root.querySelector("[data-history-more]");
    this.clearButton = root.querySelector("[data-history-clear]");
    this.older = root.querySelector("[data-history-older]");
    this.filterButtons = [...root.querySelectorAll("[data-history-filter] [data-filter]")];
    this.list = new HistoryList({
      root: root.querySelector("[data-history-rows]"),
      onOpen: (execution) => this.#open(execution),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.rows = new ActivityRows(root.querySelector("[data-history-rows]"));
    this.detail = new HistoryDetail({
      root: root.querySelector("[data-history-detail]"),
      onBack: () => this.#back(),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.clearButton.addEventListener("click", () => this.#confirmClear());
    this.older.addEventListener("click", () => this.#loadOlder());
    for (const button of this.filterButtons) button.addEventListener("click", () => this.#setFilter(button.dataset.filter));
  }

  /** The dialog shows this artifact: start from its list (a reopened one keeps what it had until the fresh data arrives). */
  show(task) {
    const same = task.id === this.taskId;
    this.taskId = task.id;
    this.detail.taskNumber = task.number;
    this.#showList();
    if (!same) {
      this.list.render([]);
      this.activity = [];
      this.next = null;
      this.total = 0;
      this.notice = "";
      this.deleted.clear();
      this.alert.hide();
      this.#render();
    }
    this.load();
  }

  /** The dialog closed: stop listening and ticking. */
  hide() {
    this.taskId = null;
    this.token++;
    window.clearTimeout(this.refetchTimer);
    this.list.dispose();
    this.detail.execution = null;
  }

  /** Fetch the list; a failed fetch keeps what is shown. Also the resync after a reconnect. */
  async load() {
    const taskId = this.taskId;
    if (!taskId) return;
    const token = ++this.token;
    try {
      const [data, page] = await Promise.all([listExecutions(taskId, this.limit), listActivity(taskId)]);
      if (token !== this.token) return;
      this.list.render(data.items);
      this.total = data.total;
      this.activity = page.items;
      this.next = page.next;
      this.alert.hide();
      this.#render();
      if (this.#detailShown()) this.#refetchDetail();
    } catch (error) {
      if (token === this.token) this.alert.show(error.message || t("tasks.history_tab.history_could_not_be_loaded"), { retry: true });
    }
  }

  /** execution.updated / execution.deleted / activity.created of the event stream. */
  handleEvent(type, data) {
    if (!this.taskId || data.task_id !== this.taskId) return;
    if (type === "activity.created") {
      this.activity = withEntry(this.activity, data);
      this.#render();
      return;
    }
    if (type === "execution.deleted") {
      const known = this.list.get(data.id) ?? (this.detail.executionId === data.id ? this.detail.execution : null);
      if (known) this.#vanished(known);
      return;
    }
    const execution = data.execution;
    if (this.deleted.has(execution.id)) return;
    if (!this.list.get(execution.id)) this.total += 1;
    this.list.upsert(execution);
    this.#render();
    if (this.#detailShown() && this.detail.executionId === execution.id) {
      this.detail.patchSummary(execution);
      this.#refetchDetail(REFETCH_MS);
    }
  }

  #detailShown() {
    return !this.root.querySelector("[data-history-detail]").hidden;
  }

  /** Bring the rows, the filter, the counts and the empty state in line with the data. */
  #render() {
    const count = this.list.size;
    const finished = this.list.executions.some((execution) => execution.status !== "running");
    const items = mergeTimeline(this.list.executions, this.activity);
    this.rows.render(items.filter((item) => item.type !== "execution"));
    const group = { runs: "run", changes: "change" }[this.filter];
    for (const row of this.root.querySelectorAll("[data-history-rows] > li")) row.hidden = group !== undefined && row.dataset.group !== group;
    const shown = filterTimeline(items, this.filter).length;
    const more = this.next !== null || this.total > count;
    this.badge.hidden = this.taskId === null || items.length === 0;
    this.badge.textContent = this.badge.hidden ? "" : `${items.length}${more ? "+" : ""}`;
    this.badge.title = plural(items.length, "entry");
    this.summary.textContent = [this.notice, plural(items.length, "entry")].filter(Boolean).join(" ");
    this.empty.hidden = shown > 0;
    this.empty.textContent = {
      all: t("history.nothing_recorded_yet"),
      runs: t("history.no_executions_yet_start_processing_this"),
      changes: t("history.no_changes_recorded_yet"),
    }[this.filter];
    this.more.hidden = this.total <= count;
    this.more.textContent = t("tasks.history_tab.showing_newest_count_total_executions", { count, total: this.total });
    this.older.hidden = this.next === null;
    this.clearButton.setAttribute("aria-disabled", String(!finished));
    for (const button of this.filterButtons) button.setAttribute("aria-pressed", String(button.dataset.filter === this.filter));
  }

  #setFilter(filter) {
    this.filter = filter;
    this.#render();
  }

  /** The next, older page of the changes. */
  async #loadOlder() {
    const { taskId, next } = this;
    if (!taskId || next === null) return;
    try {
      const page = await listActivity(taskId, { before: next });
      if (taskId !== this.taskId) return;
      const known = new Set(this.activity.map((entry) => entry.id));
      this.activity = [...this.activity, ...page.items.filter((entry) => !known.has(entry.id))];
      this.next = page.next;
      this.alert.hide();
      this.#render();
    } catch (error) {
      if (taskId === this.taskId) this.alert.show(error.message || t("tasks.history_tab.history_could_not_be_loaded"), { retry: true });
    }
  }

  announce(message) {
    this.live.textContent = "";
    window.requestAnimationFrame(() => (this.live.textContent = message));
  }

  // ── the detail ──────────────────────────────────────────────────────

  #open(execution) {
    this.listView.hidden = true;
    this.root.querySelector("[data-history-detail]").hidden = false;
    this.detail.show(execution);
    this.detail.focusHeading();
    this.#refetchDetail();
  }

  #showList() {
    window.clearTimeout(this.refetchTimer);
    this.root.querySelector("[data-history-detail]").hidden = true;
    this.listView.hidden = false;
  }

  #back() {
    const id = this.detail.executionId;
    this.#showList();
    this.list.focus(id);
  }

  #refetchDetail(delay = 0) {
    window.clearTimeout(this.refetchTimer);
    this.refetchTimer = window.setTimeout(async () => {
      const { taskId } = this;
      const id = this.detail.executionId;
      if (!taskId || !id) return;
      try {
        const detail = await getExecution(taskId, id);
        if (taskId === this.taskId && id === this.detail.executionId && this.#detailShown()) {
          this.detail.update(detail);
          this.alert.hide();
        }
      } catch (error) {
        if (taskId !== this.taskId || id !== this.detail.executionId) return;
        if (error.status === 404) this.#vanished(this.detail.execution);
        else this.alert.show(error.message || t("tasks.history_tab.execution_could_not_be_loaded"), { retry: true });
      }
    }, delay);
  }

  #retry() {
    if (this.#detailShown()) this.#refetchDetail();
    else this.load();
  }

  /** The execution was deleted elsewhere: drop it; if it was open, say so and go back to the list. */
  #vanished(execution) {
    const wasOpen = this.#detailShown() && this.detail.executionId === execution.id;
    this.#removed(execution);
    if (!wasOpen) return;
    this.notice = t("tasks.history_tab.execution_number_was_deleted", { number: execution.number });
    this.#render();
    this.announce(this.notice);
    this.list.focus(null);
  }

  // ── deleting ────────────────────────────────────────────────────────

  #confirmDelete(execution) {
    let next = null;
    this.confirm.open({
      message: t("executions.page.delete_subject_cannot_be_undone"),
      subject: t("tasks.history_tab.execution_number", { number: execution.number }),
      note: t("executions.page.its_steps_deleted_with"),
      onConfirm: async () => {
        try {
          await deleteExecution(this.taskId, execution.id);
        } catch (error) {
          if (error.status !== 404) throw error; // gone already is what was wanted
        }
        next = this.#removed(execution);
      },
      onClose: () => this.list.focus(next), // after a delete the focus moves on to the next row, else the list
    });
  }

  /** Drop the execution everywhere; an open detail goes back to the list. Returns the row to focus next. */
  #removed(execution) {
    this.deleted.add(execution.id);
    const next = this.list.neighbour(execution.id);
    if (this.list.get(execution.id)) this.total = Math.max(0, this.total - 1);
    this.list.remove(execution.id);
    this.notice = "";
    if (this.#detailShown() && this.detail.executionId === execution.id) this.#showList();
    this.#render();
    this.announce(t("tasks.history_tab.execution_number_deleted", { number: execution.number }));
    return next;
  }

  #confirmClear() {
    if (this.clearButton.getAttribute("aria-disabled") === "true") return;
    this.confirm.open({
      message: t("tasks.history_tab.delete_all_finished_executions_artifact"),
      note: t("tasks.history_tab.running_execution_not_deleted"),
      confirmLabel: t("tasks.history_tab.delete_all"),
      onConfirm: async () => {
        const { deleted } = await clearExecutions(this.taskId);
        this.announce(t("executions.page.deleted_count", { what: plural(deleted, "execution") }));
        await this.load();
      },
      onClose: () => this.clearButton.focus(),
    });
  }
}
