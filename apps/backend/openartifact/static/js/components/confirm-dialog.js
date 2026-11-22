/* Generic confirmation dialog (templates/components/confirm_modal.html): shows a message, runs an
 * async action on confirm, keeps the dialog open and shows the error if the action fails. */

export class ConfirmDialog {
  /** @param {import("./modal.js").Modal} modal */
  constructor(modal) {
    this.modal = modal;
    this.busy = false;
    this.action = null;
    this.onClose = null;
    const root = modal.dialog;
    this.message = root.querySelector("[data-confirm-message]");
    this.note = root.querySelector("[data-confirm-note]");
    this.error = root.querySelector("[data-form-error]");
    this.confirmButton = root.querySelector("[data-confirm]");
    this.cancelButton = root.querySelector("[data-cancel]");
    this.label = root.querySelector("[data-confirm-label]");
    modal.canClose = () => !this.busy;
    this.confirmButton.addEventListener("click", () => this.#confirm());
  }

  /**
   * @param {object} options
   * @param {string} options.message `{subject}` in it is replaced by the subject, set in bold
   * @param {string} [options.subject]
   * @param {string} [options.note] a second line (needs a note in the markup)
   * @param {() => Promise<unknown>} options.onConfirm
   * @param {string} [options.confirmLabel]
   * @param {() => void} [options.onClose] called once the dialog has closed after a confirmed action
   */
  open({ message, subject = null, note = "", onConfirm, confirmLabel = "Delete", onClose = null }) {
    this.action = onConfirm;
    this.onClose = onClose;
    this.#showMessage(message, subject);
    if (this.note) {
      this.note.textContent = note;
      this.note.hidden = !note;
    }
    this.label.textContent = confirmLabel;
    this.error.hidden = true;
    this.modal.open();
  }

  #showMessage(message, subject) {
    const [before, after] = message.split("{subject}");
    if (subject === null || after === undefined) {
      this.message.textContent = message;
      return;
    }
    const strong = document.createElement("strong");
    strong.className = "confirm-text__subject";
    strong.textContent = subject;
    this.message.replaceChildren(before, strong, after);
  }

  async #confirm() {
    if (this.busy || !this.action) return;
    this.#setBusy(true);
    this.error.hidden = true;
    try {
      await this.action();
    } catch (error) {
      this.#setBusy(false);
      this.error.textContent = error.detail ?? (error.message || "That did not work. Please try again.");
      this.error.hidden = false;
      return;
    }
    this.#setBusy(false);
    this.modal.close();
    this.onClose?.();
  }

  #setBusy(busy) {
    this.busy = busy;
    for (const button of [this.confirmButton, this.cancelButton]) button?.setAttribute("aria-disabled", String(busy));
    this.confirmButton.setAttribute("aria-busy", String(busy));
  }
}
