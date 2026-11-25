/* The list of pipelines or action definitions: create, rename, delete, open. Actions are in two lists, the ones for pipelines and the
 * ones for guards (ADR-067); the window that makes or changes an action is a form manifest (ui/forms/action.yaml, ADR-065). */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { ManifestDialog } from "../components/manifest-dialog.js";
import { Modal } from "../components/modal.js";
import { Tabs } from "../components/tabs.js";
import { KEYS, readJson, removeStorage } from "../storage.js";
import { createGraph, deleteGraph, listGraphs, renameGraph, updateGraph } from "./api.js";
import { t } from "../i18n.js";

const lists = [...document.querySelectorAll("[data-ge-list]")];
const { kind, path } = lists[0].dataset;
const noun = kind === "action" ? "action" : "pipeline";
const template = document.getElementById("ge-item-template");

const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const nameDialog = kind === "action" ? null : new FormDialog(new Modal(document.getElementById("name-modal")));
const actionDialog = kind === "action" ? new ManifestDialog(new Modal(document.getElementById("action-modal")), { form: "action", confirm: (options) => confirm.open(options) }) : null;
// the tab that is open says what a new action is for (an action for pipelines or one for guards)
let purpose = "pipeline";
if (kind === "action") new Tabs(document.querySelector("[data-ge-tabs]"), (name) => (purpose = name));

let items = [];

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** The sidebar's "Pipeline" must not reopen a pipeline that is gone. */
function forget(slug) {
  if (readJson(KEYS.lastPipeline)?.slug === slug) removeStorage(KEYS.lastPipeline);
}

/** The window that makes (graph null) or changes an action: its name and what it is for. */
function openAction(graph) {
  actionDialog.open({
    title: graph ? t("editor.list.edit_action") : purpose === "guard" ? t("editor.list.new_guard_action") : t("editor.list.new_noun", { noun }),
    values: { name: graph?.name ?? "", purpose: graph?.purpose ?? purpose },
    submitLabel: graph ? t("common.save") : t("common.create"),
    onSubmit: async ({ name, purpose: chosen }) => {
      if (!graph) {
        const created = await createGraph(kind, String(name).trim(), chosen);
        window.location.assign(`${path}/${encodeURIComponent(created.slug)}`);
        return;
      }
      await updateGraph(kind, graph.id, { name: String(name).trim(), purpose: chosen });
      await load();
    },
  });
}

function render() {
  for (const listEl of lists) {
    const shown = kind === "action" ? items.filter((graph) => graph.purpose === listEl.dataset.purpose) : items;
    listEl.replaceChildren(
      ...shown.map((graph) => {
        const item = template.content.firstElementChild.cloneNode(true);
        item.querySelector("a").href = `${path}/${encodeURIComponent(graph.slug)}`;
        item.querySelector(".ge-item__name").textContent = graph.name;
        item.querySelector(".ge-item__meta").textContent = t("editor.list.changed_when", { when: when(graph.updated_at) });
        item.querySelector("[data-guard-chip]").hidden = graph.purpose !== "guard";
        item.querySelector("[data-rename]").addEventListener("click", () =>
          kind === "action"
            ? openAction(graph)
            : nameDialog.open({
                title: t("editor.list.rename_noun", { noun }),
                values: { name: graph.name },
                submitLabel: t("common.save"),
                onSubmit: async ({ name }) => {
                  await renameGraph(kind, graph.id, name);
                  await load();
                },
              }),
        );
        item.querySelector("[data-delete]").addEventListener("click", () =>
          confirm.open({
            message: kind === "action" ? t("editor.list.delete_name_cannot_be_undone", { name: graph.name }) : t("editor.list.delete_name_with_all_its", { name: graph.name }),
            onConfirm: async () => {
              await deleteGraph(kind, graph.id);
              forget(graph.slug);
              await load();
            },
          }),
        );
        return item;
      }),
    );
    document.querySelector(`[data-ge-empty]${kind === "action" ? `[data-purpose="${listEl.dataset.purpose}"]` : ""}`).hidden = shown.length > 0;
  }
}

async function load() {
  try {
    items = await listGraphs(kind);
    banner.hide();
    render();
  } catch {
    banner.show(t(`graph.${noun}.load_error`), { retry: true });
  }
}

document.querySelector("[data-new-graph]").addEventListener("click", () =>
  kind === "action"
    ? openAction(null)
    : nameDialog.open({
        title: t("editor.list.new_noun", { noun }),
        onSubmit: async ({ name }) => {
          const created = await createGraph(kind, name);
          window.location.assign(`${path}/${encodeURIComponent(created.slug)}`);
        },
      }),
);
banner.onRetry(load);

load();
