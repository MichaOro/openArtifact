/* Drag & drop of cards between lanes, built on Pointer Events (mouse, touch, pen).
 *
 *  - Mouse/pen: drag starts after moving a few pixels.
 *  - Touch: the card itself is the handle. A sideways swipe starts the drag at once (cards
 *    move between lanes sideways; CSS gives cards `touch-action: pan-y`, so the browser leaves
 *    horizontal gestures to us). A vertical swipe is a native scroll of the lane. A short
 *    press without moving also picks the card up, for any direction.
 *  - A ghost copy follows the pointer; the original stays as a faded placeholder.
 *  - The original card moves live to where it would land (also inside its own lane), so
 *    reordering needs no extra indicator; releasing calls onDrop with the new lane and the
 *    task it was placed before.
 *  - Near the board's left/right edge the board auto-scrolls (horizontal snap layout).
 *  - Escape or pointercancel aborts without side effects.
 *
 * The controller knows nothing about the API: it only reports the placement. */

const MOUSE_THRESHOLD = 6;
const TOUCH_INTENT_DISTANCE = 8;
const TOUCH_LONG_PRESS_MS = 250;
const EDGE_ZONE = 56;
const EDGE_SPEED = 14;

export class CardDragController {
  /**
   * @param {object} options
   * @param {import("./board.js").Board} options.board
   * @param {(task: object, placement: {status: string, beforeId: string|null, position: number}) => void} options.onDrop
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

  #onPointerDown(event) {
    if (this.pending || this.drag) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const card = event.target.closest(".task-card");
    if (!card || event.target.closest("button")) return;
    if (this.board.locked.has(card.dataset.taskId)) return; // being processed: the system moves it

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
      origin: { parent: card.parentElement, next: card.nextElementSibling },
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
    this.#reposition(lane, y);
    const target = lane && lane.dataset.status !== d.task.status ? lane : null;
    if (target !== d.hoverLane) {
      d.hoverLane?.classList.remove("lane--drop-target");
      target?.classList.add("lane--drop-target");
      d.hoverLane = target;
    }
  }

  /** Move the original card to where a drop at (lane, y) would put it. */
  #reposition(lane, y) {
    const d = this.drag;
    if (!lane) {
      this.#restore();
      return;
    }
    const list = lane.querySelector(".lane__cards");
    const others = [...list.children].filter((c) => c !== d.card);
    const reference = others.find((c) => {
      const r = c.getBoundingClientRect();
      return y < r.top + r.height / 2;
    });
    const next = reference ?? null;
    if (d.card.parentElement === list && d.card.nextElementSibling === next) return;
    list.insertBefore(d.card, next);
  }

  /** Put the dragged card back where it came from. */
  #restore(d = this.drag) {
    const { card, origin } = d;
    const next = origin.next?.parentElement === origin.parent ? origin.next : null;
    if (card.parentElement === origin.parent && card.nextElementSibling === next) return;
    origin.parent.insertBefore(card, next);
  }

  /** Auto-scroll: the board sideways near its left/right edge, a lane list near its top/bottom. */
  #tick() {
    const d = this.drag;
    if (!d) return;
    const board = this.board.element;
    let scrolled = false;
    if (board.scrollWidth > board.clientWidth) {
      const rect = board.getBoundingClientRect();
      if (d.x < rect.left + EDGE_ZONE) {
        board.scrollLeft -= EDGE_SPEED;
        scrolled = true;
      } else if (d.x > rect.right - EDGE_ZONE) {
        board.scrollLeft += EDGE_SPEED;
        scrolled = true;
      }
    }
    const list = this.#laneAt(d.x, d.y)?.querySelector(".lane__cards");
    if (list && list.scrollHeight > list.clientHeight) {
      const rect = list.getBoundingClientRect();
      if (d.y < rect.top + EDGE_ZONE) {
        list.scrollTop -= EDGE_SPEED;
        scrolled = true;
      } else if (d.y > rect.bottom - EDGE_ZONE) {
        list.scrollTop += EDGE_SPEED;
        scrolled = true;
      }
    }
    if (scrolled) this.#update(d.x, d.y); // what is under the pointer may have changed
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

    if (!lane) {
      this.#restore(d); // aborted: Escape, pointercancel or dropped outside
      return;
    }
    const status = lane.dataset.status;
    const next = d.card.nextElementSibling;
    const unchanged =
      status === d.task.status && d.card.parentElement === d.origin.parent && next === d.origin.next;
    if (unchanged) return;
    this.onDrop(d.task, {
      status,
      beforeId: next?.dataset.taskId ?? null,
      position: this.board.positionAround(d.card),
    });
  }
}
