/* The board: owns the task state and the DOM of the lanes (which can be added and deleted while the page is open).
 *
 * Everything that changes a task funnels through upsert()/remove(), no matter where the
 * change came from (own API response, SSE event from any tab, optimistic drag & drop).
 * Both are idempotent, so the same change arriving twice is harmless.
 * Content is always set via textContent (never innerHTML). */
import { AlertBar } from "../components/alert-bar.js";
import { InlineName } from "../components/inline-name.js";
import { t } from "../i18n.js";

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
  }

  /** Lane order as shown on screen (left to right). */
  get statuses() {
    return [...this.lanes.keys()];
  }

  laneTitle(status) {
    return this.lanes.get(status)?.title ?? status;
  }

  /** Number of artifacts in a lane as shown. */
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
    this.#updateCounts();
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
    section.querySelector("[data-lane-menu]").setAttribute("aria-label", t("tasks.board.options_lane_title", { title }));
    lane.list.setAttribute("aria-label", `${title} artifacts`);
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
      [...this.tasks.keys()].filter((id) => !seen.has(id)).forEach((id) => this.remove(id));
      tasks.forEach((task) => this.upsert(task));
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
    this.#updateCounts();
    this.#renderRelations();
    return card;
  }

  remove(id) {
    this.cards.get(id)?.remove();
    this.cards.delete(id);
    this.tasks.delete(id);
    this.#updateCounts();
    this.#renderRelations();
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
  }

  /** A card that is being processed cannot be moved or deleted by the user. */
  setLocked(taskId, locked) {
    if (locked) this.locked.add(taskId);
    else this.locked.delete(taskId);
    const card = this.cards.get(taskId);
    if (card) this.#renderRun(card, taskId);
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
    const body = card.querySelector(".task-card__body");
    body.textContent = task.body ?? "";
    body.hidden = !task.body;
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

  /** Show "Parent: …" and the number of children on the cards (they depend on other tasks). */
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
      if (parent) parts.push(t("tasks.board.parent_title", { title: parent.title }));
      if (n) parts.push(`${n} sub-artifact${n === 1 ? "" : "s"}`);
      const meta = card.querySelector(".task-card__meta");
      meta.textContent = parts.join(" · ");
      meta.hidden = parts.length === 0;
    }
  }

  #updateCounts() {
    this.lanes.forEach(({ list, count }) => {
      const n = list.children.length;
      count.textContent = String(n);
      count.setAttribute("aria-label", `${n} ${n === 1 ? "artifact" : "artifacts"}`);
    });
  }
}
