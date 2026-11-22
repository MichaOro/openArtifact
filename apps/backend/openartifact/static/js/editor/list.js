/* The list of pipelines or action definitions: create, rename, delete, open. */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { NameDialog } from "../components/name-dialog.js";
import { KEYS, readJson, removeStorage } from "../storage.js";
import { createGraph, deleteGraph, listGraphs, renameGraph } from "./api.js";

const listEl = document.querySelector("[data-ge-list]");
const emptyEl = document.querySelector("[data-ge-empty]");
const { kind, path } = listEl.dataset;
const noun = kind === "action" ? "action" : "pipeline";
const template = document.getElementById("ge-item-template");

const banner = new AlertBar();
const nameDialog = new NameDialog(document.getElementById("name-modal"));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));

let items = [];

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** The sidebar's "Pipeline" must not reopen a pipeline that is gone. */
function forget(slug) {
  if (readJson(KEYS.lastPipeline)?.slug === slug) removeStorage(KEYS.lastPipeline);
}

function render() {
  listEl.replaceChildren(
    ...items.map((graph) => {
      const item = template.content.firstElementChild.cloneNode(true);
      item.querySelector("a").href = `${path}/${encodeURIComponent(graph.slug)}`;
      item.querySelector(".ge-item__name").textContent = graph.name;
      item.querySelector(".ge-item__meta").textContent = `Changed ${when(graph.updated_at)}`;
      item.querySelector("[data-rename]").addEventListener("click", () =>
        nameDialog.open({
          title: `Rename ${noun}`,
          value: graph.name,
          onSubmit: async (name) => {
            await renameGraph(kind, graph.id, name);
            await load();
          },
        }),
      );
      item.querySelector("[data-delete]").addEventListener("click", () =>
        confirm.open({
          message: kind === "action" ? `Delete "${graph.name}"? This cannot be undone.` : `Delete "${graph.name}" with all its stages and actions? This cannot be undone.`,
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
  emptyEl.hidden = items.length > 0;
}

async function load() {
  try {
    items = await listGraphs(kind);
    banner.hide();
    render();
  } catch {
    banner.show(`${noun[0].toUpperCase()}${noun.slice(1)}s could not be loaded.`, { retry: true });
  }
}

document.querySelector("[data-new-graph]").addEventListener("click", () =>
  nameDialog.open({
    title: `New ${noun}`,
    onSubmit: async (name) => {
      const created = await createGraph(kind, name);
      window.location.assign(`${path}/${encodeURIComponent(created.slug)}`);
    },
  }),
);
banner.onRetry(load);

load();
