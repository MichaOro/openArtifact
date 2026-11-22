/* The lifecycle every dialog that does something has: run an async request, show its error in
 * the dialog, block closing and double submits while it runs, close on success.
 * ConfirmDialog and FormDialog extend it; they only add what they show and collect. */

export class ActionDialog {
  /**
   * @param {import("./modal.js").Modal} modal
   * @param {string} [fallbackError] shown when an error carries no message
   */
  constructor(modal, fallbackError = "That did not work. Please try again.") {
    this.modal = modal;
    this.fallbackError = fallbackError;
    this.busy = false;
    const root = modal.dialog;
    this.root = root;
    this.titleEl = root.querySelector(".modal__title");
    this.errorEl = root.querySelector("[data-form-error]");
    this.submitButton = root.querySelector("[data-submit], [data-confirm]");
    this.cancelButton = root.querySelector("[data-cancel]");
    // Closing (X, Cancel, Escape, overlay) is blocked while a request is running.
    modal.canClose = () => !this.busy;
  }

  /**
   * Run `request` with the busy state and the error line around it.
   * @param {() => Promise<unknown>} request
   * @param {{close?: boolean}} [options] close: close the dialog when it succeeded
   * @returns {Promise<boolean>} whether the request succeeded
   */
  async run(request, { close = true } = {}) {
    if (this.busy) return false; // no double submit
    this.setError("");
    this.#setBusy(true);
    try {
      await request();
    } catch (error) {
      this.#setBusy(false);
      this.showError(error);
      return false;
    }
    this.#setBusy(false);
    if (close) this.modal.close();
    return true;
  }

  /** Show why a request failed. Subclasses handle special errors first and then call super. */
  showError(error) {
    this.setError(error.detail ?? (error.message || this.fallbackError));
  }

  setError(message) {
    if (!this.errorEl) return;
    this.errorEl.textContent = message;
    this.errorEl.hidden = !message;
  }

  #setBusy(busy) {
    this.busy = busy;
    // aria-disabled (not `disabled`) so the focused button keeps focus inside the dialog.
    for (const button of [this.submitButton, this.cancelButton]) button?.setAttribute("aria-disabled", String(busy));
    this.submitButton?.setAttribute("aria-busy", String(busy));
    this.root.querySelector("form")?.setAttribute("aria-busy", String(busy));
  }
}
