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
import { COLLAPSED, collapse, filterTimeline, mergeTimeline, withEntry, withoutComment } from "./activity-model.js";
import { clearExecutions, deleteExecution, getExecution, listExecutions } from "./history-api.js";
import { HistoryDetail } from "./history-detail.js";
import { plural as countText } from "./history-format.js";
import { HistoryList } from "./history-list.js";
import { plural, t } from "../i18n.js";

const REFETCH_MS = 300;
/** Entries fetched at once: the artifact keeps at most 500, so a first page of 200 holds the anchor ("created") of most. */
const PAGE = 200;

export class HistoryTab {
  /**
   * @param {object} options
   * @param {HTMLElement} options.root the panel (templates/components/history_panel.html)
   * @param {HTMLElement} options.badge the count on the tab
   * @param {import("../components/confirm-dialog.js").ConfirmDialog} options.confirm
   * @param {(id: string) => object | undefined} options.commentOf a comment of the artifact by id (previews are read live)
   * @param {(commentId: string) => void} options.onJump a comment entry was activated: show that comment
   */
  constructor({ root, badge, confirm, commentOf, onJump }) {
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
    this.expanded = false; // the older entries are shown (GitHub-style "Show N older")

    this.alert = new AlertBar(root.querySelector("[data-history-alert]"));
    this.alert.onRetry(() => this.#retry());
    this.live = root.querySelector("[data-history-live]");
    this.listView = root.querySelector("[data-history-list-view]");
    this.summary = root.querySelector("[data-history-summary]");
    this.empty = root.querySelector("[data-history-empty]");
    this.more = root.querySelector("[data-history-more]");
    this.clearButton = root.querySelector("[data-history-clear]");
    this.filterButtons = [...root.querySelectorAll("[data-history-filter] [data-filter]")];
    this.list = new HistoryList({
      root: root.querySelector("[data-history-rows]"),
      onOpen: (execution) => this.#open(execution),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.rows = new ActivityRows(root.querySelector("[data-history-rows]"), { commentOf, onJump });
    this.fold = document.getElementById("collapse-row-template").content.firstElementChild.cloneNode(true);
    this.foldButton = this.fold.querySelector("[data-history-collapse]");
    this.foldButton.addEventListener("click", () => this.#toggleExpanded());
    this.detail = new HistoryDetail({
      root: root.querySelector("[data-history-detail]"),
      onBack: () => this.#back(),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.clearButton.addEventListener("click", () => this.#confirmClear());
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
      this.expanded = false;
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
      const [data, page] = await Promise.all([listExecutions(taskId, this.limit), listActivity(taskId, { limit: PAGE })]);
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
    if (type === "comment.deleted") {
      this.activity = withoutComment(this.activity, data.id); // its entry is replaced by the "deleted a comment" one
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

  /** The timeline in line with the data again (a comment changed: its preview is read live). */
  refresh() {
    if (this.taskId) this.#render();
  }

  /** The row of an item of the timeline (a live execution or an activity entry). */
  #rowOf(item) {
    return item.type === "execution" ? this.list.entries.get(item.execution.id)?.row : this.rows.get(item.key);
  }

  /** Bring the rows, the filter, the collapse, the counts and the empty state in line with the data. */
  #render() {
    const count = this.list.size;
    const finished = this.list.executions.some((execution) => execution.status !== "running");
    const items = mergeTimeline(this.list.executions, this.activity);
    this.rows.render(items.filter((item) => item.type !== "execution"));
    const filtered = filterTimeline(items, this.filter);
    const { shown, hidden } = collapse(filtered, this.expanded);
    const visible = new Set(shown.map((item) => item.key));
    for (const item of items) {
      const row = this.#rowOf(item);
      if (row) row.hidden = !visible.has(item.key);
    }
    this.#placeFold(filtered, shown, hidden);
    // the line ends at the last entry (the "Show fewer" row after it does not continue it)
    const last = [...this.list.root.children].filter((row) => !row.hidden && row !== this.fold).at(-1);
    for (const row of this.list.root.children) row.toggleAttribute("data-last", row === last);
    const more = this.next !== null || this.total > count;
    this.badge.hidden = this.taskId === null || items.length === 0;
    this.badge.textContent = this.badge.hidden ? "" : `${items.length}${more ? "+" : ""}`;
    this.badge.title = countText(items.length, "entry");
    this.summary.textContent = [this.notice, countText(items.length, "entry")].filter(Boolean).join(" ");
    this.empty.hidden = filtered.length > 0;
    this.empty.textContent = {
      all: t("history.nothing_recorded_yet"),
      runs: t("history.no_executions_yet_start_processing_this"),
      changes: t("history.no_changes_recorded_yet"),
      comments: t("history.no_comments_recorded_yet"),
    }[this.filter];
    this.more.hidden = this.total <= count;
    this.more.textContent = t("tasks.history_tab.showing_newest_count_total_executions", { count, total: this.total });
    this.clearButton.setAttribute("aria-disabled", String(!finished));
    for (const button of this.filterButtons) button.setAttribute("aria-pressed", String(button.dataset.filter === this.filter));
  }

  /** The "Show N older entries" row sits between the newest ones and the anchor ("created"), "Show fewer" at the end. */
  #placeFold(filtered, shown, hidden) {
    const folding = hidden > 0 || (this.expanded && filtered.length > COLLAPSED);
    if (!folding) {
      this.fold.remove();
      return;
    }
    this.foldButton.textContent = hidden > 0 ? plural("tasks.activity.show_older", hidden) : t("tasks.activity.show_fewer");
    this.foldButton.setAttribute("aria-expanded", String(hidden === 0));
    const anchor = hidden > 0 && shown.length > COLLAPSED ? this.#rowOf(shown.at(-1)) : null;
    if (anchor) anchor.before(this.fold);
    else this.list.root.append(this.fold);
  }

  async #toggleExpanded() {
    this.expanded = !this.expanded;
    this.#render();
    if (this.expanded) await this.#loadRest();
    this.foldButton.focus();
  }

  /** Every older page of the changes (the artifact keeps at most 500: a few requests). */
  async #loadRest() {
    const { taskId } = this;
    try {
      while (taskId === this.taskId && this.next !== null) {
        const page = await listActivity(taskId, { limit: PAGE, before: this.next });
        if (taskId !== this.taskId) return;
        const known = new Set(this.activity.map((entry) => entry.id));
        this.activity = [...this.activity, ...page.items.filter((entry) => !known.has(entry.id))];
        this.next = page.next;
      }
      this.alert.hide();
      this.#render();
    } catch (error) {
      if (taskId === this.taskId) this.alert.show(error.message || t("tasks.history_tab.history_could_not_be_loaded"), { retry: true });
    }
  }

  #setFilter(filter) {
    this.filter = filter;
    this.#render();
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
        this.announce(t("executions.page.deleted_count", { what: countText(deleted, "execution") }));
        await this.load();
      },
      onClose: () => this.clearButton.focus(),
    });
  }
}
