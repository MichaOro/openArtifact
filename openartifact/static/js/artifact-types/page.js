/* The artifact types page: the list (create, rename, delete) and the editor of a type's parameters. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { createType, deleteType, listTypes, replaceType } from "./api.js";
import { FieldsEditor } from "./fields-editor.js";
import { summary } from "./model.js";

const listEl = document.querySelector("[data-type-list]");
const emptyEl = document.querySelector("[data-type-empty]");
const template = document.getElementById("type-item-template");

const banner = new AlertBar();
const nameDialog = new FormDialog(new Modal(document.getElementById("name-modal")));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const editor = new FieldsEditor(new Modal(document.getElementById("fields-modal")), replaceType, () => load());

let types = [];

function render() {
  listEl.replaceChildren(
    ...types.map((type) => {
      const item = template.content.firstElementChild.cloneNode(true);
      item.dataset.typeId = type.id;
      item.querySelector(".ge-item__name").textContent = type.name;
      item.querySelector(".ge-item__meta").textContent = summary(type);
      item.querySelector(".at-item__fields").textContent = type.fields.map((f) => f.label).join(" · ");
      const used = type.artifact_count;
      const hint = item.querySelector(".at-item__hint");
      const remove = item.querySelector("[data-delete]");
      if (used) {
        hint.textContent = `${used} artifact${used === 1 ? " uses" : "s use"} this type: change or delete ${used === 1 ? "it" : "them"} to delete the type.`;
        hint.hidden = false;
        hint.id = `type-hint-${type.id}`;
        remove.setAttribute("aria-disabled", "true");
        remove.setAttribute("aria-describedby", hint.id);
        remove.title = "In use: cannot be deleted";
      }
      item.querySelector("[data-edit-fields]").addEventListener("click", () => editor.open(type));
      item.querySelector("[data-rename]").addEventListener("click", () =>
        nameDialog.open({
          title: "Rename artifact type",
          values: { name: type.name },
          submitLabel: "Save",
          onSubmit: async ({ name }) => {
            await replaceType(type.id, { name, fields: type.fields });
            await load();
          },
        }),
      );
      remove.addEventListener("click", () => {
        if (used) return;
        confirm.open({
          message: `Delete the artifact type "${type.name}" with its ${type.fields.length} parameter${type.fields.length === 1 ? "" : "s"}? This cannot be undone.`,
          onConfirm: async () => {
            await deleteType(type.id);
            await load();
          },
        });
      });
      return item;
    }),
  );
  emptyEl.hidden = types.length > 0;
}

async function load() {
  try {
    types = await listTypes();
    banner.hide();
    render();
  } catch {
    banner.show("Artifact types could not be loaded.", { retry: true });
  }
}

document.querySelector("[data-new-type]").addEventListener("click", () =>
  nameDialog.open({
    title: "New artifact type",
    onSubmit: async ({ name }) => {
      const created = await createType({ name, fields: [] });
      await load();
      setTimeout(() => editor.open(created), 0); // once this dialog has closed
    },
  }),
);
banner.onRetry(load);

let refresh = 0;
connectEvents({
  onClosed: () => {},
  onOpen: () => load(),
  onEvent: (type) => {
    // the number of artifacts of a type changes with the artifacts; do not reload under an open editor
    if (editor.modal.isOpen) return;
    if (type === "artifact_types.changed" || (type.startsWith("task.") && type !== "task.moved")) {
      clearTimeout(refresh);
      refresh = setTimeout(load, 150);
    }
  },
});
