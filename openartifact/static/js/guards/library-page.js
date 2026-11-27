/* The Guards page (ADR-060, ADR-069): the guard library as a management page. Cards or rows (name, what fires it, its condition in
 * words, its consequence, where it is used, whether it is a draft or which version is published), a detail panel (Overview, Usage,
 * Versions, Preview); "New guard" (a blank one, opened in the editor); a double click or the
 * pencil opens a guard in the guard editor; Delete is refused, with the reason, while it is used somewhere. Guards are attached to a
 * pipeline, a stage or an action in the pipeline editor; a definition has no on/off of its own (an attachment has). A definition is
 * edited as a draft; only a published version applies (ADR-081): the Versions tab publishes, shows an earlier version read-only (in
 * the Overview) and publishes it again. `?open=<id>` opens one (the way back from its action). The frame is
 * components/management-page.js; the sentences are guards/model.js (the same the guard editor uses). */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { ManagementPage, cardBody, chip, make } from "../components/management-page.js";
import { Modal } from "../components/modal.js";
import * as rules from "../components/rule-model.js";
import { publicationChip, renderVersions } from "../editor/versions-tab.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { GuardEditor, loadSchema } from "./editor-window.js";
import * as model from "./model.js";

const calls = model.versionCalls((url, method) => request(url, { method }));
// the version the Overview shows instead of the draft, by guard (the Versions tab's "Show")
const shownVersion = new Map();

const root = document.querySelector("[data-management]");
const newButton = document.querySelector("[data-new-guard]");

const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const editor = new GuardEditor(new Modal(document.getElementById("guard-modal")), {
  actionUrl: (actionId, guardId) => `/actions/${encodeURIComponent(actionId)}?guard=${encodeURIComponent(guardId)}`,
  confirm: (message, action, options = {}) => confirm.open({ message, onConfirm: action, ...options }),
  onSaved: () => load(),
  onDeleted: () => load(),
});

let guards = [];
let schema = null;
let actionNames = new Map(); // guard action id -> name

async function open(guard) {
  try {
    await editor.open(guard);
  } catch (error) {
    banner.show(error.message || t("guards.not_loaded"), { autoHide: 6000 });
  }
}

const conditionText = (guard) => (schema && guard.when ? rules.describe(guard.when, schema) : "") || t("guards.summary.no_condition");
const triggerChip = (guard) => chip(model.triggerText(guard.trigger), { glyph: guard.trigger?.type === "interval" ? "clock" : "refresh" });
const consequenceChip = (guard) => chip(t(`guards.consequence.${guard.consequence}`), { glyph: "shield" });

function card(guard) {
  // the middle is the condition in words (the description is in the panel); the foot: what triggers it, what it does, and where it is used
  const used = make("span", "", model.usedText(guard.used_by)); // where it is used: a line, not a third chip that wraps
  used.dataset.used = "";
  return cardBody({
    title: guard.name,
    text: conditionText(guard),
    textTitle: conditionText(guard),
    chips: [triggerChip(guard), consequenceChip(guard), publicationChip(guard)],
    facts: [used],
  });
}

// ── the panel ────────────────────────────────────────────────────────
function fact(list, label, value) {
  list.append(make("dt", "", label), Object.assign(make("dd"), { textContent: value }));
}

/** The Overview: the draft as the editor has it, or, after "Show" in the Versions tab, an earlier version read-only (a note says which,
 * and a way back to the draft). */
function overview(body, guard) {
  const number = shownVersion.get(guard.id) ?? null;
  if (number === null) {
    drawOverview(body, guard, false);
    return;
  }
  const note = make("p", "mg-showing");
  note.append(document.createTextNode(t("graph_versions.showing", { number })));
  const back = make("button", "button button--ghost button--sm", t("graph_versions.back_to_draft"));
  back.type = "button";
  back.dataset.backToDraft = "";
  back.addEventListener("click", () => {
    shownVersion.delete(guard.id);
    page.refreshPanel();
  });
  note.append(back);
  body.append(note);
  calls
    .version(guard.id, number)
    .then((found) => drawOverview(body, { ...guard, ...found.guard }, true))
    .catch(() => body.append(make("p", "mg-card__facts", t("graph_versions.load_error"))));
}

function drawOverview(body, guard, readOnly) {
  const list = make("dl", "mg-facts");
  fact(list, t("guards.panel.trigger"), model.triggerText(guard.trigger));
  fact(list, t("guards.panel.condition"), conditionText(guard));
  fact(list, t("guards.panel.then"), t(`guards.consequence.${guard.consequence}`));
  if (guard.consequence === "run_action") {
    list.append(make("dt", "", t("guards.panel.action")));
    const dd = make("dd");
    if (guard.action_id) {
      const link = make("a", "", actionNames.get(guard.action_id) ?? t("guards.panel.action_unknown"));
      link.href = `/actions/${encodeURIComponent(guard.action_id)}`;
      dd.append(link);
    } else {
      dd.textContent = t("guards.panel.no_action");
    }
    list.append(dd);
    fact(list, t("guards.panel.fallback"), t(`guards.consequence.${guard.fallback ?? "pause"}`));
  }
  if (guard.escalation?.length) fact(list, t("guards.panel.escalation"), guard.escalation.map(model.escalationText).join("; "));
  fact(list, t("graph_list.description"), guard.description || "–");
  fact(list, t("guards.panel.used"), model.usedText(guard.used_by));
  body.append(list);
  if (readOnly) return; // an earlier version is only shown; the draft is what is opened and changed
  const actions = make("div", "action-row");
  const edit = make("button", "button button--primary button--sm", t("graph_list.open"));
  edit.type = "button";
  edit.dataset.openGuard = "";
  edit.addEventListener("click", () => open(guard));
  actions.append(edit);
  body.append(actions);
}

function versionsTab(body, guard) {
  renderVersions(body, guard, {
    api: calls,
    texts: model.versionWords,
    confirm: (options) => confirm.open(options),
    shown: shownVersion.get(guard.id) ?? null,
    onShow: (number) => {
      shownVersion.set(guard.id, number);
      page.panelTab = "overview";
      page.refreshPanel();
    },
    onChanged: async () => {
      shownVersion.delete(guard.id);
      await load();
    },
  });
}

function usage(body, guard) {
  const section = make("section", "mg-section");
  section.append(make("h3", "", t("graph_list.used_by")));
  const list = make("ul", "mg-uses");
  for (const attachment of guard.attachments ?? []) {
    const place = model.attachmentPlace(attachment);
    const item = make("li");
    item.append(make("span", "mg-uses__kind", place.watches));
    const link = make("a", "", place.holder);
    link.href = place.href;
    item.append(link);
    if (!attachment.enabled) item.append(chip(t("guards.panel.off")));
    if (model.isInactive(attachment)) item.append(chip(t("guards.panel.not_published")));
    list.append(item);
  }
  if (!list.children.length) list.append(make("li", "mg-card__facts", t("guards.unused")));
  section.append(list);
  body.append(section);
}

async function previewTab(body, guard) {
  const line = make("p", "field__help gd-preview");
  line.setAttribute("role", "status");
  body.append(line);
  if (!guard.used_by) {
    line.textContent = t("guards.preview_unattached");
    return;
  }
  if (!rules.countConditions(guard.when)) {
    line.textContent = t("guards.preview_empty");
    return;
  }
  try {
    line.textContent = model.previewText(await request("/api/guards/preview", { method: "POST", body: JSON.stringify({ guard_id: guard.id, when: guard.when }) }));
  } catch {
    line.textContent = t("guards.load_error");
  }
}

const page = new ManagementPage(root, {
  name: "guards",
  label: t("guards.library"),
  placeholder: t("guards.search_placeholder"),
  emptyText: t("guards.empty"),
  itemKey: (guard) => guard.id,
  search: (guard) => `${guard.name} ${guard.description ?? ""} ${model.summaryLine(guard, schema)}`,
  sorts: [
    { key: "name", label: t("graph_list.sort_name"), compare: (a, b) => a.name.localeCompare(b.name) },
    { key: "name_desc", label: t("graph_list.sort_name_desc"), compare: (a, b) => b.name.localeCompare(a.name) },
    { key: "used", label: t("guards.panel.sort_used"), compare: (a, b) => (b.used_by ?? 0) - (a.used_by ?? 0) || a.name.localeCompare(b.name) },
  ],
  card,
  editLabel: (guard) => t("graph_list.open_noun", { name: guard.name }),
  deleteLabel: (guard) => t("guards.delete_name", { name: guard.name }),
  deleteBlocked: (guard) => model.deleteBlocked(guard) || null, // the bin of a used guard is disabled and says why (a click shows it as a banner too)
  onBlocked: (_guard, reason) => banner.show(reason, { autoHide: 6000 }),
  panel: {
    placeholder: t("guards.select_one"),
    icon: () => "shield",
    title: (guard) => guard.name,
    chips: (guard) => [triggerChip(guard), consequenceChip(guard), publicationChip(guard)],
    tabs: () => [
      { key: "overview", label: t("graph_list.tab_overview"), render: overview },
      { key: "usage", label: t("graph_list.tab_usage"), render: usage },
      { key: "versions", label: t("guards.tab_versions"), render: versionsTab },
      { key: "preview", label: t("guards.panel.tab_preview"), render: previewTab },
    ],
  },
  onOpen: open,
  onEdit: open,
  onDelete: (guard) =>
    confirm.open({
      message: t("guards.delete_question", { name: guard.name }),
      onConfirm: async () => {
        await request(`/api/guards/${encodeURIComponent(guard.id)}`, { method: "DELETE" });
        await load();
      },
    }),
});

async function load() {
  try {
    const [found, serverSchema, actions] = await Promise.all([
      request("/api/guards"),
      loadSchema(),
      request("/api/actions?purpose=guard"),
    ]);
    guards = found;
    schema = model.builderSchema(serverSchema);
    actionNames = new Map(actions.map((a) => [a.id, a.name]));
    banner.hide();
    page.setItems(guards);
  } catch {
    banner.show(t("guards.load_error"), { retry: true });
  }
}

newButton.addEventListener("click", () => editor.openNew().catch((error) => banner.show(error.message, { autoHide: 6000 })));
banner.onRetry(load);

await load();
const wanted = new URLSearchParams(window.location.search).get("open");
if (wanted) {
  window.history.replaceState(null, "", window.location.pathname);
  const guard = guards.find((g) => g.id === wanted);
  if (guard) open(guard);
}
