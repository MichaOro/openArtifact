/* The artifact dialog: a FormDialog (title, body) in three modes: "create" (form), "view"
 * (read-only, references are links) and "edit" (form). An existing artifact opens in view mode;
 * saving an edit returns to it. Adds to the base only what is artifact-specific: the view, the
 * number, the lane chip, the rail's parent/lane fields and the draft. Where a saved artifact
 * goes is delegated via createTask/updateTask/onSaved, so this module never touches the board. */
import { FormDialog } from "../components/form-dialog.js";
import { Tabs } from "../components/tabs.js";
import { ParameterForm } from "./parameter-form.js";
import { parseProblems } from "./parameters.js";
import { renderReferences } from "./references.js";

/** Share of the viewport height a saved artifact's dialog may use at most. */
const AVAILABLE_HEIGHT = 0.9;
const FIT_SLACK = 10;
/** A saved artifact's dialog is never smaller than this (px): the History tab needs room for its list. */
const MIN_FIT_HEIGHT = 560;

export class ArtifactDialog extends FormDialog {
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
   * @param {import("./history-tab.js").HistoryTab} options.history the History tab; follows the artifact shown
   */
  constructor({ modal, createTask, updateTask, onSaved, onGone, findByNumber, onReference, onBack, history }) {
    super(modal);
    this.createTask = createTask;
    this.updateTask = updateTask;
    this.onSaved = onSaved;
    this.onGone = onGone;
    this.findByNumber = findByNumber;
    this.mode = "create";
    this.status = "backlog";
    /** The task being edited, or null when creating. */
    this.editing = null;
    /** Create-mode draft, parked while an edit is open. */
    this.draft = null;

    const root = this.root;
    this.titleInput = this.fields.get("title").control;
    this.bodyInput = this.fields.get("body").control;
    this.numberLabel = root.querySelector("[data-modal-number]");
    this.subtitle = root.querySelector("[data-modal-subtitle]");
    this.cardNav = root.querySelector("[data-card-nav]");
    this.laneField = root.querySelector('[data-card-field="lane"]');
    this.laneValue = root.querySelector("[data-lane-value]");
    this.laneTitle = "";
    this.parentField = root.querySelector('[data-card-field="parent"]');
    this.parentValue = root.querySelector("[data-parent-value]");
    this.panel = root.querySelector(".modal__panel");
    /** Height of the saved artifact's content without any limit; measured when it is opened. */
    this.fittedHeight = 0;
    this.view = root.querySelector("[data-task-view]");
    this.viewTitle = root.querySelector("[data-view-title]");
    this.viewBody = root.querySelector("[data-view-body]");
    this.backButton = root.querySelector("[data-view-back]");
    this.history = history;
    this.paramForm = new ParameterForm(root);
    /** The tab last used: kept while the page lives (not stored). Edit mode hides the tabs and keeps it. */
    this.tab = "details";
    this.tabs = new Tabs(root.querySelector("[data-tabs]"), (name) => this.#showTab(name));
    root.addEventListener("close", () => this.history.hide());

    root.querySelector("[data-view-edit]").addEventListener("click", () => this.startEdit());
    this.backButton.addEventListener("click", () => onBack());
    this.viewBody.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-number]");
      if (!link) return;
      event.preventDefault();
      onReference(Number(link.dataset.number));
    });
    window.addEventListener("resize", () => this.#applyFit());
  }

  /** Open in create mode for a lane. The draft is kept if the user dismissed the dialog earlier. */
  openCreate(status, laneTitle, hue) {
    this.#leaveEditMode();
    this.status = status;
    this.mode = "create";
    this.#present("Create Artifact");
    this.paramForm.setLocked(false);
    this.#unfit();
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
    this.tabs.select("details", { notify: false }); // the size is fitted to the Details content
    this.#fit();
    this.tabs.select(this.tab, { notify: false });
    this.view.dataset.tab = this.tab;
    this.history.show(task);
  }

  #showTab(name) {
    this.tab = name;
    this.view.dataset.tab = name;
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
    this.draft ??= { ...this.snapshot(), params: this.paramForm.snapshot() };
    this.setValues({ title: task.title, body: task.body ?? "" });
    this.paramForm.show(task.type_id ?? null, task.parameters ?? {});
    this.mode = "edit";
    this.#present("Edit Artifact", "Save");
    this.titleInput.focus();
  }

  /** Cancel in edit mode goes back to the view instead of closing. */
  cancel() {
    if (this.mode === "edit") this.#showView();
    else super.cancel();
  }

  /** Saving an edit stays open: it returns to the view. */
  get closesOnSuccess() {
    return this.mode !== "edit";
  }

  async submit() {
    if (this.mode === "edit" && !this.busy && this.validate() && !this.#changed()) {
      this.#showView(); // nothing to save
      return;
    }
    await super.submit();
  }

  showError(error) {
    if (this.mode === "edit" && error.status === 404) {
      // Deleted elsewhere in the meantime.
      const task = this.editing;
      this.#leaveEditMode();
      this.modal.close();
      this.onGone(task);
      return;
    }
    const { byField, other } = parseProblems(error.detail);
    if (error.status === 422 && byField.size > 0) {
      const missing = this.paramForm.showErrors(byField);
      this.setError([...other, ...missing.map((name) => `${name}: ${byField.get(name)}`)].join(" "));
      return;
    }
    super.showError(error);
  }

  /** Also empties the parameters of a new artifact once it is saved. */
  reset() {
    super.reset();
    this.paramForm.reset();
  }

  clearErrors() {
    super.clearErrors();
    this.paramForm?.clearErrors();
  }

  #changed() {
    const { title, body } = this.#editValues(this.values());
    return title !== this.editing.title || body !== (this.editing.body ?? null) || this.paramForm.changed();
  }

  #editValues({ title, body }) {
    return { title, body: body.trim() || null };
  }

  async #create({ title, body }) {
    const { type_id, parameters } = this.paramForm.collect();
    const typed = type_id ? { type_id, parameters } : {};
    this.onSaved(await this.createTask({ title, body, status: this.status, ...typed }));
  }

  /** Type and parameters to send: everything the form holds when something changed (a change of type drops the old values). */
  #parameterFields() {
    if (!this.paramForm.changed()) return {};
    const { type_id, parameters } = this.paramForm.collect();
    const typeChanged = this.paramForm.typeChanged(this.editing.type_id);
    return { type_id, parameters, ...(typeChanged ? { reset_parameters: true } : {}) };
  }

  async #save(values) {
    const saved = await this.updateTask(this.editing.id, { ...this.#editValues(values), ...this.#parameterFields() });
    this.editing = saved;
    this.#showView();
    this.onSaved(saved);
  }

  /** Size the dialog from the content of the artifact just opened; view and edit keep that size. */
  /** Size the dialog once from its content (see .modal__panel--fit): the smallest height whose
   * resulting width (0.62 x height, within the limits) lets the content fit, at most 90 % of the window. */
  #fit() {
    this.#unfit();
    this.panel.classList.add("modal__panel--fit");
    const limit = Math.floor(window.innerHeight * AVAILABLE_HEIGHT);
    if (this.#contentHeightAt(limit) > limit) {
      this.fittedHeight = limit; // more than the window allows: the body scrolls
    } else {
      // the content's height falls as the height (so the width) grows: find where they meet
      let low = 0;
      let high = limit;
      for (let i = 0; i < 10 && high - low > 4; i++) {
        const middle = Math.floor((low + high) / 2);
        if (this.#contentHeightAt(middle) <= middle) high = middle;
        else low = middle;
      }
      this.fittedHeight = Math.min(Math.max(high + FIT_SLACK, MIN_FIT_HEIGHT), limit); // slack: rounding between measuring and the fixed layout
    }
    this.#applyFit();
  }

  /** The height the content needs when the dialog's height (and so its width) is `height`. */
  #contentHeightAt(height) {
    this.panel.style.setProperty("--fit-h", `${height}px`);
    this.panel.dataset.measuring = "";
    const needed = this.panel.offsetHeight;
    delete this.panel.dataset.measuring;
    return needed;
  }

  #unfit() {
    this.panel.classList.remove("modal__panel--fit");
    this.panel.style.removeProperty("--fit-h");
  }

  /** Height: the fitted one, but at most AVAILABLE_HEIGHT of the window. The width follows in CSS. */
  #applyFit() {
    if (!this.panel.classList.contains("modal__panel--fit")) return;
    const height = Math.min(this.fittedHeight, Math.floor(window.innerHeight * AVAILABLE_HEIGHT));
    this.panel.style.setProperty("--fit-h", `${height}px`);
  }

  #showView() {
    const task = this.editing;
    this.mode = "view";
    this.#present("Artifact", "Save");
    this.viewTitle.textContent = task.title;
    this.viewBody.replaceChildren(renderReferences(task.body ?? "", this.findByNumber));
    this.paramForm.renderView(task.type_id ?? null, task.parameters ?? {});
  }

  /** The artifact types that exist (they follow ``artifact_types.changed``). */
  setTypes(types) {
    this.paramForm.setTypes(types);
    if (this.mode === "view" && this.editing) this.paramForm.renderView(this.editing.type_id ?? null, this.editing.parameters ?? {});
  }

  /** While the artifact is processed its type and parameters cannot change. */
  lockParameters(locked) {
    this.paramForm.setLocked(locked);
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

  #leaveEditMode() {
    if (!this.editing) return;
    this.editing = null;
    if (this.draft) {
      const { params, ...values } = this.draft;
      this.setValues(values);
      this.paramForm.restore(params);
      this.draft = null;
    }
  }

  /** Heading, submit text and target for the current mode; shows the form or the view. */
  #present(title, submitLabel) {
    const editing = this.mode === "edit";
    this.present({ title, submitLabel, onSubmit: (values) => (editing ? this.#save(values) : this.#create(values)) });
    const showView = this.mode === "view";
    this.view.hidden = !showView;
    this.form.hidden = showView;
    if (this.mode === "create") this.backButton.hidden = true;
    if (this.cardNav) this.cardNav.hidden = !this.editing; // task actions only exist for saved tasks
  }
}
