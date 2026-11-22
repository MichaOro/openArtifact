/* Renaming a lane: the pencil in the lane header opens a one-field FormDialog; "Reset to default"
 * (only shown for a custom title) restores the default. Only the title changes, never the status code. */
import { FormDialog } from "../components/form-dialog.js";
import { request } from "../http.js";

export const listLanes = () => request("/api/lanes");

/** @param {string} status @param {string|null} title null restores the default. Resolves to the lanes. */
export const renameLane = (status, title) =>
  request(`/api/lanes/${encodeURIComponent(status)}`, { method: "PUT", body: JSON.stringify({ title }) });

export class LaneRenamer {
  /** @param {{modal: import("../components/modal.js").Modal, board: import("./board.js").Board}} options */
  constructor({ modal, board }) {
    this.board = board;
    this.dialog = new FormDialog(modal);
    this.reset = modal.dialog.querySelector("[data-reset]");
    this.status = null;
    this.reset.addEventListener("click", () => this.#save(null));
    board.element.addEventListener("click", (event) => {
      const button = event.target.closest("[data-rename-lane]");
      if (button) this.open(button.closest("[data-lane]").dataset.status);
    });
  }

  open(status) {
    this.status = status;
    const title = this.board.laneTitle(status);
    this.reset.hidden = !this.board.laneIsCustom(status);
    this.dialog.open({
      title: "Rename lane",
      values: { title },
      submitLabel: "Save",
      onSubmit: ({ title: chosen }) => this.#request(status, chosen),
    });
  }

  async #request(status, title) {
    this.board.setLanes(await renameLane(status, title));
    this.board.announce(`Lane renamed to ${this.board.laneTitle(status)}`);
  }

  #save(title) {
    return this.dialog.run(() => this.#request(this.status, title));
  }
}
