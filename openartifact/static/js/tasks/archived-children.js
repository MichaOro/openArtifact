/* The archived children of a card (ADR-095 add.1): a window with a row for each archived card that has the card as its parent, the newest
 * archived first: "#number title" on one line (cut with "…"), the lane it was archived from and the day it was archived. A click on a row
 * hands the card to the page, which shows the archive and opens the card there. The window keeps itself current while it is open (a card
 * archived or taken out of the archive changes the list). */
import { t } from "../i18n.js";
import { formatDay } from "./history-format.js";
import { rowLabel } from "./grouping-model.js";
import { listArchivedChildren } from "./api.js";

export class ArchivedChildren {
  /**
   * @param {object} options
   * @param {import("../components/modal.js").Modal} options.modal
   * @param {(task: object, parent: object) => void} options.onPick a row was clicked: the archived card and the card that was asked about
   */
  constructor({ modal, onPick }) {
    this.modal = modal;
    this.onPick = onPick;
    this.parent = null;
    this.refresh = 0;
    this.token = 0;
    const root = modal.dialog;
    this.title = root.querySelector(".modal__title");
    this.list = root.querySelector("[data-archived-list]");
    this.empty = root.querySelector("[data-archived-empty]");
    this.error = root.querySelector("[data-archived-error]");
    this.list.addEventListener("click", (event) => {
      const row = event.target.closest("[data-archived-id]");
      const task = row && this.tasks.get(row.dataset.archivedId);
      if (task && this.parent) this.onPick(task, this.parent);
    });
    root.addEventListener("close", () => {
      this.parent = null;
      clearTimeout(this.refresh);
    });
    /** @type {Map<string, object>} */ this.tasks = new Map();
  }

  /** Open the window for the archived children of a card. */
  async open(parent) {
    this.parent = parent;
    this.title.textContent = t("archived_children.title", { label: rowLabel(parent) });
    this.list.replaceChildren();
    this.empty.hidden = true;
    this.error.hidden = true;
    if (!this.modal.isOpen) this.modal.open();
    await this.load();
  }

  get isOpen() {
    return this.modal.isOpen && this.parent !== null;
  }

  close() {
    if (this.modal.isOpen) this.modal.close();
  }

  async load() {
    const parent = this.parent;
    if (!parent) return;
    const token = ++this.token;
    try {
      const tasks = await listArchivedChildren(parent.id);
      if (token !== this.token || this.parent?.id !== parent.id) return; // a newer answer or another card
      this.tasks = new Map(tasks.map((task) => [task.id, task]));
      this.error.hidden = true;
      this.list.replaceChildren(...tasks.map((task) => this.#row(task)));
      this.empty.hidden = tasks.length > 0;
    } catch {
      if (token === this.token) this.error.hidden = false;
    }
  }

  /** A card was archived, restored or deleted somewhere: the list is read again (once for a burst of events). */
  handleEvent(type) {
    if (!this.isOpen || !["board.updated", "board.resync", "task.updated", "task.deleted"].includes(type)) return;
    clearTimeout(this.refresh);
    this.refresh = setTimeout(() => this.load(), 200);
  }

  #row(task) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "group-row archived-children__row";
    button.dataset.archivedId = task.id;
    const title = document.createElement("span");
    title.className = "group-row__title";
    title.textContent = rowLabel(task);
    title.title = rowLabel(task);
    const lane = document.createElement("span");
    lane.className = "group-row__lane";
    lane.textContent = task.archived_from_lane ?? t("archived_children.lane_unknown");
    const when = document.createElement("span");
    when.className = "group-row__run archived-children__day";
    when.textContent = task.archived_at ? formatDay(task.archived_at) : "";
    button.append(title, lane, when);
    item.append(button);
    return item;
  }
}
