/* Generic confirmation dialog: shows a message, runs an async action on confirm, keeps the
 * dialog open and shows the error if the action fails. */

export class ConfirmDialog {
  /** @param {import("./modal.js").Modal} modal */
  constructor(modal) {
    this.modal = modal;
    this.busy = false;
    this.action = null;
    const root = modal.dialog;
    this.message = root.querySelector("[data-confirm-message]");
    this.error = root.querySelector("[data-form-error]");
    this.confirmButton = root.querySelector("[data-confirm]");
    this.label = root.querySelector("[data-confirm-label]");
    modal.canClose = () => !this.busy;
    this.confirmButton.addEventListener("click", () => this.#confirm());
  }

  /**
   * @param {object} options
   * @param {string} options.message
   * @param {() => Promise<unknown>} options.onConfirm
   * @param {string} [options.confirmLabel]
   */
  open({ message, onConfirm, confirmLabel = "Delete" }) {
    this.action = onConfirm;
    this.message.textContent = message;
    this.label.textContent = confirmLabel;
    this.error.hidden = true;
    this.modal.open();
  }

  async #confirm() {
    if (this.busy || !this.action) return;
    this.#setBusy(true);
    try {
      await this.action();
    } catch (error) {
      this.#setBusy(false);
      this.error.textContent = error.message || "That did not work. Please try again.";
      this.error.hidden = false;
      return;
    }
    this.#setBusy(false);
    this.modal.close();
  }

  #setBusy(busy) {
    this.busy = busy;
    this.confirmButton.setAttribute("aria-disabled", String(busy));
    this.confirmButton.setAttribute("aria-busy", String(busy));
  }
}
