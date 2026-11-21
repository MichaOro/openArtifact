/* Confirmation dialog for deleting a task. Same busy/guard rules as the create form. */

export class DeleteTaskDialog {
  /**
   * @param {object} options
   * @param {import("../components/modal.js").Modal} options.modal
   * @param {(id: string) => Promise<unknown>} options.deleteTask
   * @param {(task: object) => void} options.onDeleted
   */
  constructor({ modal, deleteTask, onDeleted }) {
    this.modal = modal;
    this.deleteTask = deleteTask;
    this.onDeleted = onDeleted;
    this.busy = false;
    this.task = null;

    const root = modal.dialog;
    this.titleEl = root.querySelector("[data-task-title]");
    this.errorEl = root.querySelector("[data-form-error]");
    this.childrenNote = root.querySelector("[data-children-note]");
    this.confirmButton = root.querySelector("[data-confirm]");
    this.cancelButton = root.querySelector("[data-cancel]");

    modal.canClose = () => !this.busy;
    this.confirmButton.addEventListener("click", () => this.confirm());
  }

  open(task, childCount = 0) {
    this.task = task;
    this.titleEl.textContent = task.title;
    this.childrenNote.hidden = childCount === 0;
    this.childrenNote.textContent =
      childCount === 0
        ? ""
        : `Its ${childCount} sub-artifact${childCount === 1 ? "" : "s"} will lose their parent but are not deleted.`;
    this.#setError("");
    this.modal.open();
  }

  async confirm() {
    if (this.busy || !this.task) return;
    const task = this.task;
    this.#setError("");
    this.#setBusy(true);
    try {
      await this.deleteTask(task.id);
    } catch (error) {
      // Already gone elsewhere (404) is the outcome the user wanted.
      if (error.status !== 404) {
        this.#setBusy(false);
        this.#setError(error.message || "The artifact could not be deleted. Please try again.");
        return;
      }
    }
    this.#setBusy(false);
    this.modal.close();
    this.onDeleted(task);
  }

  #setBusy(busy) {
    this.busy = busy;
    for (const button of [this.confirmButton, this.cancelButton]) {
      button.setAttribute("aria-disabled", String(busy));
    }
    this.confirmButton.setAttribute("aria-busy", String(busy));
  }

  #setError(message) {
    this.errorEl.textContent = message;
    this.errorEl.hidden = !message;
  }
}
