/* The Guards page (ADR-060, ADR-069): the guard library as a management page. Cards or rows (name, what fires it, its condition in
 * words, its consequence, where it is used), a detail panel (Overview, Usage, Preview); "New guard" (a menu: a blank one or one from a
 * template: Stall, Runtime, Health guard); a double click or the pencil opens a guard in the guard editor; Delete is refused, with the
 * reason, while it is used somewhere. Guards are attached to a pipeline, a stage or an action in the pipeline editor; a definition has
 * no on/off of its own (an attachment has). `?open=<id>` opens one (the way back from its action). The frame is
 * components/management-page.js; the sentences are guards/model.js (the same the guard editor uses). */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { ManagementPage, chip, make } from "../components/management-page.js";
import { Modal } from "../components/modal.js";
import * as rules from "../components/rule-model.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { GuardEditor, loadSchema } from "./editor-window.js";
import * as model from "./model.js";

const root = document.querySelector("[data-management]");
const newButton = document.querySelector("[data-new-guard]");

const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const menu = new ActionMenu();
const editor = new GuardEditor(new Modal(document.getElementById("guard-modal")), {
  actionUrl: (actionId, guardId) => `/actions/${encodeURIComponent(actionId)}?guard=${encodeURIComponent(guardId)}`,
  confirm: (message, action, options = {}) => confirm.open({ message, onConfirm: action, ...options }),
  onSaved: () => load(),
  onDeleted: () => load(),
});

const ORDER = ["stall", "runtime", "agent_quiet", "health", "agent_health"]; // the templates from the simplest on (rules only first, then the ones with an action)

let guards = [];
let schema = null;
let templates = [];
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
  const box = make("div", "mg-card__body");
  const head = make("div", "mg-card__head");
  head.append(make("h3", "mg-card__name", guard.name));
  const chips = make("div", "mg-card__chips");
  chips.append(triggerChip(guard), consequenceChip(guard));
  head.append(chips);
  if (guard.description) head.append(make("p", "mg-card__text", guard.description));
  const condition = make("p", "mg-card__facts", conditionText(guard));
  condition.title = conditionText(guard);
  const used = make("p", "mg-card__facts", model.usedText(guard.used_by)); // where it is used: a line, not a third chip that wraps
  used.dataset.used = "";
  box.append(head, condition, used);
  return box;
}

// ── the panel ────────────────────────────────────────────────────────
function fact(list, label, value) {
  list.append(make("dt", "", label), Object.assign(make("dd"), { textContent: value }));
}

function overview(body, guard) {
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
  const actions = make("div", "action-row");
  const edit = make("button", "button button--primary button--sm", t("graph_list.open"));
  edit.type = "button";
  edit.dataset.openGuard = "";
  edit.addEventListener("click", () => open(guard));
  actions.append(edit);
  body.append(list, actions);
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
    chips: (guard) => [triggerChip(guard), consequenceChip(guard)],
    tabs: () => [
      { key: "overview", label: t("graph_list.tab_overview"), render: overview },
      { key: "usage", label: t("graph_list.tab_usage"), render: usage },
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
    const [found, serverSchema, shipped, actions] = await Promise.all([
      request("/api/guards"),
      loadSchema(),
      templates.length ? templates : request("/api/guards/templates"),
      request("/api/actions?purpose=guard"),
    ]);
    guards = found;
    schema = model.builderSchema(serverSchema);
    templates = shipped;
    actionNames = new Map(actions.map((a) => [a.id, a.name]));
    banner.hide();
    page.setItems(guards);
  } catch {
    banner.show(t("guards.load_error"), { retry: true });
  }
}

async function fromTemplate(key) {
  try {
    const made = await request("/api/guards/from-template", {
      method: "POST",
      body: JSON.stringify({ template: key, name: t(`guards.template.${key}`), description: t(`guards.template.${key}_summary`) }),
    });
    await load();
    await open(made);
  } catch (error) {
    banner.show(error.detail ?? t("guards.template_failed"), { autoHide: 6000 });
  }
}

newButton.addEventListener("click", () =>
  menu.toggle(
    newButton,
    [
      { label: t("guards.new_blank"), icon: "shield", onSelect: () => editor.openNew().catch((error) => banner.show(error.message, { autoHide: 6000 })) },
      ...[...templates].sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key)).map((tpl) => ({ label: t("guards.from_template", { name: t(`guards.template.${tpl.key}`) }), icon: "layers", onSelect: () => fromTemplate(tpl.key) })),
    ],
    t("guards.new_menu"),
  ),
);
banner.onRetry(load);

await load();
const wanted = new URLSearchParams(window.location.search).get("open");
if (wanted) {
  window.history.replaceState(null, "", window.location.pathname);
  const guard = guards.find((g) => g.id === wanted);
  if (guard) open(guard);
}
