/* The list of pipelines or action definitions: create, rename, delete, open. */
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { createGraph, deleteGraph, listGraphs, renameGraph } from "./api.js";

const listEl = document.querySelector("[data-wf-list]");
const emptyEl = document.querySelector("[data-wf-empty]");
const errorEl = document.querySelector("[data-list-error]");
const { kind, path } = listEl.dataset;
const noun = kind === "action" ? "action" : "pipeline";
const template = document.getElementById("wf-item-template");

const nameModal = new Modal(document.getElementById("name-modal"));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const form = document.getElementById("name-form");
const input = document.getElementById("graph-name");
const fieldError = document.getElementById("graph-name-error");
const formError = nameModal.dialog.querySelector("[data-form-error]");
const heading = nameModal.dialog.querySelector(".modal__title");

let items = [];
let onName = null; // what to do with the entered name

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function render() {
  listEl.replaceChildren(
    ...items.map((graph) => {
      const item = template.content.firstElementChild.cloneNode(true);
      const link = item.querySelector("a");
      link.href = `${path}/${encodeURIComponent(graph.slug)}`;
      item.querySelector(".wf-item__name").textContent = graph.name;
      item.querySelector(".wf-item__meta").textContent = `Changed ${when(graph.updated_at)}`;
      item.querySelector("[data-rename]").addEventListener("click", () => askName(`Rename ${noun}`, graph.name, async (name) => {
        await renameGraph(kind, graph.id, name);
        await load();
      }));
      item.querySelector("[data-delete]").addEventListener("click", () =>
        confirm.open({
          message: kind === "action" ? `Delete "${graph.name}"? This cannot be undone.` : `Delete "${graph.name}" with all its stages and actions? This cannot be undone.`,
          onConfirm: async () => {
            await deleteGraph(kind, graph.id);
            try {
              const last = JSON.parse(localStorage.getItem("oa-last-pipeline"));
              if (last?.slug === graph.slug) localStorage.removeItem("oa-last-pipeline");
            } catch {
              /* nothing remembered */
            }
            await load();
          },
        }),
      );
      return item;
    }),
  );
  emptyEl.hidden = items.length > 0;
}

async function load() {
  try {
    items = await listGraphs(kind);
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

document.querySelector("[data-new-graph]").addEventListener("click", () =>
  askName(`New ${noun}`, "", async (name) => {
    const created = await createGraph(kind, name);
    window.location.assign(`${path}/${encodeURIComponent(created.slug)}`);
  }),
);
document.querySelector("[data-list-retry]").addEventListener("click", load);

load();
