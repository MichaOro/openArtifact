/* A list whose entries are reordered by their handle (ADR-050): drag it with the pointer (the entry follows
 * between its neighbours, `is-dragging` while it moves), or focus it and press ArrowUp / ArrowDown. Only the
 * handle starts a move, so a click on the rest of the entry stays a click. The list's owner keeps the order:
 * `onMove(from, to, by)` reports where an entry went; the owner changes its data and draws the list again. `by` is
 * `"pointer"` when the entry already stands at `to` in the document (the drag moved it as it went) and `"key"` when
 * it still stands at `from` (the owner moves it); an owner that draws the list anew from its data can ignore it.
 * `axis: "x"` makes it a row (the lanes of the board): the pointer's X decides, the keys are ArrowLeft / ArrowRight, and with `scroller` (the row's
 * scrolling box) a drag near its left or right edge scrolls it. */

export class Sortable {
  /**
   * @param {HTMLElement} list the element whose children are the entries
   * @param {{handle: string, onMove: (from: number, to: number, by: "pointer" | "key") => void, axis?: "y" | "x", scroller?: HTMLElement}} options
   *   handle: a selector inside an entry
   */
  constructor(list, { handle, onMove, axis = "y", scroller = null }) {
    this.list = list;
    this.handle = handle;
    this.onMove = onMove;
    this.axis = axis;
    this.scroller = scroller;
    this.drag = null;
    list.addEventListener("pointerdown", (event) => this.#start(event));
    list.addEventListener("keydown", (event) => this.#key(event));
  }

  #entries() {
    return [...this.list.children];
  }

  #start(event) {
    const grip = event.target.closest(this.handle);
    if (!grip || event.button !== 0) return;
    const entry = this.#entries().find((e) => e.contains(grip));
    if (!entry) return;
    event.preventDefault();
    const from = this.#entries().indexOf(entry);
    this.drag = { entry, from, pointerId: event.pointerId };
    entry.classList.add("is-dragging");
    // listened on the window: moving the entry in the document would end a pointer capture on the grip
    const move = (e) => {
      if (e.pointerId !== this.drag?.pointerId) return;
      this.drag.pointer = e.clientX;
      this.#move(e);
      this.#scroll();
    };
    const end = (e) => {
      if (e.pointerId !== this.drag?.pointerId) return;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      entry.classList.remove("is-dragging");
      cancelAnimationFrame(this.drag?.frame ?? 0);
      const to = this.#entries().indexOf(entry);
      this.drag = null;
      if (to !== from) this.onMove(from, to, "pointer");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }

  /** The entry moves past a neighbour once the pointer is beyond the neighbour's middle. */
  #move(event) {
    const { entry } = this.drag;
    for (const other of this.#entries()) {
      if (other === entry) continue;
      const box = other.getBoundingClientRect();
      const row = this.axis === "x";
      const middle = row ? box.left + box.width / 2 : box.top + box.height / 2;
      const at = row ? event.clientX : event.clientY;
      const before = entry.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_PRECEDING;
      if (before && at < middle) {
        this.list.insertBefore(entry, other);
        return;
      }
      if (!before && at > middle) {
        other.after(entry);
        return;
      }
    }
  }

  /** Near the left or right edge of the scrolling row the drag scrolls it, as long as the pointer stays there. */
  #scroll() {
    if (!this.scroller || this.axis !== "x" || !this.drag) return;
    cancelAnimationFrame(this.drag.frame ?? 0);
    const step = () => {
      if (!this.drag) return;
      const box = this.scroller.getBoundingClientRect();
      const x = this.drag.pointer;
      const zone = 56;
      const speed = x < box.left + zone ? -14 : x > box.right - zone ? 14 : 0;
      if (speed) {
        this.scroller.scrollLeft += speed;
        this.#move({ clientX: x, clientY: 0 });
        this.drag.frame = requestAnimationFrame(step);
      }
    };
    step();
  }

  #key(event) {
    const grip = event.target.closest(this.handle);
    const [back, forward] = this.axis === "x" ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
    if (!grip || (event.key !== back && event.key !== forward)) return;
    event.preventDefault();
    const entries = this.#entries();
    const from = entries.findIndex((e) => e.contains(grip));
    const to = from + (event.key === back ? -1 : 1);
    if (from < 0 || to < 0 || to >= entries.length) return;
    this.onMove(from, to, "key");
  }
}
