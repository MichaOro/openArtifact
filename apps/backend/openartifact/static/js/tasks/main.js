/* Entry point: wires the board, the generic modal and the create-task form. */
import { Modal } from "../components/modal.js";
import { createTask, listTasks } from "./api.js";
import { Board } from "./board.js";
import { CreateTaskForm } from "./create-task-form.js";

const dialog = document.getElementById("create-task-modal");

const board = new Board({ loadTasks: listTasks });
const form = new CreateTaskForm({
  modal: new Modal(dialog),
  createTask,
  onCreated: (task) => board.add(task),
});

document.querySelectorAll("[data-create-task]").forEach((button) => {
  button.addEventListener("click", () => form.open(button.dataset.status, button.dataset.laneTitle));
});

board.load();
