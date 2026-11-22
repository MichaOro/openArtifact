/* The global execution list: loads the first page for the filters in the URL, appends further pages on
 * request, and follows the event stream without moving rows under the cursor (a row that is shown is
 * updated in place; an execution that is not shown only raises the "new executions" hint). Deleting goes
 * through the artifact's own endpoint after a confirmation. The one place that writes is that delete. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { deleteExecution } from "../tasks/history-api.js";
import { plural } from "../tasks/history-format.js";
import { listAllExecutions } from "./api.js";
import { FilterBar } from "./filter-bar.js";
import { Filters } from "./filters.js";
import { SummaryStrip } from "./summary.js";
import { ExecutionTable } from "./table.js";

const COUNTS_MS = 300;
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

    this.table = new ExecutionTable({ body: $("[data-rows]"), onDelete: (execution) => this.#confirmDelete(execution) });
    this.summary = new SummaryStrip($(".ex-summary"), (filters) => this.#select(filters));
    this.bar = new FilterBar($("[data-filters]"), (filters) => this.#select(filters, { fromBar: true }));

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
      this.alert.show(error.message || "Executions could not be loaded.", { retry: true });
      if (this.knownTotal === null) this.countText.textContent = "Executions could not be loaded.";
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
      this.cursor = page.next_cursor;
      this.total = page.total;
      this.summary.render(page.summary);
      this.alert.hide();
      this.#render();
      this.#announce(`${plural(rows.length, "more execution")} loaded`);
      rows[0]?.querySelector("[data-open]").focus();
    } catch (error) {
      this.alert.show(error.message || "More executions could not be loaded.", { retry: false });
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
    this.moreButton.textContent = `Load more (${rows} of ${this.total} shown)`;
    const hint = this.stale ? "The list may have changed. Reload it" : this.pending.size ? plural(this.pending.size, "new execution") : "";
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
    const subject = `execution #${execution.number} of #${execution.task.number}`;
    let next = null;
    this.confirm.open({
      message: "Delete {subject}? This cannot be undone.",
      subject,
      note: "Its steps are deleted with it.",
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

  /** Drop the row everywhere; returns the id of the row to focus next. */
  #removeRow(execution) {
    this.deleted.add(execution.id);
    const next = this.table.neighbour(execution.id);
    this.table.remove(execution.id);
    this.total = Math.max(0, this.total - 1);
    this.knownTotal = Math.max(0, (this.knownTotal ?? 1) - 1);
    this.#render();
    this.#announce(`Execution #${execution.number} of #${execution.task.number} deleted`);
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
    onClosed: () => page.alert.show("Live updates stopped. Reload the page or sign in again."),
  });
});
