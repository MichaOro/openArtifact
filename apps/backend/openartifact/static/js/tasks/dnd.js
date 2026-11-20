/* Drag & drop of cards between lanes, built on Pointer Events (mouse, touch, pen).
 *
 *  - Mouse/pen: drag starts after moving a few pixels.
 *  - Touch: the card itself is the handle. A sideways swipe starts the drag at once (cards
 *    move between lanes sideways; CSS gives cards `touch-action: pan-y`, so the browser leaves
 *    horizontal gestures to us). A vertical swipe is a native scroll of the lane. A short
 *    press without moving also picks the card up, for any direction.
 *  - A ghost copy follows the pointer; the original stays as a faded placeholder.
 *  - The lane under the pointer is highlighted; releasing over another lane calls onDrop.
 *  - Near the board's left/right edge the board auto-scrolls (horizontal snap layout).
 *  - Escape or pointercancel aborts without side effects.
 *
 * The controller knows nothing about the API: it only reports (task, targetStatus). */

const MOUSE_THRESHOLD = 6;
const TOUCH_INTENT_DISTANCE = 8;
const TOUCH_LONG_PRESS_MS = 250;
const EDGE_ZONE = 56;
const EDGE_SPEED = 14;

export class CardDragController {
  /**
   * @param {object} options
   * @param {import("./board.js").Board} options.board
   * @param {(task: object, status: string) => void} options.onDrop
   */
  constructor({ board, onDrop }) {
    this.board = board;
    this.onDrop = onDrop;
    this.pending = null;
    this.drag = null;
    this.justDragged = false;

    const el = board.element;
    // Releasing a dragged card produces a click on it; that must not open the editor.
    el.addEventListener(
      "click",
      (e) => {
        if (this.justDragged) {
          e.stopPropagation();
          e.preventDefault();
        }
      },
      true,
    );
    el.addEventListener("pointerdown", (e) => this.#onPointerDown(e));
    el.addEventListener("contextmenu", (e) => {
      // Long-press on touch devices would otherwise open the browser context menu.
      if ((this.pending || this.drag) && e.target.closest(".task-card")) e.preventDefault();
    });
    document.addEventListener("pointermove", (e) => this.#onPointerMove(e));
    document.addEventListener("pointerup", (e) => this.#onPointerEnd(e, false));
    document.addEventListener("pointercancel", (e) => this.#onPointerEnd(e, true));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.drag) {
        e.preventDefault();
        this.#finish(null);
      }
    });
    // Once a drag runs, the page must not scroll under the finger.
    document.addEventListener(
      "touchmove",
      (e) => {
        if (this.drag && e.cancelable) e.preventDefault();
      },
      { passive: false },
    );
  }

  get isDragging() {
    return this.drag !== null;
  }

  #onPointerDown(event) {
    if (this.pending || this.drag) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const card = event.target.closest(".task-card");
    if (!card || event.target.closest("button")) return;

    this.pending = {
      card,
      pointerId: event.pointerId,
      type: event.pointerType,
      startX: event.clientX,
      startY: event.clientY,
      timer: null,
    };
    if (event.pointerType === "touch") {
      this.pending.timer = window.setTimeout(() => {
        if (this.pending) this.#begin(this.pending.startX, this.pending.startY);
      }, TOUCH_LONG_PRESS_MS);
    }
  }

  #onPointerMove(event) {
    if (this.drag) {
      if (event.pointerId === this.drag.pointerId) this.#update(event.clientX, event.clientY);
      return;
    }
    const p = this.pending;
    if (!p || event.pointerId !== p.pointerId) return;
    const distance = Math.hypot(event.clientX - p.startX, event.clientY - p.startY);
    if (p.type === "touch") {
      if (distance <= TOUCH_INTENT_DISTANCE) return;
      const dx = Math.abs(event.clientX - p.startX);
      const dy = Math.abs(event.clientY - p.startY);
      if (dx > dy) this.#begin(event.clientX, event.clientY); // sideways: drag
      else this.#cancelPending(); // vertical: the browser scrolls the lane
    } else if (distance > MOUSE_THRESHOLD) {
      this.#begin(event.clientX, event.clientY);
    }
  }

  #onPointerEnd(event, cancelled) {
    if (this.drag) {
      if (event.pointerId !== this.drag.pointerId) return;
      this.#finish(cancelled ? null : this.#laneAt(event.clientX, event.clientY));
    } else if (this.pending && event.pointerId === this.pending.pointerId) {
      this.#cancelPending();
    }
  }

  #cancelPending() {
    if (this.pending?.timer) window.clearTimeout(this.pending.timer);
    this.pending = null;
  }

  #begin(x, y) {
    const { card, pointerId } = this.pending;
    this.#cancelPending();
    const task = this.board.taskOf(card);
    if (!task) return;

    const rect = card.getBoundingClientRect();
    const ghost = card.cloneNode(true);
    ghost.removeAttribute("data-task-id");
    ghost.removeAttribute("tabindex");
    ghost.setAttribute("aria-hidden", "true");
    ghost.classList.add("task-card--ghost");
    ghost.style.width = `${rect.width}px`;
    document.body.append(ghost);

    card.classList.add("task-card--placeholder");
    document.body.classList.add("is-dragging");
    try {
      card.setPointerCapture(pointerId);
    } catch {
      /* the pointer may already be gone */
    }

    this.drag = {
      card,
      task,
      ghost,
      pointerId,
      offsetX: x - rect.left,
      offsetY: y - rect.top,
      x,
      y,
      hoverLane: null,
      raf: requestAnimationFrame(() => this.#tick()),
    };
    this.#update(x, y);
  }

  #update(x, y) {
    const d = this.drag;
    d.x = x;
    d.y = y;
    d.ghost.style.transform = `translate3d(${x - d.offsetX}px, ${y - d.offsetY}px, 0) rotate(1.2deg)`;

    const lane = this.#laneAt(x, y);
    const target = lane && lane.dataset.status !== d.task.status ? lane : null;
    if (target !== d.hoverLane) {
      d.hoverLane?.classList.remove("lane--drop-target");
      target?.classList.add("lane--drop-target");
      d.hoverLane = target;
    }
  }

  /** Auto-scroll the board horizontally when the pointer is near its left/right edge. */
  #tick() {
    const d = this.drag;
    if (!d) return;
    const board = this.board.element;
    if (board.scrollWidth > board.clientWidth) {
      const rect = board.getBoundingClientRect();
      if (d.x < rect.left + EDGE_ZONE) board.scrollLeft -= EDGE_SPEED;
      else if (d.x > rect.right - EDGE_ZONE) board.scrollLeft += EDGE_SPEED;
      this.#update(d.x, d.y); // lane under the pointer may have changed
    }
    d.raf = requestAnimationFrame(() => this.#tick());
  }

  #laneAt(x, y) {
    return document.elementFromPoint(x, y)?.closest("[data-lane]") ?? null;
  }

  /** End the drag; `lane` is the drop target or null to abort. */
  #finish(lane) {
    const d = this.drag;
    this.drag = null;
    cancelAnimationFrame(d.raf);
    d.ghost.remove();
    d.hoverLane?.classList.remove("lane--drop-target");
    d.card.classList.remove("task-card--placeholder");
    document.body.classList.remove("is-dragging");
    try {
      d.card.releasePointerCapture(d.pointerId);
    } catch {
      /* already released */
    }
    this.justDragged = true;
    window.setTimeout(() => (this.justDragged = false), 0);
    if (lane && lane.dataset.status !== d.task.status) this.onDrop(d.task, lane.dataset.status);
  }
}
