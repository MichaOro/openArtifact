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
   * @param {{retry?: boolean, autoHide?: number, tone?: "info"}} options retry: offer Retry; autoHide: hide after
   *   this many ms; tone "info": a message that is news, not an error (calm colour)
   */
  show(message, { retry = false, autoHide = 0, tone = "" } = {}) {
    this.text.textContent = message;
    if (tone) this.root.dataset.tone = tone;
    else delete this.root.dataset.tone;
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
