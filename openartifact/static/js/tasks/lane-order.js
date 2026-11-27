/* Reordering the lanes (ADR-092). The board's menu switches a mode on: the lanes make room above them for a handle each, cards stay where they are,
 * and a lane moves by its handle (the pointer, or ArrowLeft / ArrowRight on the focused handle). A drop is saved at once with the new order of the
 * statuses; when the save fails the old order comes back. The mode is not stored: a reload ends it, and so does Escape. */
import { Sortable } from "../components/sortable.js";
import { t } from "../i18n.js";
import { moveLane, orderChanged } from "./lane-order-model.js";

export class LaneReorder {
  /**
   * @param {object} options
   * @param {import("./board.js").Board} options.board
   * @param {(order: string[]) => Promise<object[]>} options.save puts the lanes in this order on the server; resolves to the lanes
   * @param {(lanes: object[]) => void} options.onLanes shows the lanes the server answered with
   */
  constructor({ board, save, onLanes }) {
    Object.assign(this, { board, save, onLanes });
    this.on = false;
    this.sortable = new Sortable(board.element, {
      handle: "[data-lane-grip]",
      axis: "x",
      scroller: board.element,
      onMove: (from, to, by) => this.#moved(from, to, by),
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.on && !document.querySelector("dialog[open]")) this.set(false);
    });
  }

  /** The mode on or off; the handles can be focused only while it is on. */
  set(on) {
    this.on = on;
    this.board.setReordering(on);
    for (const grip of this.board.element.querySelectorAll("[data-lane-grip]")) grip.tabIndex = on ? 0 : -1;
    if (on) this.board.announce(t("lane.reorder_on"));
  }

  async #moved(from, to, by) {
    const before = this.board.statuses;
    const after = by === "pointer" ? this.board.laneOrder() : moveLane(before, from, to);
    if (!orderChanged(before, after)) return;
    const status = after[to];
    try {
      this.onLanes(await this.save(after));
    } catch (error) {
      this.onLanes(null); // draw the old order again
      this.board.showError(error.detail ?? error.message ?? t("lane.reorder_failed"));
      return;
    }
    const total = after.length;
    this.board.announce(t("lane.moved", { name: this.board.laneTitle(status), n: after.indexOf(status) + 1, total }));
    this.board.lanes.get(status)?.section.querySelector("[data-lane-grip]")?.focus();
    for (const grip of this.board.element.querySelectorAll("[data-lane-grip]")) grip.tabIndex = this.on ? 0 : -1;
  }
}
