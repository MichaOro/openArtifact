/* Generic confirmation dialog (templates/components/confirm_modal.html): shows a message, runs an
 * async action on confirm, keeps the dialog open and shows the error if the action fails. */
import { ActionDialog } from "./action-dialog.js";

export class ConfirmDialog extends ActionDialog {
  /** @param {import("./modal.js").Modal} modal */
  constructor(modal) {
    super(modal);
    this.action = null;
    this.onClose = null;
    this.message = this.root.querySelector("[data-confirm-message]");
    this.note = this.root.querySelector("[data-confirm-note]");
    this.label = this.root.querySelector("[data-confirm-label]");
    this.submitButton.addEventListener("click", () => this.#confirm());
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
    this.setError("");
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
    if (!this.action) return;
    if (await this.run(this.action)) this.onClose?.();
  }
}
