/* Entry point: wires board, modals, drag & drop and live updates together. */
import { CollapsibleNav } from "../components/collapsible-nav.js";
import { LanePicker } from "../components/lane-picker.js";
import { Modal } from "../components/modal.js";
import { createTask, deleteTask, listTasks, placeTask, updateTask } from "./api.js";
import { Board } from "./board.js";
import { TaskForm } from "./create-task-form.js";
import { DeleteTaskDialog } from "./delete-task-dialog.js";
import { CardDragController } from "./dnd.js";
import { connectEvents } from "./events.js";

const board = new Board({ loadTasks: listTasks });

// ── Actions ───────────────────────────────────────────────────────────

/**
 * Move a task to another lane and/or to another place in its lane: optimistically, then
 * persisted; rolled back if the server refuses. Resolves to success.
 *
 * @param {object} task
 * @param {{status?: string, beforeId?: string|null, position?: number}} placement
 *   beforeId: place before this task, null = end of the lane, undefined = keep (same lane) or
 *   top (other lane). position: the sort key that matches that placement, for the optimistic view.
 */
async function moveTaskTo(task, { status = task.status, beforeId, position } = {}) {
  const laneChanged = status !== task.status;
  if (!laneChanged && beforeId === undefined) return true;
  const previous = task;
  board.upsert({ ...task, status, position: position ?? board.topPosition(status) });
  board.announce(
    laneChanged
      ? `${task.title} moved to ${board.laneTitle(status)}`
      : `${task.title} moved to position ${[...board.cards.get(task.id).parentElement.children].indexOf(board.cards.get(task.id)) + 1}`,
  );
  try {
    board.upsert(await placeTask(task.id, { status: laneChanged ? status : undefined, beforeId }));
    return true;
  } catch (error) {
    if (error.status === 404) {
      board.remove(task.id); // deleted elsewhere in the meantime
    } else {
      board.upsert(previous);
      board.showError(`Could not move "${task.title}". Please try again.`);
    }
    return false;
  }
}

const taskForm = new TaskForm({
  modal: new Modal(document.getElementById("create-task-modal")),
  createTask,
  updateTask,
  onSaved: (task) => board.upsert(task),
  onGone: (task) => {
    board.remove(task.id);
    board.showError(`"${task.title}" no longer exists.`);
  },
});

const deleteDialog = new DeleteTaskDialog({
  modal: new Modal(document.getElementById("delete-task-modal")),
  deleteTask,
  onDeleted: (task) => {
    board.remove(task.id);
    board.announce(`${task.title} deleted`);
  },
});

new CardDragController({ board, onDrop: (task, placement) => moveTaskTo(task, placement) });

// Right-hand navigation of the task dialog: collapsed by default; for now it only offers Delete.
const cardNavRoot = document.querySelector("[data-card-nav]");
new CollapsibleNav(cardNavRoot, cardNavRoot.querySelector("[data-card-nav-toggle]"), "card-nav", {
  expand: "Expand artifact details",
  collapse: "Collapse artifact details",
});

// Lane switch inside the task dialog. Two entry points: the lane chip under the title (a
// deliberately unadorned "hidden" feature) and the Lane field of the rail. The lane list comes
// from the board, so it follows whatever lanes the page renders.
const lanePicker = new LanePicker({
  container: document.getElementById("create-task-modal"),
  inline: document.querySelector("[data-lane-chips]"),
});
function pickLane(trigger, placement, variant = "list") {
  lanePicker.toggle({
    trigger,
    placement,
    variant,
    current: taskForm.currentStatus(),
    lanes: board.statuses.map((status) => ({
      status,
      title: board.laneTitle(status),
      hue: board.laneHue(status),
    })),
    onSelect: async (status) => {
      const editing = taskForm.editing;
      const previous = taskForm.currentStatus();
      taskForm.setLane(status, board.laneTitle(status), board.laneHue(status));
      if (!editing) return; // new task: only the target lane changes
      const task = board.tasks.get(editing.id) ?? editing;
      const moved = await moveTaskTo(task, { status });
      if (!moved && taskForm.editing?.id === editing.id) {
        taskForm.setLane(previous, board.laneTitle(previous), board.laneHue(previous));
      }
    },
  });
}
taskForm.subtitle.addEventListener("click", (event) => pickLane(event.currentTarget, "below", "chips"));
cardNavRoot
  .querySelector('[data-card-field="lane"]')
  .addEventListener("click", (event) => pickLane(event.currentTarget, "left"));
cardNavRoot.querySelector('[data-card-action="delete"]').addEventListener("click", () => {
  const task = taskForm.editing;
  if (!task || taskForm.busy) return;
  taskForm.modal.close(); // hand over from the editor to the delete confirmation
  deleteDialog.open(task);
});

// ── DOM events ────────────────────────────────────────────────────────

document.querySelectorAll("[data-create-task]").forEach((button) => {
  button.addEventListener("click", () => taskForm.open(button.dataset.status, button.dataset.laneTitle, board.laneHue(button.dataset.status)));
});

const editTask = (task) => taskForm.openEdit(task, board.laneTitle(task.status), board.laneHue(task.status));

board.element.addEventListener("click", (event) => {
  const card = event.target.closest(".task-card");
  const task = board.taskOf(card);
  if (!task) return;
  if (event.target.closest("[data-delete-task]")) deleteDialog.open(task);
  else editTask(task); // click anywhere else on the card opens it for editing
});

/** Keyboard reorder inside the lane: -1 = one place up, +1 = one place down. */
function reorder(task, direction) {
  const card = board.cards.get(task.id);
  const siblings = [...card.parentElement.children];
  const i = siblings.indexOf(card);
  const taskAt = (n) => board.taskOf(siblings[n]);
  if (direction < 0 && i > 0) {
    return moveTaskTo(task, {
      beforeId: siblings[i - 1].dataset.taskId,
      position: Board.positionBetween(taskAt(i - 2), taskAt(i - 1)),
    });
  }
  if (direction > 0 && i < siblings.length - 1) {
    return moveTaskTo(task, {
      beforeId: siblings[i + 2]?.dataset.taskId ?? null,
      position: Board.positionBetween(taskAt(i + 1), taskAt(i + 2)),
    });
  }
  return Promise.resolve(true);
}

// Keyboard: Enter opens the focused card, Alt+←/→ moves it to another lane, Alt+↑/↓ reorders it
// inside its lane, Delete removes it.
board.element.addEventListener("keydown", (event) => {
  const card = event.target.closest(".task-card");
  if (!card || event.target !== card) return;
  const task = board.taskOf(card);
  if (!task) return;

  if (event.key === "Delete") {
    event.preventDefault();
    deleteDialog.open(task);
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    editTask(task);
  } else if (event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    const index = board.statuses.indexOf(task.status) + (event.key === "ArrowLeft" ? -1 : 1);
    const status = board.statuses[index];
    if (status) moveTaskTo(task, { status }).then(() => board.cards.get(task.id)?.focus());
  } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
    event.preventDefault();
    reorder(task, event.key === "ArrowUp" ? -1 : 1).then(() => board.cards.get(task.id)?.focus());
  }
});

// ── Live updates ──────────────────────────────────────────────────────

connectEvents({
  onOpen: () => board.load(), // first connect and every reconnect: resync
  onEvent: (type, data) => {
    if (type === "task.deleted") board.remove(data.id);
    else if (type === "board.resync") board.load(); // lane was renumbered: positions changed
    else board.upsert(data); // task.created / task.updated / task.moved
  },
});

board.load(); // do not depend on the event stream for the first paint
