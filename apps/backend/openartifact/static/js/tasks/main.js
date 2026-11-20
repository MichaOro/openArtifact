/* Entry point: wires board, modals, drag & drop and live updates together. */
import { CollapsibleNav } from "../components/collapsible-nav.js";
import { LanePicker } from "../components/lane-picker.js";
import { Modal } from "../components/modal.js";
import { createTask, deleteTask, listTasks, moveTask, updateTask } from "./api.js";
import { Board } from "./board.js";
import { TaskForm } from "./create-task-form.js";
import { DeleteTaskDialog } from "./delete-task-dialog.js";
import { CardDragController } from "./dnd.js";
import { connectEvents } from "./events.js";

const board = new Board({ loadTasks: listTasks });

// ── Actions ───────────────────────────────────────────────────────────

/** Move optimistically, then persist; roll back if the server refuses. Resolves to success. */
async function moveTaskTo(task, status) {
  if (task.status === status) return true;
  const previous = task;
  board.upsert({ ...task, status });
  board.announce(`${task.title} moved to ${board.laneTitle(status)}`);
  try {
    board.upsert(await moveTask(task.id, status));
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

new CardDragController({ board, onDrop: moveTaskTo });

// Right-hand navigation of the task dialog: collapsed by default; for now it only offers Delete.
const cardNavRoot = document.querySelector("[data-card-nav]");
new CollapsibleNav(cardNavRoot, cardNavRoot.querySelector("[data-card-nav-toggle]"), "card-nav", {
  expand: "Expand task details",
  collapse: "Collapse task details",
});

// Lane switch inside the task dialog. Two entry points: the lane chip under the title (a
// deliberately unadorned "hidden" feature) and the Lane field of the rail. The lane list comes
// from the board, so it follows whatever lanes the page renders.
const lanePicker = new LanePicker({ container: document.getElementById("create-task-modal") });
function pickLane(trigger, placement) {
  lanePicker.toggle({
    trigger,
    placement,
    current: taskForm.currentStatus(),
    lanes: board.statuses.map((status) => ({ status, title: board.laneTitle(status) })),
    onSelect: async (status) => {
      const editing = taskForm.editing;
      const previous = taskForm.currentStatus();
      taskForm.setLane(status, board.laneTitle(status));
      if (!editing) return; // new task: only the target lane changes
      const task = board.tasks.get(editing.id) ?? editing;
      const moved = await moveTaskTo(task, status);
      if (!moved && taskForm.editing?.id === editing.id) taskForm.setLane(previous, board.laneTitle(previous));
    },
  });
}
taskForm.subtitle.addEventListener("click", (event) => pickLane(event.currentTarget, "below"));
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
  button.addEventListener("click", () => taskForm.open(button.dataset.status, button.dataset.laneTitle));
});

const editTask = (task) => taskForm.openEdit(task, board.laneTitle(task.status));

board.element.addEventListener("click", (event) => {
  const card = event.target.closest(".task-card");
  const task = board.taskOf(card);
  if (!task) return;
  if (event.target.closest("[data-delete-task]")) deleteDialog.open(task);
  else editTask(task); // click anywhere else on the card opens it for editing
});

// Keyboard: Enter opens the focused card, Alt+←/→ moves it, Delete removes it.
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
    if (status) moveTaskTo(task, status).then(() => board.cards.get(task.id)?.focus());
  }
});

// ── Live updates ──────────────────────────────────────────────────────

connectEvents({
  onOpen: () => board.load(), // first connect and every reconnect: resync
  onEvent: (type, data) => {
    if (type === "task.deleted") board.remove(data.id);
    else board.upsert(data); // task.created / task.updated / task.moved
  },
});

board.load(); // do not depend on the event stream for the first paint
