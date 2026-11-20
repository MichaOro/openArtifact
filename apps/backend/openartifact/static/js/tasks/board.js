/* Renders tasks into the Kanban lanes and keeps the lane counters in sync.
 * Content is always set via textContent (never innerHTML). */

export class Board {
  /**
   * @param {object} options
   * @param {() => Promise<object[]>} options.loadTasks
   */
  constructor({ loadTasks }) {
    this.loadTasks = loadTasks;
    this.template = document.getElementById("task-card-template");
    this.errorBox = document.querySelector("[data-board-error]");
    this.errorText = document.querySelector("[data-board-error-text]");
    this.lanes = new Map();
    document.querySelectorAll("[data-lane]").forEach((section) => {
      this.lanes.set(section.dataset.status, {
        list: section.querySelector(".lane__cards"),
        count: section.querySelector(".lane__count"),
      });
    });

    document.querySelector("[data-board-retry]")?.addEventListener("click", () => this.load());
  }

  async load() {
    try {
      const tasks = await this.loadTasks();
      this.#setError("");
      this.lanes.forEach(({ list }) => list.replaceChildren());
      // The API returns newest first, so appending keeps that order.
      tasks.forEach((task) => this.#cardList(task)?.append(this.#createCard(task)));
      this.#updateCounts();
    } catch (error) {
      this.#setError(error.message || "Tasks could not be loaded.");
    }
  }

  /** Show a freshly created task at the top of its lane. */
  add(task) {
    const card = this.#createCard(task);
    card.classList.add("task-card--new");
    this.#cardList(task)?.prepend(card);
    this.#updateCounts();
  }

  #cardList(task) {
    return this.lanes.get(task.status)?.list;
  }

  #createCard(task) {
    const card = this.template.content.firstElementChild.cloneNode(true);
    card.dataset.taskId = task.id;
    card.querySelector(".task-card__title").textContent = task.title;
    const body = card.querySelector(".task-card__body");
    body.textContent = task.body ?? "";
    body.hidden = !task.body;
    return card;
  }

  #updateCounts() {
    this.lanes.forEach(({ list, count }) => {
      const n = list.children.length;
      count.textContent = String(n);
      count.setAttribute("aria-label", `${n} ${n === 1 ? "task" : "tasks"}`);
    });
  }

  #setError(message) {
    this.errorText.textContent = message;
    this.errorBox.hidden = !message;
  }
}
