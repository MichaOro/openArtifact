/* The dialog that asks for a name (templates/components/name_modal.html): create or rename something.
 * It stays open with the reason when the action fails. */
import { Modal } from "./modal.js";

export class NameDialog {
  /** @param {HTMLDialogElement} dialog rendered by the name_modal macro */
  constructor(dialog) {
    this.modal = new Modal(dialog);
    this.title = dialog.querySelector(".modal__title");
    this.form = dialog.querySelector("form");
    this.input = dialog.querySelector("input");
    this.fieldError = dialog.querySelector(".field__error");
    this.formError = dialog.querySelector("[data-form-error]");
    this.action = null;
    this.input.addEventListener("input", () => (this.fieldError.hidden = true));
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.#submit();
    });
  }

  /**
   * @param {object} options
   * @param {string} options.title
   * @param {string} [options.value] the name to start with
   * @param {(name: string) => Promise<unknown>} options.onSubmit closes the dialog when it resolves
   */
  open({ title, value = "", onSubmit }) {
    this.title.textContent = title;
    this.input.value = value;
    this.fieldError.hidden = true;
    this.formError.hidden = true;
    this.action = onSubmit;
    this.modal.open();
    this.input.select();
  }

  async #submit() {
    const name = this.input.value.trim();
    if (!name) {
      this.fieldError.textContent = "Please enter a name.";
      this.fieldError.hidden = false;
      this.input.focus();
      return;
    }
    try {
      await this.action(name);
      this.modal.close();
    } catch (error) {
      this.formError.textContent = error.detail ?? (error.message || "Could not save. Please try again.");
      this.formError.hidden = false;
    }
  }
}
