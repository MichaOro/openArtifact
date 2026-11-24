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
   *   this many ms; tone "info": a message that is news, not an error: a calm colour, and it floats above an open
   *   window (the popover layer), because a window's backdrop would cover the bar and the news would go unseen
   */
  show(message, { retry = false, autoHide = 0, tone = "" } = {}) {
    this.#closePopover();
    this.text.textContent = message;
    if (tone) this.root.dataset.tone = tone;
    else delete this.root.dataset.tone;
    const floats = tone === "info" && typeof this.root.showPopover === "function";
    if (floats) this.root.setAttribute("popover", "manual");
    else this.root.removeAttribute("popover");
    if (this.retryButton) this.retryButton.hidden = !retry;
    this.root.hidden = false;
    if (floats) this.root.showPopover();
    window.clearTimeout(this.timer);
    if (autoHide) this.timer = window.setTimeout(() => this.hide(), autoHide);
  }

  hide() {
    window.clearTimeout(this.timer);
    this.#closePopover();
    this.root.hidden = true;
  }

  #closePopover() {
    try {
      if (this.root.matches(":popover-open")) this.root.hidePopover();
    } catch {
      /* no popover support: the bar is in the page */
    }
  }
}
