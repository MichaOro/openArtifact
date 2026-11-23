/* The lane settings dialog (templates/components/lane_settings_modal.html): how a lane draws its
 * cards, with a preview made of copies of the real card. Save is possible once something changed;
 * Cancel, Escape and the backdrop discard. */
import { ActionDialog } from "../components/action-dialog.js";
import { t } from "../i18n.js";

export class LaneSettingsDialog extends ActionDialog {
  /** @param {import("../components/modal.js").Modal} modal */
  constructor(modal) {
    super(modal, t("agents.providers_page.could_not_save_please_try"));
    this.chip = this.root.querySelector("[data-modal-chip]");
    this.finished = this.root.querySelector("[data-setting-finished]");
    this.preview = this.root.querySelector("[data-lane-preview]");
    this.#fillPreview(this.root.querySelector("[data-preview-cards]"));
    this.initial = "normal";
    this.onSave = null;
    this.finished.addEventListener("change", () => this.#sync());
    this.submitButton.addEventListener("click", () => this.#save());
  }

  /**
   * @param {object} options
   * @param {string} options.title the lane's name, shown as a chip in its colour
   * @param {string} options.hue the lane's palette index
   * @param {string} options.style the lane's current style
   * @param {(style: string) => Promise<unknown>} options.onSave
   */
  open({ title, hue, style, onSave }) {
    this.onSave = onSave;
    this.initial = style;
    this.chip.textContent = title;
    this.chip.dataset.laneHue = hue;
    this.finished.checked = style === "finished";
    this.setError("");
    this.#sync();
    this.modal.open();
  }

  get style() {
    return this.finished.checked ? "finished" : "normal";
  }

  /** Two sample cards copied from the board's own card template, so the preview is the real thing. */
  #fillPreview(list) {
    const samples = [
      [t("tasks.lane_settings.draft_release_notes"), t("tasks.lane_settings.collect_changes_week"), ""],
      [t("tasks.lane_settings.publish_changelog"), t("tasks.lane_settings.announce_team"), t("tasks.lane_settings.parent_release_2_4")],
    ];
    for (const [title, body, meta] of samples) {
      const card = document.getElementById("task-card-template").content.firstElementChild.cloneNode(true);
      card.querySelector(".task-card__title").textContent = title;
      card.querySelector(".task-card__body").textContent = body;
      const line = card.querySelector(".task-card__meta");
      line.textContent = meta;
      line.hidden = !meta;
      card.querySelector("[data-delete-task]").remove();
      // a picture of a card, not a card: nothing to open, move or delete
      for (const name of ["tabindex", "aria-haspopup", "aria-keyshortcuts"]) card.removeAttribute(name);
      list.append(card);
    }
  }

  #sync() {
    this.preview.classList.toggle("lane--finished", this.style === "finished");
    this.submitButton.disabled = this.style === this.initial;
  }

  async #save() {
    if (this.submitButton.disabled || !this.onSave) return;
    await this.run(() => this.onSave(this.style));
  }
}
