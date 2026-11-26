/* Guards a page with unsaved changes (templates/components/leave_modal.html): a click on one of the page's own
 * links opens the dialog "Unsaved changes" (Stay, Leave without saving, Save and leave) instead of the browser's
 * question. Closing the tab, reloading or typing an address still gets the browser's own question; a page
 * cannot replace that one. */
import { ActionDialog } from "./action-dialog.js";
import { t } from "../i18n.js";

export class LeaveGuard extends ActionDialog {
  /**
   * @param {import("./modal.js").Modal} modal
   * @param {{isDirty: () => boolean, save: () => Promise<unknown>}} hooks
   */
  constructor(modal, { isDirty, save }) {
    super(modal, t("components.leave_guard.could_not_save_please_try"));
    this.isDirty = isDirty;
    this.save = save;
    this.target = null;
    this.leaving = false;
    this.submitButton.addEventListener("click", async () => {
      if (await this.run(() => this.save(), { close: false })) this.#go();
    });
    this.root.querySelector("[data-leave-discard]").addEventListener("click", () => this.#go());
    document.addEventListener("click", (event) => this.#onClick(event));
    window.addEventListener("beforeunload", (event) => {
      if (!this.leaving && this.isDirty()) event.preventDefault();
    });
  }

  #onClick(event) {
    const link = event.target.closest?.("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target && link.target !== "_self") return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin || !this.isDirty()) return;
    if (url.pathname === window.location.pathname && url.hash) return; // a jump within the page
    event.preventDefault();
    this.target = url.href;
    this.setError("");
    this.modal.open();
  }

  #go() {
    this.leaving = true;
    window.location.assign(this.target);
  }
}
