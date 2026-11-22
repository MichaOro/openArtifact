/* The task modal in three modes: "create" (form), "view" (read-only, references are links) and
 * "edit" (form). An existing artifact opens in view mode; saving an edit returns to it.
 * No markup knowledge beyond the data-/id hooks below; what happens with a saved task is
 * delegated via onSaved, so this module never touches the board. */
import { renderReferences } from "./references.js";

export class TaskForm {
  /**
   * @param {object} options
   * @param {import("../components/modal.js").Modal} options.modal
   * @param {(task: {title: string, body: string, status: string}) => Promise<object>} options.createTask
   * @param {(id: string, fields: {title: string, body: string|null}) => Promise<object>} options.updateTask
   * @param {(task: object) => void} options.onSaved called with the created/updated task
   * @param {(task: object) => void} options.onGone called when an edited task no longer exists
   * @param {(number: number) => object|undefined} options.findByNumber resolves "#n" references
   * @param {(number: number) => void} options.onReference a reference link was followed
   * @param {() => void} options.onBack the Back button was pressed
   */
  constructor({ modal, createTask, updateTask, onSaved, onGone, findByNumber, onReference, onBack }) {
    this.modal = modal;
    this.createTask = createTask;
    this.updateTask = updateTask;
    this.onSaved = onSaved;
    this.onGone = onGone;
    this.findByNumber = findByNumber;
    this.mode = "create";
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
    this.view = root.querySelector("[data-task-view]");
    this.viewTitle = root.querySelector("[data-view-title]");
    this.viewBody = root.querySelector("[data-view-body]");
    this.backButton = root.querySelector("[data-view-back]");

    // Closing (X, Cancel, Escape, overlay) is blocked while a request is running.
    modal.canClose = () => !this.busy;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.titleInput.addEventListener("input", () => this.#setTitleError(""));
    this.cancelButton.addEventListener("click", () => (this.mode === "edit" ? this.#showView() : this.modal.close()));
    root.querySelector("[data-view-edit]").addEventListener("click", () => this.startEdit());
    this.backButton.addEventListener("click", () => onBack());
    this.viewBody.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-number]");
      if (!link) return;
      event.preventDefault();
      onReference(Number(link.dataset.number));
    });
  }

  /** Open in create mode for a lane. The draft is kept if the user dismissed the modal earlier. */
  open(status, laneTitle, hue) {
    this.#leaveEditMode();
    this.status = status;
    this.mode = "create";
    this.#present("Create Artifact", "Create Artifact");
    this.#showNumber(null);
    this.setLane(status, laneTitle, hue);
    this.modal.open();
  }

  /** Open an existing artifact read-only; `canGoBack` shows the Back button. */
  openView(task, laneTitle, hue, parentTitle = null, canGoBack = false) {
    this.editing = task;
    this.backButton.hidden = !canGoBack;
    this.setLane(task.status, laneTitle, hue);
    this.setParent(parentTitle);
    this.#showNumber(task.number);
    this.#showView();
    if (!this.modal.isOpen) this.modal.open();
  }

  /** Update the read-only view when the artifact (or what it references) changed elsewhere. */
  refreshView(task) {
    if (this.mode !== "view" || this.editing?.id !== task.id) return;
    this.editing = task;
    this.#showView();
  }

  /** Switch from the read-only view to the form. */
  startEdit() {
    const task = this.editing;
    if (!task || this.mode !== "view") return;
    if (!this.draft) this.draft = { title: this.titleInput.value, body: this.bodyInput.value };
    this.titleInput.value = task.title;
    this.bodyInput.value = task.body ?? "";
    this.mode = "edit";
    this.#present("Edit Artifact", "Save");
    this.view.hidden = true;
    this.form.hidden = false;
    this.titleInput.focus();
  }

  #showView() {
    const task = this.editing;
    this.mode = "view";
    this.#present("Artifact", "Save");
    this.form.hidden = true;
    this.view.hidden = false;
    this.viewTitle.textContent = task.title;
    this.viewBody.replaceChildren(renderReferences(task.body ?? "", this.findByNumber));
  }

  /** The artifact number in the header (only for saved artifacts). */
  #showNumber(number) {
    if (!this.numberLabel) return;
    this.numberLabel.hidden = number == null;
    this.numberLabel.textContent = number == null ? "" : `#${number}`;
    this.numberLabel.title = `Artifact number: reference it as #${number}`;
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
      this.#showView(); // nothing to save
      return;
    }
    await this.#run(
      () => this.updateTask(task.id, { title, body }),
      (saved) => {
        this.editing = saved;
        this.#showView();
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
      { close: false },
    );
  }

  /** Shared request lifecycle: busy state, error display, close on success. */
  async #run(request, onSuccess, onError = () => false, { close = true } = {}) {
    this.#setFormError("");
    this.#setBusy(true);
    try {
      const result = await request();
      this.#setBusy(false);
      if (close) this.modal.close();
      onSuccess(result);
    } catch (error) {
      this.#setBusy(false);
      if (!onError(error)) this.#showError(error);
    }
  }

  #leaveEditMode() {
    if (!this.editing) return;
    this.editing = null;
    if (this.draft) {
      this.titleInput.value = this.draft.title;
      this.bodyInput.value = this.draft.body;
      this.draft = null;
    }
  }

  #present(heading, submitLabel) {
    this.heading.textContent = heading;
    this.submitLabel.textContent = submitLabel;
    this.#setTitleError("");
    this.#setFormError("");
    if (this.mode === "create") {
      this.view.hidden = true;
      this.form.hidden = false;
      this.backButton.hidden = true;
    }
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
