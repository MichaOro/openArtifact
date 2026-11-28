/* Entry point: wires board, modals, drag & drop and live updates together. */
import { CollapsibleNav } from "../components/collapsible-nav.js";
import { LanePicker } from "../components/lane-picker.js";
import { Modal } from "../components/modal.js";
import { ReferencePicker } from "../components/reference-picker.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { KEYS } from "../storage.js";
import { archiveTask, createTask, deleteTask, getTask, listRuns, listTasks, placeTask, updateTask } from "./api.js";
import { needsFullBody } from "./body-model.js";
import { Board } from "./board.js";
import { ArtifactDialog } from "./artifact-dialog.js";
import { CardDragController } from "./dnd.js";
import { ProcessingPanel } from "./processing.js";
import { connectEvents } from "./events.js";
import { CommentsTab } from "./comments-tab.js";
import { HistoryTab } from "./history-tab.js";
import { FormDialog } from "../components/form-dialog.js";
import { LaneControls, listLanes, reorderLanes } from "./lanes.js";
import { LaneReorder } from "./lane-order.js";
import { CardRulesDialog } from "./card-rules-dialog.js";
import { listFields, replaceFields } from "../artifact-fields/api.js";
import { FieldsEditor } from "../artifact-fields/fields-editor.js";
import { ActionMenu } from "../components/action-menu.js";
import { FieldRail } from "./field-rail.js";
import { ArchiveView } from "./archive-view.js";
import { BoardSearch } from "./board-search.js";
import { t, tn } from "../i18n.js";

const board = new Board({ loadTasks: listTasks, renameLane: (status, title) => laneControls.rename(status, title) });
const search = new BoardSearch({ board, root: document.querySelector("[data-board-search-box]") }); // the title and number of a card, never its body (ADR-091)

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
      ? t("tasks.main.title_moved_lanetitle", { title: task.title, laneTitle: board.laneTitle(status) })
      : t("tasks.main.moved_to_position", { title: task.title, position: [...board.cards.get(task.id).parentElement.children].indexOf(board.cards.get(task.id)) + 1 }),
  );
  try {
    board.upsert(await placeTask(task.id, { status: laneChanged ? status : undefined, beforeId }));
    return true;
  } catch (error) {
    if (error.status === 404) {
      board.remove(task.id); // deleted elsewhere in the meantime
    } else {
      board.upsert(previous);
      board.showError(t("tasks.main.could_not_move_title_please", { title: task.title }));
    }
    return false;
  }
}

const laneControls = new LaneControls({
  board,
  addDialog: new FormDialog(new Modal(document.getElementById("add-lane-modal"))),
  confirm: new ConfirmDialog(new Modal(document.getElementById("delete-lane-modal"))),
  settings: new CardRulesDialog(new Modal(document.getElementById("card-rules-modal")), { onSaved: () => board.load() }),
  onLanes: (lanes) => showLanes(lanes),
});

/** Show the lanes everywhere: board, and the open artifact dialog's lane chip and rail. */
function showLanes(lanes) {
  board.setLanes(lanes);
  if (artifactDialog.modal.isOpen) {
    const status = artifactDialog.currentStatus();
    artifactDialog.setLane(status, board.laneTitle(status), board.laneHue(status));
  }
}

const history = new HistoryTab({
  root: document.querySelector("[data-history]"),
  badge: document.querySelector("[data-history-count]"),
  confirm: new ConfirmDialog(new Modal(document.getElementById("delete-execution-modal"))),
  commentOf: (id) => comments.commentOf(id),
  onJump: (id) => {
    artifactDialog.openTab("comments"); // the comment shows itself: expands the list over it, scrolls, pulses
    comments.reveal(id);
  },
});

const comments = new CommentsTab({
  root: document.querySelector("[data-comments]"),
  badge: document.querySelector("[data-comments-count]"),
  confirm: new ConfirmDialog(new Modal(document.getElementById("delete-comment-modal"))),
  onChange: () => history.refresh(), // the History tab shows the first words of a comment, read live
});

const artifactDialog = new ArtifactDialog({
  modal: new Modal(document.getElementById("create-task-modal")),
  createTask: async (payload) => {
    const task = await createTask(payload);
    board.keepVisible(task.id); // a card the user has just made must not vanish behind the search
    return task;
  },
  updateTask,
  onSaved: (task) => board.upsert(task),
  onGone: (task) => {
    board.remove(task.id);
    board.showError(t("tasks.main.title_no_longer_exists", { title: task.title }));
  },
  history,
  comments,
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
  fieldRail.show(task);
  fieldRail.setLocked(board.locked.has(task.id));
  if (needsFullBody(task)) loadFullBody(task.id); // the list carries a preview only; the dialog reads the whole text
}

/** The open dialog gets the body with its references filled in (the board's list holds the first words only). */
async function loadFullBody(id) {
  try {
    const full = await getTask(id);
    if (artifactDialog.editing?.id === id) artifactDialog.refreshView(full);
  } catch {
    // the dialog keeps the body as it was written; the next event or opening tries again
  }
}

/** The artifact fields (ADR-044): the rail of the dialog and the editor behind the board's menu. */
let artifactFields = [];
function showFields(read) {
  artifactFields = read.fields;
  fieldRail.setFields(read.fields);
}

const deleteDialog = new ConfirmDialog(new Modal(document.getElementById("delete-task-modal")));

/** Ask, then delete the artifact; one that is already gone (404) is the outcome the user wanted. */
function confirmDelete(task) {
  const children = board.childCount(task.id);
  deleteDialog.open({
    message: t("executions.page.delete_subject_cannot_be_undone"),
    subject: task.title,
    note: children === 0 ? "" : tn("tasks.main.sub_artifacts", children),
    onConfirm: async () => {
      try {
        await deleteTask(task.id);
      } catch (error) {
        if (error.status !== 404) throw error;
      }
      board.remove(task.id);
      board.announce(t("tasks.main.artifact_deleted", { title: task.title }));
    },
  });
}

new CardDragController({ board, onDrop: (task, placement) => moveTaskTo(task, placement) });

// Right-hand navigation of the task dialog (Lane, Parent, Delete): collapsed by default.
const cardNavRoot = document.querySelector("[data-card-nav]");
const cardNav = new CollapsibleNav(cardNavRoot, cardNavRoot.querySelector("[data-card-nav-toggle]"), KEYS.cardNav, {
  expand: t("create_task.expand_artifact_details"),
  collapse: t("tasks.main.collapse_artifact_details"),
}, () => artifactDialog.refit()); // expanded, the rail needs the height of its labels: the dialog refits
const fieldRail = new FieldRail({
  rail: cardNavRoot,
  nav: cardNav,
  save: (id, values) => updateTask(id, { fields: values }),
  onSaved: (task) => board.upsert(task),
  onLayout: () => artifactDialog.refit(), // the dialog grows with its navigation, as it does with its text
});

// The board's menu next to "Add lane": the artifact fields every artifact has.
const fieldsEditor = new FieldsEditor(new Modal(document.getElementById("fields-modal")), replaceFields, (saved) => showFields(saved));
const boardMenu = new ActionMenu();

// The archive (ADR-071): a view of its own that takes the place of the lanes; the board's menu shows and hides it.
const boardElement = board.element;
const addLaneButton = document.querySelector("[data-add-lane]");
const archive = new ArchiveView({
  root: document.querySelector("[data-archive-view]"),
  fields: () => artifactFields,
  parentTitle: (id) => board.tasks.get(id)?.title ?? null,
  onRestored: (task) => {
    board.upsert(task);
    board.announce(t("archive.restored", { title: task.title }));
  },
  onOpen: (task) => showArchived(task),
  onError: (message) => board.showError(message),
});

/** An archived card in the same window as a card of the board, read only; its rail offers "Remove from archive" (ADR-071). */
async function showArchived(task) {
  processing.show(task.id);
  trail.length = 0;
  artifactDialog.openView(task, task.archived_from_lane ?? "–", board.laneHue(task.archived_from_status), board.parentOf(task)?.title ?? null, false, { readOnly: true });
  fieldRail.show(task);
  fieldRail.setLocked(true);
}
/** Reorder the lanes (ADR-092): the board's menu switches it; a failed save draws the lanes the server has. */
const laneReorder = new LaneReorder({
  board,
  save: reorderLanes,
  onLanes: async (lanes) => showLanes(lanes ?? (await listLanes())),
});
function showArchive(on) {
  if (on) laneReorder.set(false);
  boardElement.hidden = on;
  search.setVisible(!on);
  if (addLaneButton) addLaneButton.hidden = on;
  archive.show(on);
}
document.querySelector("[data-board-menu]")?.addEventListener("click", (event) => {
  boardMenu.toggle(
    event.currentTarget,
    [
      { label: t("index.artifact_fields"), icon: "tag", onSelect: () => fieldsEditor.open(artifactFields) },
      { label: t("common.settings"), icon: "settings", onSelect: () => laneControls.settings.open({ kind: "board" }, board.laneChoices()) },
      { label: laneReorder.on ? t("index.stop_reorder_lanes") : t("index.reorder_lanes"), icon: "grip", onSelect: () => laneReorder.set(!laneReorder.on) },
      { label: archive.visible ? t("index.hide_archive") : t("index.show_archive"), icon: "inbox", onSelect: () => showArchive(!archive.visible) },
    ],
    t("tasks.main.board"),
  );
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
    if (artifactDialog.editing?.id === taskId && !artifactDialog.readOnly) {
      artifactDialog.subtitle.disabled = locked;
      fieldRail.setLocked(locked);
    }
  },
  onError: (message) => board.showError(message),
});
processing.onRun = (taskId, run) => board.setRun(taskId, run);

function pickLane(trigger, placement, variant = "list") {
  lanePicker.toggle({
    trigger,
    placement,
    variant,
    label: t("modal.move_to_lane"),
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
      board.showError(t("tasks.main.parent_change_failed", { title: task.title, why: error.status === 422 ? t("tasks.main.would_create_loop") : t("tasks.main.please_try_again") }));
    }
  }
}
cardNavRoot.querySelector('[data-card-field="parent"]').addEventListener("click", (event) => {
  const editing = artifactDialog.editing;
  const task = editing && board.tasks.get(editing.id);
  if (!task || board.locked.has(task.id)) return;
  const blocked = board.descendantIds(task.id);
  const items = [
    { value: "", label: t("tasks.main.no_parent"), selected: !task.parent_id },
    ...board
      .inBoardOrder()
      .filter((t) => t.id !== task.id && !blocked.has(t.id))
      .map((t) => ({ value: t.id, label: t.title, hue: board.laneHue(t.status), selected: t.id === task.parent_id })),
  ];
  lanePicker.toggle({
    trigger: event.currentTarget,
    items,
    caption: t("tasks.main.parent"),
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
cardNavRoot.querySelector('[data-card-action="archive"]').addEventListener("click", async () => {
  const task = artifactDialog.editing;
  if (!task || artifactDialog.busy || board.locked.has(task.id)) return;
  try {
    await archiveTask(task.id);
    artifactDialog.modal.close();
    board.remove(task.id);
    board.announce(t("tasks.main.archived_title", { title: task.title }));
    if (archive.visible) archive.load();
  } catch (error) {
    if (error.status === 404) board.remove(task.id);
    else board.showError(t("tasks.main.archive_failed", { title: task.title }));
  }
});
cardNavRoot.querySelector('[data-card-action="unarchive"]').addEventListener("click", async () => {
  const task = artifactDialog.editing;
  if (!task || !artifactDialog.readOnly || artifactDialog.busy) return;
  if (await archive.restore(task)) artifactDialog.modal.close();
});
cardNavRoot.querySelector('[data-card-action="delete"]').addEventListener("click", () => {
  const task = artifactDialog.editing;
  if (!task || artifactDialog.busy || board.locked.has(task.id)) return;
  artifactDialog.modal.close(); // hand over from the editor to the delete confirmation
  confirmDelete(task);
});

// ── DOM events ────────────────────────────────────────────────────────

board.element.addEventListener("click", (event) => {
  const button = event.target.closest("[data-create-task]");
  if (button) artifactDialog.openCreate(button.dataset.status, button.dataset.laneTitle, board.laneHue(button.dataset.status));
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

/** Keyboard reorder inside the lane: -1 = one place up, +1 = one place down. A card the board search hides is not a place: the card passes the next
 * VISIBLE one, and its position is taken between the neighbours in the whole lane so the order stays right for the hidden ones. */
function reorder(task, direction) {
  const card = board.cards.get(task.id);
  const siblings = [...card.parentElement.children];
  const i = siblings.indexOf(card);
  const taskAt = (n) => board.taskOf(siblings[n]);
  const visible = (n) => siblings[n] && !siblings[n].hidden;
  if (direction < 0) {
    let up = i - 1;
    while (up >= 0 && !visible(up)) up -= 1;
    if (up < 0) return Promise.resolve(true);
    return moveTaskTo(task, { beforeId: siblings[up].dataset.taskId, position: Board.positionBetween(taskAt(up - 1), taskAt(up)) });
  }
  let down = i + 1;
  while (down < siblings.length && !visible(down)) down += 1;
  if (down >= siblings.length) return Promise.resolve(true);
  return moveTaskTo(task, {
    beforeId: siblings[down + 1]?.dataset.taskId ?? null,
    position: Board.positionBetween(taskAt(down), taskAt(down + 1)),
  });
}

// Keyboard: Enter opens the focused card, Alt+←/→ moves it to another lane, Alt+↑/↓ reorders it
// inside its lane, Delete removes it.
board.element.addEventListener("keydown", (event) => {
  const card = event.target.closest(".task-card");
  if (!card || event.target !== card) return;
  const task = board.taskOf(card);
  if (!task) return;

  if (board.locked.has(task.id) && event.key !== "Enter" && event.key !== " ") return; // being processed
  if (board.reordering && event.altKey) return; // the lanes are being reordered: a card is not moved (ADR-092)
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
    board.showError(t("execution.flow_page.live_updates_stopped_reload_page"), { sticky: true });
  },
  onOpen: () => {
    board.load(); // first connect and every reconnect: resync
    listLanes().then(showLanes).catch(() => {});
    listFields().then(showFields).catch(() => {});
    listRuns().then((runs) => processing.setRuns(runs)).catch(() => {});
    history.load(); // missed events are not replayed
    comments.load();
  },
  onEvent: (type, data) => {
    archive.handleEvent(type);
    if ((type === "task.updated" || type === "task.moved" || type === "task.created") && data.archived_at) {
      board.remove(data.id); // an archived card is not on the board
      if (artifactDialog.editing?.id === data.id && !artifactDialog.readOnly) artifactDialog.modal.close(); // the read-only window is where an archived card is looked at
    } else if (type === "run.updated") processing.upsert(data);
    else if (type.startsWith("execution.") || type === "activity.created") history.handleEvent(type, data);
    else if (type.startsWith("comment.")) {
      comments.handleEvent(type, data);
      if (type === "comment.deleted") history.handleEvent(type, data); // its entry in the timeline becomes "deleted a comment"
    } else if (type === "task.deleted") {
      if (artifactDialog.readOnly && artifactDialog.editing?.id === data.id) artifactDialog.modal.close();
      board.remove(data.id);
      processing.remove(data.id);
    }
    else if (type === "board.lanes") showLanes(data.lanes);
    else if (type === "artifact_fields.changed") {
      showFields(data);
      board.load(); // the first words of a card come from its fields
      const open = artifactDialog.editing;
      if (open && artifactDialog.mode === "view") loadFullBody(open.id); // a referenced field changed
    }
    else if (type === "board.resync") board.load(); // positions changed, or the rules: marks, archived and deleted cards (board.updated and cards.rules.changed are always followed by it: one load)
    else if (type === "settings.changed") {
      if (data.personal) {
        board.load(); // marked or not: the server sends the cards the other way now
        const open = artifactDialog.editing;
        if (open && artifactDialog.mode === "view") loadFullBody(open.id);
      }
    }
    else {
      if (artifactDialog.readOnly && artifactDialog.editing?.id === data.id) artifactDialog.modal.close(); // it left the archive (here or elsewhere)
      board.upsert(data); // task.created / task.updated / task.moved
      artifactDialog.refreshView(data);
      if (artifactDialog.mode === "view" && artifactDialog.editing?.id === data.id) fieldRail.show(data);
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
