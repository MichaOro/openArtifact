/* The strip of counters above the list. Each is a toggle button: pressing it applies the filter that
 * shows exactly those executions, pressing it again (or "Total") clears the filters. */
import { Filters } from "./filters.js";

/** The filters each counter stands for. `total` means no filter at all. */
const COUNTERS = {
  running: new Filters({ status: ["running"] }),
  failed_24h: new Filters({ status: ["failed"], range: "24h" }),
  done_24h: new Filters({ status: ["done"], range: "24h" }),
  total: new Filters(),
};

const sameFilters = (a, b) => a.toSearch() === b.toSearch();

export class SummaryStrip {
  /**
   * @param {HTMLElement} root the section
   * @param {(filters: Filters) => void} onSelect
   */
  constructor(root, onSelect) {
    this.root = root;
    this.buttons = [...root.querySelectorAll("[data-summary]")];
    this.current = new Filters();
    for (const button of this.buttons) button.addEventListener("click", () => onSelect(this.#target(button.dataset.summary)));
  }

  #target(key) {
    const pressed = sameFilters(this.current.with({ pageSize: "" }), COUNTERS[key]);
    return pressed ? new Filters({ pageSize: this.current.pageSize }) : COUNTERS[key].with({ pageSize: this.current.pageSize });
  }

  /** @param {{running: number, failed_24h: number, done_24h: number, total: number}} summary */
  render(summary) {
    for (const button of this.buttons) {
      button.querySelector("[data-summary-value]").textContent = String(summary[button.dataset.summary]);
    }
  }

  /** Mark the counter whose filter is the current one (the total counts when nothing is filtered). */
  setFilters(filters) {
    this.current = filters;
    for (const button of this.buttons) {
      const on = filters.active && sameFilters(filters.with({ pageSize: "" }), COUNTERS[button.dataset.summary]);
      button.setAttribute("aria-pressed", String(on));
    }
  }
}
