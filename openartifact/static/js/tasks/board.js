/* The board: owns the task state and the DOM of the lanes (which can be added and deleted while the page is open).
 *
 * Everything that changes a task funnels through upsert()/remove(), no matter where the
 * change came from (own API response, SSE event from any tab, optimistic drag & drop).
 * Both are idempotent, so the same change arriving twice is harmless.
 * Content is always set via textContent (never innerHTML). */
import { applyMarks } from "./card-marks.js";
import { cardPreview, previewSegments } from "./body-model.js";
import { renderBody } from "./references.js";
import { AlertBar } from "../components/alert-bar.js";
import { InlineName } from "../components/inline-name.js";
import { matches } from "./board-search-model.js";
import { KEYS, readStorage, writeStorage } from "../storage.js";
import { isOpen, laneGrouped, plan as groupPlan, readOpen, rowLabel } from "./grouping-model.js";
import { t, tn } from "../i18n.js";

const LANE_NAME_MAX_LENGTH = 40;

export class Board {
  /**
   * @param {object} options
   * @param {() => Promise<object[]>} options.loadTasks
   * @param {(status: string, title: string) => Promise<unknown>} options.renameLane saves a title typed into a lane's name
   */
  constructor({ loadTasks, renameLane }) {
    this.loadTasks = loadTasks;
    this.renameLane = renameLane;
    this.element = document.querySelector(".board");
    this.template = document.getElementById("task-card-template");
    this.laneTemplate = document.getElementById("lane-template");
    this.alert = new AlertBar();
    this.liveRegion = document.querySelector("[data-live-region]");

    this.loaded = false;
    /** The mode that reorders the lanes (ADR-092): the lanes show their handles and the cards stay where they are. */
    this.reordering = false;
    /** The board search (ADR-091): the plan from board-search-model.js, or null while nothing is typed; `kept` are cards that stay shown. */
    this.filter = null;
    /** The board view (ADR-095): "classic" or "grouped". Grouped draws a card with a parent as a row in the accordion of its parent. */
    this.view = "classic";
    /** What the Grouped view makes of the cards now (grouping-model.js `plan`), or null in the classic view. */
    this.grouping = null;
    /** The accordions the user has opened (kept in the browser). */
    this.openGroups = readOpen(readStorage(KEYS.boardGroups));
    /** Called with the task of a row of an accordion that was clicked (the card is opened as if its own card had been). */
    this.onOpenRow = null;
    /** True while a load adds many cards: the board is arranged once at the end, not after each card. */
    this.batching = false;
    /** Called after a card was added, changed or removed (the search updates its line and keeps the focus sensible). */
    this.onChange = null;
    /** Called when the card that has the focus is hidden by the search (the search takes the focus so it does not fall to the page). */
    this.onFocusLost = null;
    /** @type {Set<string>} */ this.kept = new Set();
    /** @type {Map<string, object>} */ this.runs = new Map();
    /** @type {Set<string>} */ this.locked = new Set();
    /** @type {Map<string, object>} */ this.tasks = new Map();
    /** @type {Map<string, HTMLElement>} */ this.cards = new Map();
    /** @type {Map<string, {section: HTMLElement, list: HTMLElement, count: HTMLElement, name: InlineName, title: string, hue: string, style: string}>} */
    this.lanes = new Map();
    document.querySelectorAll("[data-lane]").forEach((section) => {
      this.lanes.set(section.dataset.status, this.#adopt(section));
    });

    this.alert.onRetry(() => this.load());
    this.element.addEventListener("click", (event) => this.#groupClick(event));
  }

  /** The board view: "classic" (every card in its lane) or "grouped" (a card with a parent is a row under its parent; ADR-095). */
  setView(view) {
    const next = view === "grouped" ? "grouped" : "classic";
    if (next === this.view) return;
    this.view = next;
    this.#refresh();
  }

  get grouped() {
    return this.view === "grouped";
  }

  /** Lane order as shown on screen (left to right). */
  get statuses() {
    return [...this.lanes.keys()];
  }

  laneTitle(status) {
    return this.lanes.get(status)?.title ?? status;
  }

  /** Show only the cards a search plan keeps (`null`: all). No card is built again: each one is shown or hidden. A card the user just made stays
   * shown until the query changes (`keepVisible`). Returns `{shown, total}`. */
  setFilter(plan) {
    this.filter = plan && plan.kind !== "all" ? plan : null;
    this.kept.clear();
    return this.refilter();
  }

  /** Whether a card is hidden now: by the Grouped view (it is a row under its parent), or by the search. */
  #isHidden(task) {
    if (this.grouping?.hidden.has(task.id)) return true;
    if (!this.filter || this.kept.has(task.id)) return false;
    return this.grouping ? !this.grouping.shown.has(task.id) : !matches(task, this.filter);
  }

  /** Make a card stay shown while a filter is on (the card the user has just made must not vanish). */
  keepVisible(id) {
    this.kept.add(id);
    this.#refresh();
  }

  /** Apply the filter to every card and the lane counts again. `shown` counts the cards that match the query themselves, also a card the
   * Grouped view draws as a row. */
  refilter() {
    this.#refresh();
    let shown = 0;
    for (const [id, task] of this.tasks) {
      if (!this.filter || this.kept.has(id) || matches(task, this.filter)) shown += 1;
    }
    return { shown, total: this.cards.size };
  }

  /** Arrange the board for the view and the search: which cards are drawn in their lane, the accordions, the lines under the titles and the counts. */
  #refresh() {
    if (this.batching) return;
    const all = [...this.tasks.values()];
    this.grouping = this.grouped ? groupPlan(all, this.filter ? (task) => this.kept.has(task.id) || matches(task, this.filter) : null) : null;
    for (const [id, card] of this.cards) this.#showOrHide(card, this.tasks.get(id));
    this.#renderGroups();
    this.#updateCounts();
    this.#renderRelations();
  }

  #showOrHide(card, task) {
    const focused = document.activeElement === card; // a card that is hidden loses the focus at once: say so before it is gone
    card.hidden = Boolean(task && this.#isHidden(task));
    if (focused && card.hidden) this.onFocusLost?.();
  }

  /** Number of artifacts in a lane (the ones the Grouped view draws as rows included). */
  laneCount(status) {
    return this.lanes.get(status)?.list.children.length ?? 0;
  }

  /** Start renaming a lane in place (as clicking its name does). */
  editLaneName(status) {
    this.lanes.get(status)?.name.edit();
  }

  /**
   * Show the lanes the server sent ([{status, key, title, hue, style}], in board order): lanes that are
   * new get a section built from the server's own template, lanes that are gone disappear, titles,
   * labels and colours are updated. No reload.
   */
  setLanes(lanes) {
    const shown = new Map();
    for (const info of lanes) {
      const lane = this.lanes.get(info.status) ?? this.#adopt(this.laneTemplate.content.firstElementChild.cloneNode(true));
      if (!lane.section.isConnected) this.element.append(lane.section);
      this.#applyLane(lane, info);
      shown.set(info.status, lane);
    }
    for (const [status, lane] of this.lanes) if (!shown.has(status)) lane.section.remove();
    this.lanes = shown;
    this.#arrangeLanes();
    this.#refresh(); // the rows name the lane of their card
  }

  /** The lanes stand in the order of `this.lanes` (the server's order): a lane that moved is moved in the page, the others stay. */
  #arrangeLanes() {
    let at = this.element.firstElementChild;
    for (const { section } of this.lanes.values()) {
      if (section === at) at = at.nextElementSibling;
      else this.element.insertBefore(section, at);
    }
  }

  /** The lanes' statuses as they stand in the page now, left to right (what a drag of a lane made). */
  laneOrder() {
    return [...this.element.querySelectorAll(":scope > .lane")].map((section) => section.dataset.status);
  }

  /** The reorder mode on or off: the board makes room for the handles above its lanes (CSS) and cards cannot be moved. */
  setReordering(on) {
    this.reordering = on;
    this.element.classList.toggle("board--reorder", on);
  }

  #adopt(section) {
    const nameEl = section.querySelector("[data-lane-name]");
    const lane = {
      section,
      list: section.querySelector(".lane__cards"),
      count: section.querySelector(".lane__count"),
      title: nameEl.textContent.trim(),
      hue: section.dataset.laneHue,
      style: section.classList.contains("lane--finished") ? "finished" : "normal",
    };
    lane.name = new InlineName(nameEl, {
      label: t("dialog.lane_name"),
      maxLength: LANE_NAME_MAX_LENGTH,
      keepOpenOnError: true,
      onCommit: (title) => this.renameLane(section.dataset.status, title),
    });
    return lane;
  }

  #applyLane(lane, { status, key, title, hue, style }) {
    const { section } = lane;
    Object.assign(lane, { title, hue: String(hue), style });
    section.classList.toggle("lane--finished", style === "finished");
    Object.assign(section.dataset, { lane: key, status, laneHue: String(hue) });
    section.setAttribute("aria-labelledby", `lane-${key}-title`);
    section.querySelector(".lane__title").id = `lane-${key}-title`;
    lane.name.setText(title);
    lane.name.element.title = title;
    const add = section.querySelector("[data-create-task]");
    add.dataset.status = status;
    add.dataset.laneTitle = title;
    add.setAttribute("aria-label", t("tasks.board.add_artifact_title", { title }));
    section.querySelector("[data-lane-grip]")?.setAttribute("aria-label", t("lane.move_title", { title }));
    section.querySelector("[data-lane-menu]").setAttribute("aria-label", t("tasks.board.options_lane_title", { title }));
    lane.list.setAttribute("aria-label", t("tasks.board.lane_artifacts", { title }));
  }

  /** The lanes as choices for a rule: `{status, title}` in board order. */
  laneChoices() {
    return this.statuses.map((status) => ({ status, title: this.laneTitle(status) }));
  }

  /** How a lane draws its cards: "normal" or "finished". */
  laneStyle(status) {
    return this.lanes.get(status)?.style ?? "normal";
  }

  /** Palette index of a lane (drives its colour via data-lane-hue). */
  laneHue(status) {
    return this.lanes.get(status)?.hue ?? "1";
  }

  /** Reconcile with the server: add/update everything listed, drop everything else. */
  async load() {
    try {
      const tasks = await this.loadTasks();
      const seen = new Set(tasks.map((t) => t.id));
      this.batching = true;
      try {
        [...this.tasks.keys()].filter((id) => !seen.has(id)).forEach((id) => this.remove(id));
        tasks.forEach((task) => this.upsert(task));
      } finally {
        this.batching = false;
      }
      this.#refresh();
      this.onChange?.();
      this.loaded = true;
      this.#clearError();
    } catch (error) {
      this.showError(error.message || t("tasks.board.artifacts_could_not_be_loaded"), { retry: true });
    }
  }

  /** Create the card, or update it (and move it between lanes) if it exists. */
  upsert(task) {
    const previous = this.tasks.get(task.id);
    this.tasks.set(task.id, task);

    let card = this.cards.get(task.id);
    const isNew = !card;
    if (!card) {
      card = this.#createCard(task);
      this.cards.set(task.id, card);
    }
    this.#renderContent(card, task);

    const moved = isNew || previous.status !== task.status || previous.position !== task.position;
    // A card that is being dragged is positioned by the drag, not by incoming data.
    if (moved && !card.classList.contains("task-card--placeholder")) {
      this.#place(card, task);
      if (isNew && this.loaded) card.classList.add("task-card--new");
    }
    this.#refresh();
    if (!this.batching) this.onChange?.();
    return card;
  }

  remove(id) {
    this.cards.get(id)?.remove();
    this.cards.delete(id);
    this.tasks.delete(id);
    this.kept.delete(id);
    this.#refresh();
    if (!this.batching) this.onChange?.();
  }

  /** The parent as the dialogs and the card name it: "#15 Title" (null: none). */
  parentLabel(task) {
    const parent = this.parentOf(task);
    return parent ? rowLabel(parent) : null;
  }

  /** Parent task data of a task, or null. */
  parentOf(task) {
    return task?.parent_id ? (this.tasks.get(task.parent_id) ?? null) : null;
  }

  byNumber(number) {
    for (const t of this.tasks.values()) if (t.number === number) return t;
    return undefined;
  }

  childCount(id) {
    let n = 0;
    for (const t of this.tasks.values()) if (t.parent_id === id) n += 1;
    return n;
  }

  /** The task itself and everything below it (a task must not become a child of these). */
  descendantIds(id) {
    const found = new Set();
    const queue = [id];
    while (queue.length) {
      const current = queue.pop();
      for (const t of this.tasks.values()) {
        if (t.parent_id === current && !found.has(t.id)) {
          found.add(t.id);
          queue.push(t.id);
        }
      }
    }
    return found;
  }

  /** All tasks in the order they appear on screen (lane by lane, top to bottom). */
  inBoardOrder() {
    return this.statuses.flatMap((status) =>
      [...this.lanes.get(status).list.children].map((card) => this.taskOf(card)).filter(Boolean),
    );
  }

  /** Sort key for a task dropped between two neighbours (either may be null). */
  static positionBetween(prev, next) {
    if (prev && next) return (prev.position + next.position) / 2;
    if (next) return next.position - 1;
    if (prev) return prev.position + 1;
    return 0;
  }

  /** Sort key for a card that sits at its desired spot in the DOM. */
  positionAround(card) {
    return Board.positionBetween(this.taskOf(card.previousElementSibling), this.taskOf(card.nextElementSibling));
  }

  /** Sort key that puts a task at the top of a lane. */
  topPosition(status) {
    const first = this.taskOf(this.lanes.get(status)?.list.firstElementChild);
    return first ? first.position - 1 : 0;
  }

  /** Task data for a card element (or null). */
  taskOf(card) {
    return this.tasks.get(card?.dataset.taskId) ?? null;
  }

  /** Screen-reader announcement (moves, deletions). */
  announce(message) {
    if (!this.liveRegion) return;
    this.liveRegion.textContent = "";
    // A changed text node is what triggers the announcement. (setTimeout, not
    // requestAnimationFrame: frames are paused in background tabs.)
    window.setTimeout(() => (this.liveRegion.textContent = message), 50);
  }

  /**
   * @param {string} message
   * @param {{retry?: boolean, sticky?: boolean}} options retry: offer the "Retry" button (load errors);
   *   sticky: keep it (the others disappear by themselves)
   */
  showError(message, { retry = false, sticky = false } = {}) {
    this.alert.show(message, { retry, autoHide: retry || sticky ? 0 : 6000 });
  }

  #clearError() {
    this.alert.hide();
  }

  #createCard(task) {
    const card = this.template.content.firstElementChild.cloneNode(true);
    card.dataset.taskId = task.id;
    return card;
  }

  /** Show the state of the artifact's run on its card (null: none). */
  setRun(taskId, run) {
    if (run) this.runs.set(taskId, run);
    else this.runs.delete(taskId);
    const card = this.cards.get(taskId);
    if (card) this.#renderRun(card, taskId);
    this.#renderGroupOf(taskId); // the row of a card drawn under its parent shows the run
  }

  /** A card that is being processed cannot be moved or deleted by the user. */
  setLocked(taskId, locked) {
    if (locked) this.locked.add(taskId);
    else this.locked.delete(taskId);
    const card = this.cards.get(taskId);
    if (card) this.#renderRun(card, taskId);
    this.#renderGroupOf(taskId);
  }

  #renderRun(card, taskId) {
    const run = this.runs.get(taskId);
    const line = card.querySelector(".task-card__run");
    line.textContent = run ? `${run.stage_name ?? run.pipeline_name} · ${run.status}` : "";
    line.hidden = !run;
    line.dataset.status = run?.status ?? "";
    const locked = this.locked.has(taskId);
    card.classList.toggle("task-card--locked", locked);
    card.querySelector("[data-delete-task]").disabled = locked;
  }

  #renderContent(card, task) {
    this.#renderRun(card, task.id);
    card.querySelector(".task-card__title").textContent = task.title;
    applyMarks(card, task.marks);
    const body = card.querySelector(".task-card__body");

    const segments = previewSegments(task); // marked while the personal setting says so
    body.replaceChildren(renderBody(cardPreview(task), this.findByNumber, { segments, plain: true, links: Boolean(segments) })); // the first words as plain lines: bold, italic, strikethrough and code stay, block marks (#, >, bullets, fences, table pipes) and links are not drawn (ADR-077)
    body.hidden = !body.textContent;

    card.querySelector("[data-delete-task]").setAttribute("aria-label", t("tasks.board.delete_artifact_title", { title: task.title }));
  }

  /** Insert into the lane keeping the server's order: position, then newest first, then id. */
  #place(card, task) {
    const list = this.lanes.get(task.status)?.list;
    if (!list) return;
    const before = [...list.children].find((other) => {
      const o = this.tasks.get(other.dataset.taskId);
      return o && o.id !== task.id && this.#compare(task, o) < 0;
    });
    list.insertBefore(card, before ?? null);
  }

  #compare(a, b) {
    if (a.position !== b.position) return a.position < b.position ? -1 : 1;
    if (a.created_at !== b.created_at) return a.created_at > b.created_at ? -1 : 1;
    return a.id < b.id ? -1 : 1;
  }

  /** Show "Parent: #15 …" and, in the classic view, the number of children on the cards (they depend on other tasks). In the grouped view the
   * accordion says how many children a card has. */
  #renderRelations() {
    const children = new Map();
    for (const t of this.tasks.values()) {
      if (t.parent_id) children.set(t.parent_id, (children.get(t.parent_id) ?? 0) + 1);
    }
    for (const [id, card] of this.cards) {
      const task = this.tasks.get(id);
      const parent = this.parentOf(task);
      const n = children.get(id) ?? 0;
      const parts = [];
      if (parent) parts.push(t("tasks.board.parent_title", { title: rowLabel(parent) }));
      if (n && !this.grouped) parts.push(`${n} sub-artifact${n === 1 ? "" : "s"}`);
      const meta = card.querySelector(".task-card__meta");
      meta.textContent = parts.join(" · ");
      meta.hidden = parts.length === 0;
    }
  }

  /** The accordion of every card that has children (the grouped view) or none (the classic view). */
  #renderGroups() {
    for (const [id, card] of this.cards) this.#renderGroup(card, id);
  }

  /** The accordion of the parent of a card (its row changed). */
  #renderGroupOf(taskId) {
    const parentId = this.tasks.get(taskId)?.parent_id;
    const card = parentId && this.cards.get(parentId);
    if (card) this.#renderGroup(card, parentId);
  }

  #renderGroup(card, id) {
    const group = card.querySelector("[data-group]");
    if (!group) return;
    const children = this.grouping?.children.get(id) ?? [];
    group.hidden = children.length === 0;
    if (!children.length) return;
    const rows = this.grouping.rows.get(id) ?? [];
    const open = isOpen(this.openGroups, id, Boolean(this.filter), rows.length);
    const toggle = group.querySelector("[data-group-toggle]");
    const list = group.querySelector("[data-group-list]");
    toggle.setAttribute("aria-expanded", String(open));
    const label = t("tasks.board.group_toggle", { count: children.length });
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
    group.querySelector("[data-group-count]").textContent = this.filter ? `${rows.length}/${children.length}` : String(children.length);
    list.hidden = !open;
    if (!open) {
      list.replaceChildren();
      return;
    }
    const focused = document.activeElement?.closest?.("[data-group-row]")?.dataset.groupRow; // a row that is drawn again keeps the focus
    list.replaceChildren(...rows.map((child) => this.#groupRow(child)));
    if (focused) list.querySelector(`[data-group-row="${CSS.escape(focused)}"]`)?.focus();
  }

  /** One row of an accordion: the number and title on one line (cut with "…"), the lane of the card and the state of its run. */
  #groupRow(task) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "group-row";
    button.dataset.groupRow = task.id;
    const title = document.createElement("span");
    title.className = "group-row__title";
    title.textContent = rowLabel(task);
    title.title = rowLabel(task);
    const lane = document.createElement("span");
    lane.className = "group-row__lane";
    lane.dataset.laneHue = this.laneHue(task.status);
    lane.textContent = this.laneTitle(task.status);
    button.append(title, lane);
    const run = this.runs.get(task.id);
    if (run) {
      const state = document.createElement("span");
      state.className = "group-row__run";
      state.dataset.status = run.status;
      state.textContent = run.status;
      state.title = `${run.stage_name ?? run.pipeline_name} · ${run.status}`;
      button.append(state);
    }
    item.append(button);
    return item;
  }

  /** A click on the toggle of an accordion or on one of its rows (not on the card around them). */
  #groupClick(event) {
    const toggle = event.target.closest("[data-group-toggle]");
    const row = event.target.closest("[data-group-row]");
    if (!toggle && !row) return;
    event.stopImmediatePropagation(); // the card around it would open as well
    if (row) {
      const task = this.tasks.get(row.dataset.groupRow);
      if (task) this.onOpenRow?.(task);
      return;
    }
    const id = toggle.closest(".task-card")?.dataset.taskId;
    if (!id) return;
    if (this.openGroups.has(id)) this.openGroups.delete(id);
    else this.openGroups.add(id);
    writeStorage(KEYS.boardGroups, JSON.stringify([...this.openGroups]));
    this.#renderGroup(this.cards.get(id), id);
  }

  #updateCounts() {
    const inAccordions = (status) => (this.grouping ? laneGrouped([...this.tasks.values()], this.grouping.hidden, status) : 0);
    this.lanes.forEach(({ section, list, count }, status) => {
      const total = [...list.children].filter((card) => !this.grouping?.hidden.has(card.dataset.taskId)).length; // the cards the lane draws
      const grouped = inAccordions(status);
      const note = grouped ? t("board.grouped.lane_count", { count: grouped }) : "";
      if (!this.filter) {
        count.textContent = String(total);
        count.setAttribute("aria-label", [tn("count.artifact", total), note].filter(Boolean).join(", "));
        if (note) count.title = note;
        else count.removeAttribute("title");
        section.querySelector("[data-lane-nomatch]")?.setAttribute("hidden", "");
        section.classList.remove("lane--nomatch");
        return;
      }
      const shown = [...list.children].filter((card) => !card.hidden).length; // while a search is on the badge says how many of the lane match
      count.textContent = `${shown}/${total}`;
      const text = [t("board.search.lane_count", { shown, total }), note].filter(Boolean).join(", ");
      count.setAttribute("aria-label", text);
      count.title = text;
      const none = section.querySelector("[data-lane-nomatch]");
      const empty = total > 0 && shown === 0;
      if (none) none.hidden = !empty;
      section.classList.toggle("lane--nomatch", empty);
    });
  }
}
