/* The management page of pipelines or action definitions (ADR-069): the list as cards or rows with the picture of each graph, the detail
 * panel (Overview, Graph, Versions, Usage), create, change (name, type, description, tags), delete, open. The frame is
 * components/management-page.js; this page says what an entry is. Actions are in two tabs, the ones for pipelines and the ones for
 * guards (ADR-067); the window that makes or changes one is a form manifest (ui/forms/action.yaml, pipeline.yaml, ADR-065). */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { GraphPreview } from "../components/graph-preview.js";
import { ManagementPage, cardBody, chip, make } from "../components/management-page.js";
import { ManifestDialog } from "../components/manifest-dialog.js";
import { Modal } from "../components/modal.js";
import { sceneOfGraph } from "../components/preview-layout.js";
import { KEYS, readJson, removeStorage } from "../storage.js";
import { createGraph, deleteGraph, listGraphs, loadGraph, updateGraph, usesOf, versionOf } from "./api.js";
import { loadNodeTypes, typeOf } from "./node-types.js";
import { publicationChip, publicationOf, publicationText, renderVersions } from "./versions-tab.js";
import { t } from "../i18n.js";

const root = document.querySelector("[data-management]");
const { kind, path } = root.dataset;
const noun = kind === "action" ? "action" : "pipeline";

const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const dialog = new ManifestDialog(new Modal(document.getElementById("graph-modal")), { form: noun, confirm: (options) => confirm.open(options) });

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
/** The day only, for a card: its one line of facts has no room for the time (the panel has both). */
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
const editorUrl = (graph) => `${path}/${encodeURIComponent(graph.slug)}`;

/** The sidebar's "Pipeline" must not reopen a pipeline that is gone. */
function forget(slug) {
  if (readJson(KEYS.lastPipeline)?.slug === slug) removeStorage(KEYS.lastPipeline);
}

// ── the picture of a graph: loaded when the panel shows it, kept while the graph has not changed ──
const isTool = (k) => Boolean(typeOf(k)?.tool);
const scenes = new Map();
function sceneOf(graph) {
  const key = `${graph.id}@${graph.updated_at}`;
  if (!scenes.has(key)) scenes.set(key, loadGraph(kind, graph.id).then((detail) => sceneOfGraph(detail, isTool)));
  return scenes.get(key);
}

const purposeChip = (graph) => (kind === "action" ? (graph.purpose === "guard" ? chip(t("graph.action.chip_guard"), { glyph: "shield", tone: "guard" }) : chip(t("graph.action.chip_pipeline"), { glyph: "action" })) : null);
/** The chip of the observe mode of a pipeline (ADR-088): the open eye while its runs are observed, the stop sign while the observation has ended. */
function observeChip(graph) {
  if (graph.observe !== "observing" && graph.observe !== "ended") return null;
  const ended = graph.observe === "ended";
  const el = chip(ended ? t("graph_list.chip_observe_ended") : t("graph_list.chip_observing"), { glyph: ended ? "hand" : "eye" });
  el.dataset.observe = graph.observe;
  return el;
}
const chipsOf = (graph) => [purposeChip(graph), publicationChip(graph), observeChip(graph)].filter(Boolean);

function card(graph) {
  // no picture on a card: the graph is in the panel (tab Graph), which keeps the cards calm
  return cardBody({
    title: graph.name,
    text: graph.description,
    chips: chipsOf(graph),
    facts: [factOf(String(graph.node_count), ` ${t("graph_list.nodes")}`, "")],
    date: factOf(day(graph.updated_at), "", `${t("graph_list.changed")} `),
  });
}

function factOf(value, after, before) {
  const part = make("span");
  part.append(document.createTextNode(before), make("b", "", value), document.createTextNode(after));
  return part;
}

// ── the panel ────────────────────────────────────────────────────────
function fact(list, label, value) {
  list.append(make("dt", "", label), Object.assign(make("dd"), { textContent: value }));
}

function overview(body, graph) {
  const list = make("dl", "mg-facts");
  if (kind === "action") fact(list, t("graph_list.type"), graph.purpose === "guard" ? t("graph.action.chip_guard") : t("graph.action.chip_pipeline"));
  fact(list, t("graph_list.status"), publicationText(publicationOf(graph)));
  fact(list, t("graph_list.nodes"), String(graph.node_count));
  fact(list, t("graph_list.changed"), when(graph.updated_at));
  fact(list, t("graph_list.description"), graph.description || "–");
  const tags = make("section", "mg-section");
  tags.append(make("h3", "", t("graph_list.tags")));
  const row = make("div", "mg-tags");
  row.append(...(graph.tags.length ? graph.tags.map((tag) => make("span", "mg-tag", tag)) : [make("span", "mg-card__facts", "–")]));
  tags.append(row);
  const actions = make("div", "action-row");
  const open = make("a", "button button--primary button--sm", t("graph_list.open"));
  open.href = editorUrl(graph);
  const change = make("button", "button button--ghost button--sm", t("graph_list.properties"));
  change.type = "button";
  change.dataset.properties = "";
  change.addEventListener("click", () => openDialog(graph));
  actions.append(open, change);
  body.append(list, tags, actions);
}

// the version the Graph tab shows instead of the draft, by graph (the Versions tab's "Show", ADR-070)
const shownVersion = new Map();

function graphTab(body, graph) {
  const picture = make("div");
  const number = shownVersion.get(graph.id) ?? null;
  if (number === null) {
    body.append(picture);
    sceneOf(graph).then((scene) => new GraphPreview(picture, { scene, typeOf, node: 44 }));
    return;
  }
  // a published version, read-only: the note says which one it is and a way back to the draft
  const note = make("p", "mg-showing");
  note.append(document.createTextNode(t("graph_versions.showing", { number })));
  const back = make("button", "button button--ghost button--sm", t("graph_versions.back_to_draft"));
  back.type = "button";
  back.addEventListener("click", () => {
    shownVersion.delete(graph.id);
    page.refreshPanel();
  });
  note.append(back);
  body.append(note, picture);
  versionOf(kind, graph.id, number)
    .then((found) => new GraphPreview(picture, { scene: sceneOfGraph(found, isTool), typeOf, node: 44 }))
    .catch(() => picture.replaceChildren(make("p", "mg-card__facts", t(`graph.${noun}.load_error`))));
}

function versionsTab(body, graph) {
  renderVersions(body, graph, {
    kind,
    confirm: (options) => confirm.open(options),
    shown: shownVersion.get(graph.id) ?? null,
    onShow: (number) => {
      shownVersion.set(graph.id, number);
      page.panelTab = "graph";
      page.refreshPanel();
    },
    onChanged: async () => {
      shownVersion.delete(graph.id);
      await load();
    },
  });
}

async function usageTab(body, graph) {
  body.append(make("p", "mg-card__facts", t("graph_list.loading")));
  try {
    const found = await usesOf(kind, graph.id);
    const section = make("section", "mg-section");
    section.append(make("h3", "", t("graph_list.used_by")));
    const list = make("ul", "mg-uses");
    for (const use of found.uses) {
      const item = make("li");
      item.append(make("span", "mg-uses__kind", t(`graph_list.use_${use.kind}`)));
      if (use.href) Object.assign(item.appendChild(make("a")), { href: use.href, textContent: use.detail ? `${use.name} · ${use.detail}` : use.name });
      else item.append(document.createTextNode(use.name));
      list.append(item);
    }
    if (!found.uses.length) list.append(make("li", "mg-card__facts", t("graph_list.unused")));
    section.append(list);
    body.replaceChildren(section);
    if (found.artifacts !== null) {
      const counts = make("dl", "mg-facts");
      fact(counts, t("graph_list.artifacts"), String(found.artifacts));
      fact(counts, t("graph_list.executions"), String(found.executions));
      body.append(counts);
    }
  } catch {
    body.replaceChildren(make("p", "mg-card__facts", t(`graph.${noun}.load_error`)));
  }
}

const page = new ManagementPage(root, {
  name: `${noun}s`,
  label: t(`page.${noun}s`),
  placeholder: t(`graph_list.search_${noun}`),
  emptyText: t(`graph.${noun}.empty`),
  itemKey: (graph) => graph.id,
  tabs:
    kind === "action"
      ? [
          { key: "pipeline", label: t("graph.action.tab_pipeline"), icon: "action", match: (g) => g.purpose === "pipeline" },
          { key: "guard", label: t("graph.action.tab_guard"), icon: "shield", match: (g) => g.purpose === "guard" },
        ]
      : null,
  search: (g) => `${g.name} ${g.description} ${g.tags.join(" ")}`,
  tagsOf: (g) => g.tags,
  sorts: [
    { key: "changed", label: t("graph_list.sort_changed"), compare: (a, b) => b.updated_at.localeCompare(a.updated_at) },
    { key: "name", label: t("graph_list.sort_name"), compare: (a, b) => a.name.localeCompare(b.name) },
    { key: "name_desc", label: t("graph_list.sort_name_desc"), compare: (a, b) => b.name.localeCompare(a.name) },
    { key: "nodes", label: t("graph_list.sort_nodes"), compare: (a, b) => b.node_count - a.node_count },
  ],
  card: (graph) => card(graph),
  editLabel: (graph) => t(`graph_list.open_noun`, { name: graph.name }),
  deleteLabel: () => t(`graph.${noun}.delete`),
  panel: {
    placeholder: t(`graph.${noun}.select`),
    icon: (graph) => (kind === "action" ? (graph.purpose === "guard" ? "shield" : "action") : "pipeline"),
    title: (graph) => graph.name,
    chips: chipsOf,
    tabs: () => [
      { key: "overview", label: t("graph_list.tab_overview"), render: overview },
      { key: "graph", label: t("graph_list.tab_graph"), render: graphTab },
      { key: "versions", label: t("graph_list.tab_versions"), render: versionsTab },
      { key: "usage", label: t("graph_list.tab_usage"), render: usageTab },
    ],
  },
  onTab: (tab) => (purpose = tab),
  onOpen: (graph) => window.location.assign(editorUrl(graph)),
  onEdit: (graph) => window.location.assign(editorUrl(graph)),
  onDelete: (graph) =>
    confirm.open({
      message: kind === "action" ? t("editor.list.delete_name_cannot_be_undone", { name: graph.name }) : t("editor.list.delete_name_with_all_its", { name: graph.name }),
      onConfirm: async () => {
        await deleteGraph(kind, graph.id);
        forget(graph.slug);
        await load();
      },
    }),
});

// the tab that is open says what a new action is for (an action for pipelines or one for guards)
let purpose = "pipeline";

/** The window that makes (graph null) or changes a pipeline or an action: its name, description, tags and, for an action, what it is for. */
function openDialog(graph) {
  dialog.open({
    title: graph ? t(`editor.list.edit_${noun}`) : kind === "action" && purpose === "guard" ? t("editor.list.new_guard_action") : t("editor.list.new_noun", { noun }),
    values: { name: graph?.name ?? "", description: graph?.description ?? "", tags: [...(graph?.tags ?? [])], ...(kind === "action" ? { purpose: graph?.purpose ?? purpose } : {}) },
    submitLabel: graph ? t("common.save") : t("common.create"),
    onSubmit: async ({ name, description, tags, purpose: chosen }) => {
      const fields = { description: String(description ?? "").trim(), tags: tags ?? [] };
      if (!graph) {
        const created = await createGraph(kind, String(name).trim(), kind === "action" ? chosen : null, fields);
        window.location.assign(`${path}/${encodeURIComponent(created.slug)}`);
        return;
      }
      await updateGraph(kind, graph.id, { name: String(name).trim(), ...(kind === "action" ? { purpose: chosen } : {}), ...fields });
      await load();
    },
  });
}

async function load() {
  try {
    await loadNodeTypes();
    page.setItems(await listGraphs(kind));
    banner.hide();
  } catch {
    banner.show(t(`graph.${noun}.load_error`), { retry: true });
  }
}

document.querySelector("[data-new-graph]").addEventListener("click", () => openDialog(null));
banner.onRetry(load);
load();
