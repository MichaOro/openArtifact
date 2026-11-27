/* The global execution list: loads the first page for the filters in the URL, appends further pages on
 * request, and follows the event stream without moving rows under the cursor (a row that is shown is
 * updated in place; an execution that is not shown only raises the "new executions" hint). Deleting goes
 * through the artifact's own endpoint after a confirmation. The one place that writes is that delete. */
import { AlertBar } from "../components/alert-bar.js";
import { BulkBar } from "../components/bulk-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { Selection } from "../components/selection.js";
import { StopSwitch } from "../components/stop-switch.js";
import { connectEvents } from "../tasks/events.js";
import { deleteExecution } from "../tasks/history-api.js";
import { stopRun } from "../tasks/api.js";
import { plural } from "../tasks/history-format.js";
import { deleteExecutions, listAllExecutions } from "./api.js";
import { FilterBar } from "./filter-bar.js";
import { RetentionDialog } from "./retention-dialog.js";
import { Filters } from "./filters.js";
import { SummaryStrip } from "./summary.js";
import { ExecutionTable } from "./table.js";
import { t } from "../i18n.js";

const COUNTS_MS = 300;
const BATCH = 500; // the most executions one delete request takes
const root = document.querySelector("[data-executions]");
const $ = (selector) => root.querySelector(selector);

class ExecutionsPage {
  constructor() {
    this.pageSize = Number(root.dataset.pageSize) || 50;
    this.filters = Filters.fromSearch(window.location.search);
    this.cursor = null;
    this.total = 0;
    this.knownTotal = null; // executions of all artifacts, from the summary
    this.token = 0;
    this.pending = new Set(); // ids of executions that started or changed out of sight
    this.stale = false; // the event stream was lost for a while: anything may have changed
    this.deleted = new Set(); // ids deleted here: a late event must not bring them back
    this.timers = { counts: null, reload: null };

    this.alert = new AlertBar($("[data-alert]"));
    this.alert.onRetry(() => this.load());
    this.countText = $("[data-count]");
    this.live = $("[data-live]");
    this.newButton = $("[data-new]");
    this.moreButton = $("[data-more]");
    this.tableEl = $("[data-table]");
    this.list = $("[data-list]");
    this.emptyNone = $("[data-empty-none]");
    this.emptyMatch = $("[data-empty-match]");
    this.confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));

    this.everything = false; // every execution the filters match is selected, not only the ones shown
    this.busy = false;
    this.selection = new Selection(() => this.#renderBulk());
    this.selectAll = $("[data-select-all]");
    this.bulk = new BulkBar($("[data-bulk]"), "execution", {
      onClear: () => this.#clearSelection(),
      onAll: () => this.#selectEverything(),
      onDelete: () => this.#confirmBulkDelete(),
    });
    this.selectAll.addEventListener("change", () => {
      this.everything = false;
      this.selection.set(this.selectAll.checked ? this.table.selectableIds : []);
    });
    this.table = new ExecutionTable({
      body: $("[data-rows]"),
      onDelete: (execution) => this.#confirmDelete(execution),
      onStop: (execution) => this.#confirmStop(execution),
      onSelect: (id, on) => {
        this.everything = false;
        this.selection.toggle(id, on);
      },
    });
    this.summary = new SummaryStrip($(".ex-summary"), (filters) => this.#select(filters));
    this.bar = new FilterBar($("[data-filters]"), (filters) => this.#select(filters, { fromBar: true }));

    this.retention = new RetentionDialog(new Modal(document.getElementById("retention-modal")), {
      onSaved: (deleted) => {
        this.#announce(deleted ? t("executions.page.deleted_by_rules", { what: plural(deleted, "execution") }) : t("executions.page.rules_saved"));
        this.load();
      },
    });
    $("[data-retention]").addEventListener("click", () => this.retention.open());
    // STOP (ADR-076): the switch next to Retention; switching on ended the runs, so the list is read again
    this.stop = new StopSwitch($("[data-stop-switch]"), this.confirm, {
      onChanged: () => this.load(),
      onError: (message) => this.alert.show(message),
    });
    this.newButton.addEventListener("click", () => this.load({ focusFirst: true }));
    this.moreButton.addEventListener("click", () => this.#more());
    window.addEventListener("popstate", () => this.#apply(Filters.fromSearch(window.location.search)));
  }

  start() {
    this.#show(this.filters);
    return this.load();
  }

  // ── filters ─────────────────────────────────────────────────────────

  /** The user chose filters: they go into the URL (Back returns to the previous ones) and the list is reloaded. */
  #select(filters, { fromBar = false } = {}) {
    if (filters.toSearch() === this.filters.toSearch()) return;
    window.history.pushState(null, "", `${window.location.pathname}${filters.toSearch()}`);
    this.#apply(filters, { fromBar });
  }

  #apply(filters, { fromBar = false } = {}) {
    this.filters = filters;
    this.#show(filters, { fromBar });
    this.load();
  }

  #show(filters, { fromBar = false } = {}) {
    if (!fromBar) this.bar.setFilters(filters);
    this.summary.setFilters(filters);
  }

  // ── loading ─────────────────────────────────────────────────────────

  /** The first page for the current filters; a failed request keeps what is shown. Also "Reload" and Retry. */
  async load({ focusFirst = false } = {}) {
    window.clearTimeout(this.timers.reload);
    const token = ++this.token;
    this.list.setAttribute("aria-busy", "true");
    try {
      const page = await listAllExecutions(this.filters.toQuery({ limit: this.pageSize }));
      if (token !== this.token) return;
      this.table.replace(page.items);
      this.#clearSelection();
      this.cursor = page.next_cursor;
      this.total = page.total;
      this.knownTotal = page.summary.total;
      this.pending.clear();
      this.stale = false;
      this.deleted.clear();
      this.summary.render(page.summary);
      this.alert.hide();
      this.#render();
      if (focusFirst && page.items.length) this.table.focus(page.items[0].id);
    } catch (error) {
      if (token !== this.token) return;
      this.alert.show(error.message || t("executions.page.executions_could_not_be_loaded"), { retry: true });
      if (this.knownTotal === null) this.countText.textContent = t("executions.page.executions_could_not_be_loaded");
    } finally {
      if (token === this.token) this.list.setAttribute("aria-busy", "false");
    }
  }

  async #more() {
    if (!this.cursor) return;
    const token = this.token;
    this.moreButton.setAttribute("aria-disabled", "true");
    try {
      const page = await listAllExecutions(this.filters.toQuery({ limit: this.pageSize, cursor: this.cursor }));
      if (token !== this.token) return;
      const rows = this.table.append(page.items.filter((item) => !this.deleted.has(item.id)));
      if (this.everything) this.selection.set(this.table.selectableIds);
      this.table.markSelected(this.selection);
      this.cursor = page.next_cursor;
      this.total = page.total;
      this.summary.render(page.summary);
      this.alert.hide();
      this.#render();
      this.#announce(t("executions.page.more_loaded", { what: plural(rows.length, "more execution") }));
      rows[0]?.querySelector("[data-open]").focus();
    } catch (error) {
      this.alert.show(error.message || t("executions.page.more_executions_could_not_be"), { retry: false });
    } finally {
      this.moreButton.removeAttribute("aria-disabled");
    }
  }

  /** Only the numbers (counters and the total), for the live updates; failures are not shown. */
  #refreshCounts() {
    window.clearTimeout(this.timers.counts);
    this.timers.counts = window.setTimeout(async () => {
      const token = this.token;
      try {
        const page = await listAllExecutions(this.filters.toQuery({ limit: 1 }));
        if (token !== this.token) return;
        this.total = page.total;
        this.knownTotal = page.summary.total;
        this.summary.render(page.summary);
        this.#render();
      } catch {
        /* the next event or a reload brings the numbers */
      }
    }, COUNTS_MS);
  }

  // ── what is shown ───────────────────────────────────────────────────

  #render() {
    const rows = this.table.size;
    this.countText.textContent = plural(this.total, "execution");
    const nothingAtAll = rows === 0 && (this.knownTotal === 0 || !this.filters.active);
    this.tableEl.hidden = rows === 0;
    this.emptyNone.hidden = !nothingAtAll;
    this.emptyMatch.hidden = rows > 0 || nothingAtAll;
    this.moreButton.hidden = !this.cursor;
    this.moreButton.textContent = t("executions.page.load_more_rows_total_shown", { rows, total: this.total });
    const hint = this.stale ? t("executions.page.list_may_have_changed_reload") : this.pending.size ? plural(this.pending.size, "new execution") : "";
    this.newButton.hidden = !hint;
    this.newButton.textContent = hint;
  }

  #announce(message) {
    this.live.textContent = "";
    window.requestAnimationFrame(() => (this.live.textContent = message));
  }

  // ── the event stream ────────────────────────────────────────────────

  /** execution.updated / execution.deleted. */
  handleEvent(type, data) {
    if (type === "execution.deleted") {
      this.pending.delete(data.id);
      if (this.table.get(data.id)) {
        this.#removeRow(this.table.get(data.id));
      }
      this.#refreshCounts();
      return;
    }
    if (type !== "execution.updated") return;
    const execution = data.execution;
    if (this.deleted.has(execution.id)) return;
    this.#refreshCounts();
    if (this.table.patch(execution)) return;
    if (!this.filters.mayInclude(execution)) return;
    if (this.table.size === 0) {
      // nothing is shown, so nothing can shift: just show it
      this.timers.reload = window.setTimeout(() => this.load(), COUNTS_MS);
      return;
    }
    const oldest = this.table.oldestStart;
    if (this.cursor && Date.parse(execution.started_at) < oldest) return; // it is on a page that is not loaded yet
    this.pending.add(execution.id);
    this.#render();
  }

  /** The stream is up again after a loss: what was missed is not replayed. */
  resync() {
    this.stale = true;
    this.#refreshCounts();
    this.#render();
  }

  // ── deleting ────────────────────────────────────────────────────────

  #confirmDelete(execution) {
    const subject = t("executions.page.execution_number_number2", { number: execution.number, number2: execution.task.number });
    let next = null;
    this.confirm.open({
      message: t("executions.page.delete_subject_cannot_be_undone"),
      subject,
      note: t("executions.page.its_steps_deleted_with"),
      onConfirm: async () => {
        try {
          await deleteExecution(execution.task.id, execution.id);
        } catch (error) {
          if (error.status !== 404) throw error; // gone already is what was wanted
        }
        next = this.#removeRow(execution);
      },
      onClose: () => this.table.focus(next), // the focus moves on to the next row, else the table
    });
  }

  // ── stopping ────────────────────────────────────────────────────────

  /** The same question as for a delete, with the stop's own words; the run of the artifact is what ends. */
  #confirmStop(execution) {
    const subject = t("executions.page.execution_number_number2", { number: execution.number, number2: execution.task.number });
    this.confirm.open({
      title: t("executions.page.stop_execution"),
      message: t("executions.page.stop_subject_it_ends_as_stopped"),
      subject,
      note: t("executions.page.steps_already_done_stay"),
      confirmLabel: t("executions.page.stop_execution"),
      onConfirm: async () => {
        try {
          await stopRun(execution.task.id);
        } catch (error) {
          if (error.status !== 409) throw error;
          this.load(); // it ended or was just being started: show what is true now
          throw new Error(t("executions.page.stop_too_late"));
        }
      },
      onClose: () => this.table.focus(execution.id),
    });
  }

  // ── several at once ─────────────────────────────────────────────────

  #clearSelection() {
    this.everything = false;
    this.selection.clear();
    this.#renderBulk();
  }

  /** "Select all N": every execution the filters match, also the ones on pages not loaded yet. */
  #selectEverything() {
    this.everything = true;
    this.selection.set(this.table.selectableIds);
    this.#renderBulk();
  }

  #renderBulk() {
    const shown = this.table.selectableIds;
    const state = this.selection.stateOf(shown);
    this.selectAll.checked = state.checked;
    this.selectAll.indeterminate = state.indeterminate;
    this.table.markSelected(this.selection);
    const offerAll = state.checked && this.total > this.table.size;
    this.bulk.render(this.selection.size, { total: this.total, offerAll, everything: this.everything, busy: this.busy });
  }

  /** The ids of everything the filters match (finished ones), page after page. */
  async #matchingIds() {
    const ids = [];
    let cursor = null;
    do {
      const page = await listAllExecutions(this.filters.toQuery({ limit: 200, cursor }));
      ids.push(...page.items.filter((item) => item.status !== "running").map((item) => item.id));
      cursor = page.next_cursor;
    } while (cursor);
    return ids;
  }

  #confirmBulkDelete() {
    const everything = this.everything;
    const count = everything ? this.total : this.selection.size;
    this.confirm.open({
      title: t("executions.page.delete_executions"),
      message: everything ? t("executions.page.delete_all_subject_match_filters") : t("executions.page.delete_subject_cannot_be_undone_2"),
      subject: everything ? plural(count, "execution") : plural(count, "selected execution"),
      note: t("executions.page.their_steps_deleted_with_them"),
      onConfirm: async () => {
        this.busy = true;
        this.#renderBulk();
        try {
          const ids = everything ? await this.#matchingIds() : [...this.selection.ids];
          let deleted = 0;
          let skipped = 0;
          for (let at = 0; at < ids.length; at += BATCH) {
            const done = await deleteExecutions(ids.slice(at, at + BATCH));
            deleted += done.deleted;
            skipped += done.skipped_running;
          }
          this.#announce(`${t("executions.page.deleted_count", { what: plural(deleted, "execution") })}${skipped ? t("executions.page.skipped_running_skipped", { skipped }) : ""}`);
          await this.load();
        } finally {
          this.busy = false;
          this.#renderBulk();
        }
      },
      onClose: () => this.table.focus(this.table.size ? [...this.table.entries.keys()][0] : null),
    });
  }

  /** Drop the row everywhere; returns the id of the row to focus next. */
  #removeRow(execution) {
    this.deleted.add(execution.id);
    const next = this.table.neighbour(execution.id);
    this.table.remove(execution.id);
    this.selection.toggle(execution.id, false);
    this.total = Math.max(0, this.total - 1);
    this.knownTotal = Math.max(0, (this.knownTotal ?? 1) - 1);
    this.#render();
    this.#announce(t("executions.page.execution_number_number2_deleted", { number: execution.number, number2: execution.task.number }));
    this.#refreshCounts();
    return next;
  }
}

const page = new ExecutionsPage();
page.start().then(() => {
  let connected = false;
  connectEvents({
    onEvent: (type, data) => page.handleEvent(type, data),
    onOpen: () => {
      if (connected) page.resync();
      connected = true;
    },
    onClosed: () => page.alert.show(t("execution.flow_page.live_updates_stopped_reload_page")),
  });
});
