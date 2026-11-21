/* Form logic for the task modal: creates a task or edits an existing one.
 * No markup knowledge beyond the data-/id hooks below; what happens with the saved task is
 * delegated via onSaved, so this module never touches the board. */

export class TaskForm {
  /**
   * @param {object} options
   * @param {import("../components/modal.js").Modal} options.modal
   * @param {(task: {title: string, body: string, status: string}) => Promise<object>} options.createTask
   * @param {(id: string, fields: {title: string, body: string|null}) => Promise<object>} options.updateTask
   * @param {(task: object) => void} options.onSaved called with the created/updated task
   * @param {(task: object) => void} options.onGone called when an edited task no longer exists
   */
  constructor({ modal, createTask, updateTask, onSaved, onGone }) {
    this.modal = modal;
    this.createTask = createTask;
    this.updateTask = updateTask;
    this.onSaved = onSaved;
    this.onGone = onGone;
    this.busy = false;
    this.status = "backlog";
    /** The task being edited, or null when creating. */
    this.editing = null;
    /** Create-mode draft, parked while an edit is open. */
    this.draft = null;

    const root = modal.dialog;
    this.form = root.querySelector("form");
    this.heading = root.querySelector(".modal__title");
    this.titleInput = this.form.elements.namedItem("title");
    this.bodyInput = this.form.elements.namedItem("body");
    this.titleError = root.querySelector("#task-title-error");
    this.formError = root.querySelector("[data-form-error]");
    this.numberLabel = root.querySelector("[data-modal-number]");
    this.subtitle = root.querySelector("[data-modal-subtitle]");
    this.submitButton = root.querySelector("[data-submit]");
    this.submitLabel = root.querySelector("[data-submit-label]");
    this.cancelButton = root.querySelector("[data-cancel]");
    this.cardNav = root.querySelector("[data-card-nav]");
    this.laneField = root.querySelector('[data-card-field="lane"]');
    this.laneValue = root.querySelector("[data-lane-value]");
    this.laneTitle = "";
    this.parentField = root.querySelector('[data-card-field="parent"]');
    this.parentValue = root.querySelector("[data-parent-value]");

    // Closing (X, Cancel, Escape, overlay) is blocked while a request is running.
    modal.canClose = () => !this.busy;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.titleInput.addEventListener("input", () => this.#setTitleError(""));
  }

  /** Open in create mode for a lane. The draft is kept if the user dismissed the modal earlier. */
  open(status, laneTitle, hue) {
    this.#leaveEditMode();
    this.status = status;
    this.#present("Create Artifact", "Create Artifact");
    this.#showNumber(null);
    this.setLane(status, laneTitle, hue);
    this.modal.open();
  }

  /** Open in edit mode, prefilled with the task. */
  openEdit(task, laneTitle, hue, parentTitle = null) {
    if (!this.editing) {
      this.draft = { title: this.titleInput.value, body: this.bodyInput.value };
    }
    this.editing = task;
    this.titleInput.value = task.title;
    this.bodyInput.value = task.body ?? "";
    this.#present("Edit Artifact", "Save");
    this.#showNumber(task.number);
    this.setLane(task.status, laneTitle, hue);
    this.setParent(parentTitle);
    this.modal.open();
  }

  /** The artifact number in the header (only for saved artifacts). */
  #showNumber(number) {
    if (!this.numberLabel) return;
    this.numberLabel.hidden = number == null;
    this.numberLabel.textContent = number == null ? "" : `#${number}`;
    this.numberLabel.title = "Artifact number: reference it as #" + number;
  }

  /** Show the parent of the task being edited (null = none). */
  setParent(parentTitle) {
    if (this.parentValue) this.parentValue.textContent = parentTitle ?? "None";
    this.parentField?.setAttribute("aria-label", `Parent: ${parentTitle ?? "none"}. Change parent`);
  }

  /** Lane of the task being edited, or the target lane of a new task. */
  currentStatus() {
    return this.editing ? this.editing.status : this.status;
  }

  /** Show (and remember) the lane. Moving an existing task is the caller's job. */
  setLane(status, laneTitle, hue = "1") {
    if (this.editing) this.editing = { ...this.editing, status };
    else this.status = status;
    this.laneTitle = laneTitle;
    this.subtitle.textContent = this.editing ? `In ${laneTitle}` : `Adding to ${laneTitle}`;
    this.subtitle.setAttribute("aria-label", `Lane: ${laneTitle}. Change lane`);
    this.subtitle.dataset.laneHue = String(hue);
    if (this.laneField) this.laneField.dataset.laneHue = String(hue);
    if (this.laneValue) this.laneValue.textContent = laneTitle;
    this.laneField?.setAttribute("aria-label", `Lane: ${laneTitle}. Change lane`);
  }

  async submit() {
    if (this.busy) return; // no double submit

    const title = this.titleInput.value.trim();
    if (!title) {
      this.#setTitleError("Please enter a title.");
      this.titleInput.focus();
      return;
    }

    if (this.editing) {
      await this.#saveEdit(title);
    } else {
      await this.#saveNew(title);
    }
  }

  async #saveNew(title) {
    await this.#run(
      () => this.createTask({ title, body: this.bodyInput.value, status: this.status }),
      (task) => {
        this.form.reset();
        this.onSaved(task);
      },
    );
  }

  async #saveEdit(title) {
    const task = this.editing;
    const body = this.bodyInput.value.trim() || null;
    if (title === task.title && body === (task.body ?? null)) {
      this.modal.close(); // nothing to save
      return;
    }
    await this.#run(
      () => this.updateTask(task.id, { title, body }),
      (saved) => {
        this.#leaveEditMode();
        this.onSaved(saved);
      },
      (error) => {
        if (error.status !== 404) return false;
        // Deleted elsewhere in the meantime.
        this.#leaveEditMode();
        this.modal.close();
        this.onGone(task);
        return true;
      },
    );
  }

  /** Shared request lifecycle: busy state, error display, close on success. */
  async #run(request, onSuccess, onError = () => false) {
    this.#setFormError("");
    this.#setBusy(true);
    try {
      const result = await request();
      this.#setBusy(false);
      this.modal.close();
      onSuccess(result);
    } catch (error) {
      this.#setBusy(false);
      if (!onError(error)) this.#showError(error);
    }
  }

  #leaveEditMode() {
    if (!this.editing) return;
    this.editing = null;
    this.titleInput.value = this.draft?.title ?? "";
    this.bodyInput.value = this.draft?.body ?? "";
    this.draft = null;
  }

  #present(heading, submitLabel) {
    this.heading.textContent = heading;
    this.submitLabel.textContent = submitLabel;
    this.#setTitleError("");
    this.#setFormError("");
    if (this.cardNav) this.cardNav.hidden = !this.editing; // task actions only exist for saved tasks
  }

  #showError(error) {
    const fieldMessage = error.fieldErrors?.title;
    if (fieldMessage) {
      this.#setTitleError(fieldMessage);
      this.titleInput.focus();
    } else {
      this.#setFormError(error.message || "The artifact could not be saved. Please try again.");
    }
  }

  #setBusy(busy) {
    this.busy = busy;
    // aria-disabled (not `disabled`) so the focused button keeps focus inside the dialog.
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
