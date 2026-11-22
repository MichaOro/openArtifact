/* The alert bar of a page (templates/components/alert.html): a message with an optional Retry. */

export class AlertBar {
  /** @param {HTMLElement} root the element with [data-alert] */
  constructor(root = document.querySelector("[data-alert]")) {
    this.root = root;
    this.text = root.querySelector("[data-alert-text]");
    this.retryButton = root.querySelector("[data-alert-retry]");
    this.timer = null;
  }

  /** @param {() => void} callback what Retry does */
  onRetry(callback) {
    this.retryButton?.addEventListener("click", callback);
  }

  /**
   * @param {string} message
   * @param {{retry?: boolean, autoHide?: number}} options retry: offer Retry; autoHide: hide after this many ms
   */
  show(message, { retry = false, autoHide = 0 } = {}) {
    this.text.textContent = message;
    if (this.retryButton) this.retryButton.hidden = !retry;
    this.root.hidden = false;
    window.clearTimeout(this.timer);
    if (autoHide) this.timer = window.setTimeout(() => this.hide(), autoHide);
  }

  hide() {
    window.clearTimeout(this.timer);
    this.root.hidden = true;
  }
}
