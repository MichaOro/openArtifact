/* Form logic for the "Create Task" modal. No markup knowledge beyond the
 * data-/id hooks below; rendering of the created card is delegated via onCreated. */

export class CreateTaskForm {
  /**
   * @param {object} options
   * @param {import("../components/modal.js").Modal} options.modal
   * @param {(task: {title: string, body: string, status: string}) => Promise<object>} options.createTask
   * @param {(task: object) => void} options.onCreated
   */
  constructor({ modal, createTask, onCreated }) {
    this.modal = modal;
    this.createTask = createTask;
    this.onCreated = onCreated;
    this.busy = false;
    this.status = "backlog";

    const root = modal.dialog;
    this.form = root.querySelector("form");
    this.titleInput = this.form.elements.namedItem("title");
    this.bodyInput = this.form.elements.namedItem("body");
    this.titleError = root.querySelector("#task-title-error");
    this.formError = root.querySelector("[data-form-error]");
    this.subtitle = root.querySelector("[data-modal-subtitle]");
    this.submitButton = root.querySelector("[data-submit]");
    this.cancelButton = root.querySelector("[data-cancel]");

    // Closing (X, Cancel, Escape, overlay) is blocked while a request is running.
    modal.canClose = () => !this.busy;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.titleInput.addEventListener("input", () => this.#setTitleError(""));
  }

  /** Open for a lane. The draft is kept if the user dismissed the modal earlier. */
  open(status, laneTitle) {
    this.status = status;
    this.subtitle.textContent = `Adding to ${laneTitle}`;
    this.#setTitleError("");
    this.#setFormError("");
    this.modal.open();
  }

  async submit() {
    if (this.busy) return; // no double creation

    const title = this.titleInput.value.trim();
    if (!title) {
      this.#setTitleError("Please enter a title.");
      this.titleInput.focus();
      return;
    }

    this.#setFormError("");
    this.#setBusy(true);
    try {
      const task = await this.createTask({
        title,
        body: this.bodyInput.value,
        status: this.status,
      });
      this.form.reset();
      this.#setBusy(false);
      this.modal.close();
      this.onCreated(task);
    } catch (error) {
      this.#setBusy(false);
      this.#showError(error);
    }
  }

  #showError(error) {
    const fieldMessage = error.fieldErrors?.title;
    if (fieldMessage) {
      this.#setTitleError(fieldMessage);
      this.titleInput.focus();
    } else {
      this.#setFormError(error.message || "The task could not be saved. Please try again.");
    }
  }

  #setBusy(busy) {
    this.busy = busy;
    // aria-disabled (not `disabled`) so the focused button keeps focus inside the dialog;
    // submit() and Modal.canClose already ignore input while busy.
    this.submitButton.setAttribute("aria-disabled", String(busy));
    this.submitButton.setAttribute("aria-busy", String(busy));
    this.cancelButton.setAttribute("aria-disabled", String(busy));
    this.form.setAttribute("aria-busy", String(busy));
  }

  #setTitleError(message) {
    this.titleError.textContent = message;
    this.titleError.hidden = !message;
    this.titleInput.setAttribute("aria-invalid", String(Boolean(message)));
  }

  #setFormError(message) {
    this.formError.textContent = message;
    this.formError.hidden = !message;
  }
}
