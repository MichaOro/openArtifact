/* The workflow list: create, rename, delete, open. */
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { createWorkflow, deleteWorkflow, listWorkflows, renameWorkflow } from "./api.js";

const listEl = document.querySelector("[data-wf-list]");
const emptyEl = document.querySelector("[data-wf-empty]");
const errorEl = document.querySelector("[data-list-error]");
const template = document.getElementById("wf-item-template");

const nameModal = new Modal(document.getElementById("name-modal"));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const form = document.getElementById("name-form");
const input = document.getElementById("workflow-name");
const fieldError = document.getElementById("workflow-name-error");
const formError = nameModal.dialog.querySelector("[data-form-error]");
const heading = nameModal.dialog.querySelector(".modal__title");

let workflows = [];
let onName = null; // what to do with the entered name

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function render() {
  listEl.replaceChildren(
    ...workflows.map((workflow) => {
      const item = template.content.firstElementChild.cloneNode(true);
      const link = item.querySelector("a");
      link.href = `/workflows/${encodeURIComponent(workflow.id)}`;
      item.querySelector(".wf-item__name").textContent = workflow.name;
      item.querySelector(".wf-item__meta").textContent = `Changed ${when(workflow.updated_at)}`;
      item.querySelector("[data-rename]").addEventListener("click", () => askName("Rename workflow", workflow.name, async (name) => {
        await renameWorkflow(workflow.id, name);
        await load();
      }));
      item.querySelector("[data-delete]").addEventListener("click", () =>
        confirm.open({
          message: `Delete "${workflow.name}" with all its stages and actions? This cannot be undone.`,
          onConfirm: async () => {
            await deleteWorkflow(workflow.id);
            await load();
          },
        }),
      );
      return item;
    }),
  );
  emptyEl.hidden = workflows.length > 0;
}

async function load() {
  try {
    workflows = await listWorkflows();
    errorEl.hidden = true;
    render();
  } catch {
    errorEl.hidden = false;
  }
}

function askName(title, value, action) {
  heading.textContent = title;
  input.value = value;
  fieldError.hidden = true;
  formError.hidden = true;
  onName = action;
  nameModal.open();
  input.select();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = input.value.trim();
  if (!name) {
    fieldError.textContent = "Please enter a name.";
    fieldError.hidden = false;
    input.focus();
    return;
  }
  try {
    await onName(name);
    nameModal.close();
  } catch (error) {
    formError.textContent = error.message || "Could not save. Please try again.";
    formError.hidden = false;
  }
});
input.addEventListener("input", () => (fieldError.hidden = true));

document.querySelector("[data-new-workflow]").addEventListener("click", () =>
  askName("New workflow", "", async (name) => {
    const created = await createWorkflow(name);
    window.location.assign(`/workflows/${encodeURIComponent(created.id)}`);
  }),
);
document.querySelector("[data-list-retry]").addEventListener("click", load);

load();
