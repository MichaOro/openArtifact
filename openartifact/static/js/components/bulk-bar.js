/* The bar above a list while rows are selected: how many, "Select all N" when more exist than are shown, clear, and
 * the bulk action. Behaviour only; the markup is the page's ([data-bulk] with [data-bulk-count], [data-bulk-all],
 * [data-bulk-clear], [data-bulk-delete]). Pairs with components/selection.js. */
import { plural } from "../tasks/history-format.js";

export class BulkBar {
  /**
   * @param {HTMLElement} root the [data-bulk] element
   * @param {string} noun what the rows are ("execution")
   * @param {{onClear: () => void, onAll: () => void, onDelete: () => void}} actions
   */
  constructor(root, noun, { onClear, onAll, onDelete }) {
    this.root = root;
    this.noun = noun;
    this.count = root.querySelector("[data-bulk-count]");
    this.all = root.querySelector("[data-bulk-all]");
    this.all.addEventListener("click", onAll);
    root.querySelector("[data-bulk-clear]").addEventListener("click", onClear);
    root.querySelector("[data-bulk-delete]").addEventListener("click", onDelete);
  }

  /**
   * @param {number} selected how many are selected
   * @param {{total: number, offerAll: boolean, everything: boolean, busy?: boolean}} state `total`: how many the list
   *   holds in all; `offerAll`: show "Select all N" (all that are shown are selected and more exist than are shown);
   *   `everything`: all of them are selected, not only the shown ones
   */
  render(selected, { total, offerAll, everything, busy = false }) {
    this.root.hidden = selected === 0;
    this.count.textContent = everything ? `All ${plural(total, this.noun)} selected` : `${selected} selected`;
    const offer = offerAll && !everything;
    this.all.hidden = !offer;
    if (offer) this.all.textContent = `Select all ${plural(total, this.noun)}`;
    for (const button of this.root.querySelectorAll("button")) button.disabled = busy;
  }
}
