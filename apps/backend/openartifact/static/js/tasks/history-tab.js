/* The History tab of the artifact dialog: the executions of the shown artifact. Orchestrates the
 * list (HistoryList), one execution (HistoryDetail) and the retention editor (RetentionEditor); owns
 * what they share: the loaded data, the live events and the confirmation of deletes.
 *
 * The tab follows the artifact the dialog shows (show / hide) and is kept current by the page's one
 * event stream: execution.updated and execution.deleted reach it through handleEvent(). */
import { AlertBar } from "../components/alert-bar.js";
import { clearExecutions, deleteExecution, getExecution, listExecutions, saveHistoryPolicy } from "./history-api.js";
import { HistoryDetail } from "./history-detail.js";
import { plural } from "./history-format.js";
import { HistoryList } from "./history-list.js";
import { RetentionEditor } from "./retention-editor.js";

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

    this.alert = new AlertBar(root.querySelector("[data-history-alert]"));
    this.alert.onRetry(() => this.#retry());
    this.live = root.querySelector("[data-history-live]");
    this.listView = root.querySelector("[data-history-list-view]");
    this.summary = root.querySelector("[data-history-summary]");
    this.empty = root.querySelector("[data-history-empty]");
    this.more = root.querySelector("[data-history-more]");
    this.clearButton = root.querySelector("[data-history-clear]");
    this.list = new HistoryList({
      root: root.querySelector("[data-history-rows]"),
      onOpen: (execution) => this.#open(execution),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.detail = new HistoryDetail({
      root: root.querySelector("[data-history-detail]"),
      onBack: () => this.#back(),
      onDelete: (execution) => this.#confirmDelete(execution),
    });
    this.editor = new RetentionEditor({
      root: root.querySelector("[data-policy]"),
      save: (values) => saveHistoryPolicy(this.taskId, values),
      onSaved: () => this.load(),
    });
    this.clearButton.addEventListener("click", () => this.#confirmClear());
  }

  /** The dialog shows this artifact: start from its list (a reopened one keeps what it had until the fresh data arrives). */
  show(task) {
    const same = task.id === this.taskId;
    this.taskId = task.id;
    this.#showList();
    if (!same) {
      this.list.render([]);
      this.editor.reset();
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
      const data = await listExecutions(taskId, this.limit);
      if (token !== this.token) return;
      this.list.render(data.items);
      this.total = data.total;
      this.editor.setPolicy(data.policy);
      this.alert.hide();
      this.#render();
      if (this.#detailShown()) this.#refetchDetail();
    } catch (error) {
      if (token === this.token) this.alert.show(error.message || "The history could not be loaded.", { retry: true });
    }
  }

  /** execution.updated / execution.deleted of the event stream. */
  handleEvent(type, data) {
    if (!this.taskId || data.task_id !== this.taskId) return;
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

  #render() {
    const count = this.list.size;
    const finished = this.list.executions.some((execution) => execution.status !== "running");
    this.badge.hidden = this.taskId === null || this.total === 0;
    this.badge.textContent = this.badge.hidden ? "" : String(this.total);
    this.badge.title = `${plural(this.total, "execution")}`;
    this.summary.textContent = [this.notice, plural(this.total, "execution")].filter(Boolean).join(" ");
    this.empty.hidden = count > 0;
    this.more.hidden = this.total <= count;
    this.more.textContent = `Showing the newest ${count} of ${this.total} executions.`;
    this.clearButton.setAttribute("aria-disabled", String(!finished));
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
        else this.alert.show(error.message || "The execution could not be loaded.", { retry: true });
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
    this.notice = `Execution #${execution.number} was deleted.`;
    this.#render();
    this.announce(this.notice);
    this.list.focus(null);
  }

  // ── deleting ────────────────────────────────────────────────────────

  #confirmDelete(execution) {
    let next = null;
    this.confirm.open({
      message: "Delete {subject}? This cannot be undone.",
      subject: `execution #${execution.number}`,
      note: "Its steps are deleted with it.",
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
    this.announce(`Execution #${execution.number} deleted`);
    return next;
  }

  #confirmClear() {
    if (this.clearButton.getAttribute("aria-disabled") === "true") return;
    this.confirm.open({
      message: "Delete all finished executions of this artifact?",
      note: "A running execution is not deleted.",
      confirmLabel: "Delete all",
      onConfirm: async () => {
        const { deleted } = await clearExecutions(this.taskId);
        this.announce(`${plural(deleted, "execution")} deleted`);
        await this.load();
      },
      onClose: () => this.clearButton.focus(),
    });
  }
}
