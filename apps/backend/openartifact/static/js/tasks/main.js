/* Entry point: wires board, modals, drag & drop and live updates together. */
import { CollapsibleNav } from "../components/collapsible-nav.js";
import { LanePicker } from "../components/lane-picker.js";
import { Modal } from "../components/modal.js";
import { ReferencePicker } from "../components/reference-picker.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { KEYS } from "../storage.js";
import { createTask, deleteTask, listRuns, listTasks, placeTask, updateTask } from "./api.js";
import { Board } from "./board.js";
import { ArtifactDialog } from "./artifact-dialog.js";
import { CardDragController } from "./dnd.js";
import { ProcessingPanel } from "./processing.js";
import { connectEvents } from "./events.js";
import { HistoryTab } from "./history-tab.js";

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
  if (board.locked.has(task.id)) return false;
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

const history = new HistoryTab({
  root: document.querySelector("[data-history]"),
  badge: document.querySelector("[data-history-count]"),
  confirm: new ConfirmDialog(new Modal(document.getElementById("delete-execution-modal"))),
});

const artifactDialog = new ArtifactDialog({
  modal: new Modal(document.getElementById("create-task-modal")),
  createTask,
  updateTask,
  onSaved: (task) => board.upsert(task),
  onGone: (task) => {
    board.remove(task.id);
    board.showError(`"${task.title}" no longer exists.`);
  },
  history,
  findByNumber: (number) => board.byNumber(number),
  onReference: (number) => {
    const target = board.byNumber(number);
    if (target) showTask(target, { follow: true });
  },
  onBack: () => {
    const id = trail.pop();
    const previous = id && board.tasks.get(id);
    if (previous) showTask(previous);
    else artifactDialog.modal.close();
  },
});

/** Ids of the artifacts left by following references, so "Back" can return to them. */
const trail = [];
function showTask(task, { follow = false } = {}) {
  processing.show(task.id);
  if (follow && artifactDialog.editing) trail.push(artifactDialog.editing.id);
  else if (!follow && !artifactDialog.modal.isOpen) trail.length = 0;
  artifactDialog.openView(
    task,
    board.laneTitle(task.status),
    board.laneHue(task.status),
    board.parentOf(task)?.title ?? null,
    trail.length > 0,
  );
  artifactDialog.subtitle.disabled = board.locked.has(task.id);
}

const deleteDialog = new ConfirmDialog(new Modal(document.getElementById("delete-task-modal")));

/** Ask, then delete the artifact; one that is already gone (404) is the outcome the user wanted. */
function confirmDelete(task) {
  const children = board.childCount(task.id);
  deleteDialog.open({
    message: "Delete {subject}? This cannot be undone.",
    subject: task.title,
    note: children === 0 ? "" : `Its ${children} sub-artifact${children === 1 ? "" : "s"} will lose their parent but are not deleted.`,
    onConfirm: async () => {
      try {
        await deleteTask(task.id);
      } catch (error) {
        if (error.status !== 404) throw error;
      }
      board.remove(task.id);
      board.announce(`${task.title} deleted`);
    },
  });
}

new CardDragController({ board, onDrop: (task, placement) => moveTaskTo(task, placement) });

// Right-hand navigation of the task dialog (Lane, Parent, Delete): collapsed by default.
const cardNavRoot = document.querySelector("[data-card-nav]");
new CollapsibleNav(cardNavRoot, cardNavRoot.querySelector("[data-card-nav-toggle]"), KEYS.cardNav, {
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
// Pipeline / Stage / Action and Start / Stop in the rail; runs lock the artifact while they run.
const processing = new ProcessingPanel({
  rail: cardNavRoot,
  button: document.querySelector('[data-card-action="run"]'),
  picker: lanePicker,
  onLock: (taskId, locked) => {
    board.setLocked(taskId, locked);
    if (artifactDialog.editing?.id === taskId) artifactDialog.subtitle.disabled = locked;
  },
  onError: (message) => board.showError(message),
});
processing.onRun = (taskId, run) => board.setRun(taskId, run);

function pickLane(trigger, placement, variant = "list") {
  lanePicker.toggle({
    trigger,
    placement,
    variant,
    label: "Move to lane",
    current: artifactDialog.currentStatus(),
    lanes: board.statuses.map((status) => ({
      status,
      title: board.laneTitle(status),
      hue: board.laneHue(status),
    })),
    onSelect: async (status) => {
      const editing = artifactDialog.editing;
      const previous = artifactDialog.currentStatus();
      artifactDialog.setLane(status, board.laneTitle(status), board.laneHue(status));
      if (!editing) return; // new task: only the target lane changes
      const task = board.tasks.get(editing.id) ?? editing;
      const moved = await moveTaskTo(task, { status });
      if (!moved && artifactDialog.editing?.id === editing.id) {
        artifactDialog.setLane(previous, board.laneTitle(previous), board.laneHue(previous));
      }
    },
  });
}
// "#" in the body offers the artifacts of the board (not the one being edited).
new ReferencePicker({
  textarea: artifactDialog.bodyInput,
  container: document.getElementById("create-task-modal"),
  getItems: () =>
    board
      .inBoardOrder()
      .filter((t) => t.id !== artifactDialog.editing?.id)
      .map((t) => ({ number: t.number, title: t.title, hue: board.laneHue(t.status) })),
});

// Parent: any other artifact except the task itself and everything below it (no cycles).
async function setParent(id, parentId) {
  const task = board.tasks.get(id);
  if (!task || board.locked.has(id) || (task.parent_id ?? null) === parentId) return;
  const previous = task;
  board.upsert({ ...task, parent_id: parentId });
  artifactDialog.setParent(board.parentOf(board.tasks.get(id))?.title ?? null);
  try {
    board.upsert(await updateTask(id, { parent_id: parentId }));
  } catch (error) {
    if (error.status === 404) {
      board.remove(id);
    } else {
      board.upsert(previous);
      artifactDialog.setParent(board.parentOf(previous)?.title ?? null);
      board.showError(`Could not change the parent of "${task.title}": ${error.status === 422 ? "that would create a loop." : "please try again."}`);
    }
  }
}
cardNavRoot.querySelector('[data-card-field="parent"]').addEventListener("click", (event) => {
  const editing = artifactDialog.editing;
  const task = editing && board.tasks.get(editing.id);
  if (!task || board.locked.has(task.id)) return;
  const blocked = board.descendantIds(task.id);
  const items = [
    { value: "", label: "No parent", selected: !task.parent_id },
    ...board
      .inBoardOrder()
      .filter((t) => t.id !== task.id && !blocked.has(t.id))
      .map((t) => ({ value: t.id, label: t.title, hue: board.laneHue(t.status), selected: t.id === task.parent_id })),
  ];
  lanePicker.toggle({
    trigger: event.currentTarget,
    items,
    caption: "Parent",
    placement: "left",
    onSelect: (value) => setParent(task.id, value || null),
  });
});
artifactDialog.subtitle.addEventListener("click", (event) => {
  if (!board.locked.has(artifactDialog.editing?.id)) pickLane(event.currentTarget, "below", "chips");
});
cardNavRoot.querySelector('[data-card-field="lane"]').addEventListener("click", (event) => {
  if (!board.locked.has(artifactDialog.editing?.id)) pickLane(event.currentTarget, "left");
});
cardNavRoot.querySelector('[data-card-action="delete"]').addEventListener("click", () => {
  const task = artifactDialog.editing;
  if (!task || artifactDialog.busy || board.locked.has(task.id)) return;
  artifactDialog.modal.close(); // hand over from the editor to the delete confirmation
  confirmDelete(task);
});

// ── DOM events ────────────────────────────────────────────────────────

document.querySelectorAll("[data-create-task]").forEach((button) => {
  button.addEventListener("click", () => artifactDialog.openCreate(button.dataset.status, button.dataset.laneTitle, board.laneHue(button.dataset.status)));
});

board.element.addEventListener("click", (event) => {
  const card = event.target.closest(".task-card");
  const task = board.taskOf(card);
  if (!task) return;
  if (event.target.closest("[data-delete-task]")) {
    if (!board.locked.has(task.id)) confirmDelete(task);
  }
  else showTask(task); // click anywhere else on the card opens it
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

  if (board.locked.has(task.id) && event.key !== "Enter" && event.key !== " ") return; // being processed
  if (event.key === "Delete") {
    event.preventDefault();
    confirmDelete(task);
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    showTask(task);
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
  onClosed: () => {
    // The stream is refused for good, e.g. the sign-in expired: any request then goes to the sign-in page.
    listTasks().catch(() => {});
    board.showError("Live updates stopped. Reload the page or sign in again.", { sticky: true });
  },
  onOpen: () => {
    board.load(); // first connect and every reconnect: resync
    listRuns().then((runs) => processing.setRuns(runs)).catch(() => {});
    history.load(); // missed events are not replayed
  },
  onEvent: (type, data) => {
    if (type === "run.updated") processing.upsert(data);
    else if (type.startsWith("execution.")) history.handleEvent(type, data);
    else if (type === "task.deleted") {
      board.remove(data.id);
      processing.remove(data.id);
    }
    else if (type === "board.resync") board.load(); // lane was renumbered: positions changed
    else {
      board.upsert(data); // task.created / task.updated / task.moved
      artifactDialog.refreshView(data);
    }
  },
});

// `/?artifact=12` opens that artifact once the board has loaded (the global execution list links here).
const wanted = new URLSearchParams(window.location.search).get("artifact");
board.load().then(() => {
  // do not depend on the event stream for the first paint
  const task = wanted && [...board.tasks.values()].find((t) => String(t.number) === wanted.replace(/^#/, ""));
  if (task) showTask(task);
});
