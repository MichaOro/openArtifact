/* The one dialog with input fields: a form (templates/components/form_modal.html), a submit
 * button and Cancel. What is asked and where the result goes are parameters:
 *
 *   dialog.open({ title, values, submitLabel, onSubmit })
 *
 * onSubmit(values) returns a promise and decides where the result is saved (API call, board,
 * graph). The dialog validates required fields, shows field errors (error.fieldErrors) and a
 * form error (error.detail / error.message), blocks double submits and closes on success.
 * Specialisations (ArtifactDialog) extend this class; plain uses just instantiate it. */
import { ActionDialog } from "./action-dialog.js";

export class FormDialog extends ActionDialog {
  /** @param {import("./modal.js").Modal} modal rendered by the form_modal macro */
  constructor(modal) {
    super(modal, "Could not save. Please try again.");
    this.form = this.root.querySelector("form");
    this.submitLabelEl = this.submitButton.querySelector("[data-submit-label]");
    this.defaultSubmitLabel = this.submitLabelEl.textContent;
    this.onSubmit = null;
    /** @type {Map<string, {control: HTMLInputElement|HTMLTextAreaElement, error: HTMLElement, label: string}>} */
    this.fields = new Map();
    for (const wrapper of this.form.querySelectorAll("[data-field]")) {
      const control = wrapper.querySelector("[name]");
      this.fields.set(control.name, {
        control,
        error: wrapper.querySelector("[data-field-error]"),
        label: wrapper.querySelector("label").firstChild.textContent.trim(),
      });
      control.addEventListener("input", () => this.setFieldError(control.name, ""));
    }
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.cancelButton.addEventListener("click", () => this.cancel());
  }

  /**
   * @param {object} options
   * @param {string} options.title
   * @param {Record<string, string>} [options.values] start values by field name
   * @param {string} [options.submitLabel] default: what the markup says ("Create")
   * @param {(values: Record<string, string>) => Promise<unknown>} options.onSubmit
   */
  open({ title, values = {}, submitLabel, onSubmit }) {
    this.present({ title, submitLabel, onSubmit });
    this.setValues(values);
    this.modal.open();
    this.focusFirst();
  }

  /** Texts and target of the next submit, errors cleared. The fields keep their values. */
  present({ title, submitLabel, onSubmit }) {
    this.titleEl.textContent = title;
    this.submitLabelEl.textContent = submitLabel ?? this.defaultSubmitLabel;
    this.onSubmit = onSubmit;
    this.clearErrors();
  }

  /** Values by field name; single-line fields are trimmed. */
  values() {
    const result = {};
    for (const [name, { control }] of this.fields) {
      result[name] = control instanceof HTMLInputElement ? control.value.trim() : control.value;
    }
    return result;
  }

  /** Untouched field values, for parking a draft. */
  snapshot() {
    return Object.fromEntries([...this.fields].map(([name, { control }]) => [name, control.value]));
  }

  setValues(values) {
    for (const [name, { control }] of this.fields) control.value = values[name] ?? "";
  }

  /** Empty the fields (after a successful submit). */
  reset() {
    this.form.reset();
  }

  focusFirst() {
    const first = this.fields.values().next().value?.control;
    first?.focus();
    if (first instanceof HTMLInputElement) first.select();
  }

  /** The Cancel button. */
  cancel() {
    this.modal.close();
  }

  clearErrors() {
    for (const name of this.fields.keys()) this.setFieldError(name, "");
    this.setError("");
  }

  setFieldError(name, message) {
    const { control, error } = this.fields.get(name);
    error.textContent = message;
    error.hidden = !message;
    control.setAttribute("aria-invalid", String(Boolean(message)));
  }

  /** Mark the first empty required field; true when all are filled. */
  validate() {
    const values = this.values();
    for (const [name, { control, label }] of this.fields) {
      if (control.required && !values[name]) {
        this.setFieldError(name, `Please enter a ${label.toLowerCase()}.`);
        control.focus();
        return false;
      }
    }
    return true;
  }

  async submit() {
    if (this.busy || !this.validate()) return;
    const close = this.closesOnSuccess;
    if ((await this.run(() => this.onSubmit(this.values()), { close })) && close) this.reset();
  }

  /** Whether a successful submit closes the dialog (an edit that returns to a view does not). */
  get closesOnSuccess() {
    return true;
  }

  showError(error) {
    const [name, message] = Object.entries(error.fieldErrors ?? {}).find(([field]) => this.fields.has(field)) ?? [];
    if (name === undefined) {
      super.showError(error);
      return;
    }
    this.setFieldError(name, message);
    this.fields.get(name).control.focus();
  }
}
