/* The board's search field (ADR-091): the title and the number of a card, never its body. The query keeps the cards that match (the others are hidden, the
 * lanes stay), the lane badges say "3/16", a lane without a match says so, a short line says how many cards match, the query is kept in the address
 * (`?q=`), Escape and the clear button empty it, "/" jumps into the field. The matching is board-search-model.js; hiding is Board.setFilter. */
import { parseQuery } from "./board-search-model.js";
import { tn } from "../i18n.js";

const PARAM = "q";

export class BoardSearch {
  /** @param {{board: import("./board.js").Board, root: HTMLElement}} options root: the element with the field, the clear button and the status line */
  constructor({ board, root }) {
    this.board = board;
    this.root = root;
    this.input = root.querySelector("[data-board-search]");
    this.clearButton = root.querySelector("[data-board-search-clear]");
    this.status = root.querySelector("[data-board-search-status]");
    this.input.addEventListener("input", () => this.#typed());
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.input.value) {
        event.preventDefault();
        event.stopPropagation();
        this.clear();
      }
    });
    this.clearButton.addEventListener("click", () => {
      this.clear();
      this.input.focus();
    });
    document.addEventListener("keydown", (event) => this.#slash(event));
    board.onFocusLost = () => this.input.focus();
    board.onChange = () => this.#later(); // a card arrived, changed or went (own change, another tab, an agent): the line and the badges follow
    const stored = new URLSearchParams(location.search).get(PARAM);
    if (stored) {
      this.input.value = stored;
      this.apply();
    }
  }

  /** The text in the field. */
  get query() {
    return this.input.value;
  }

  /** Empty the field: every card is shown again. */
  clear() {
    this.input.value = "";
    this.apply();
  }

  /** The user types: the cards that stay change, and a card that was kept shown for the user loses that. */
  #typed() {
    this.apply();
  }

  /** Apply the field to the board; also called when the cards have arrived (a link with `?q=`) and after the query changed. */
  apply() {
    const plan = parseQuery(this.input.value);
    const { shown } = this.board.setFilter(plan);
    this.#render(plan, shown);
    this.#address();
  }

  /** One refresh for a burst of changes (a board of hundreds of cards loads one card at a time). */
  #later() {
    if (!this.board.filter || this.pending) return;
    this.pending = true;
    queueMicrotask(() => {
      this.pending = false;
      this.refresh();
    });
  }

  /** A card changed or arrived while a query is on: the board applied it itself; the line and the badges follow. */
  refresh() {
    if (!this.board.filter) return;
    const { shown } = this.board.refilter();
    this.#render(this.board.filter, shown);
  }

  #render(plan, shown) {
    const on = plan.kind !== "all";
    this.clearButton.hidden = !on;
    this.status.textContent = on ? tn("board.search.matches", shown) : "";
  }

  #address() {
    const url = new URL(location.href);
    const value = this.input.value.trim();
    if (value) url.searchParams.set(PARAM, value);
    else url.searchParams.delete(PARAM);
    history.replaceState(history.state, "", url);
  }

  /** "/" focuses the field when no other field has the focus and no dialog is open. */
  #slash(event) {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || this.root.hidden) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.closest("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]"))) return;
    event.preventDefault();
    this.input.focus();
    this.input.select();
  }

  /** Show or hide the field (it belongs to the board, not to the archive view). */
  setVisible(on) {
    this.root.hidden = !on;
  }
}
