/* Reusable modal controller for a native <dialog class="modal">.
 *
 * Native <dialog>.showModal() provides the focus trap, makes the page inert,
 * restores focus to the opener on close, and handles Escape. This class adds:
 *  - close via overlay click, [data-modal-close] buttons and Escape, all routed
 *    through close() so a `canClose` guard can veto them (e.g. while saving);
 *  - initial focus on [data-autofocus].
 */
export class Modal {
  /** @param {HTMLDialogElement} dialog */
  constructor(dialog) {
    this.dialog = dialog;
    /** Return false to keep the modal open. */
    this.canClose = () => true;
    this._pressStartedOnOverlay = false;

    // Escape: handled on keydown at document level so the guard applies deterministically,
    // even if focus sits on <body>. (Browsers make the `cancel` event non-cancelable on
    // repeated Escape presses, so `cancel` is only a fallback.)
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !dialog.open) return;
      event.preventDefault();
      this.close();
    });
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      this.close();
    });

    // Overlay click closes — but not when a text selection drag ends on the overlay.
    dialog.addEventListener("mousedown", (event) => {
      this._pressStartedOnOverlay = event.target === dialog;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && this._pressStartedOnOverlay) this.close();
      this._pressStartedOnOverlay = false;
    });

    dialog.querySelectorAll("[data-modal-close]").forEach((button) => {
      button.addEventListener("click", () => this.close());
    });
  }

  get isOpen() {
    return this.dialog.open;
  }

  open() {
    if (!this.dialog.open) this.dialog.showModal();
    const target = this.dialog.querySelector("[data-autofocus]");
    if (target instanceof HTMLElement) target.focus();
  }

  close() {
    if (!this.dialog.open || !this.canClose()) return;
    this.dialog.close();
  }
}
