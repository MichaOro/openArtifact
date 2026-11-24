/* The Guards page (ADR-060): the guard library, built like the Actions page. Each guard with one line about what fires
 * it and its condition, its consequence and in how many places it is used; a search; "New guard" (a menu: a blank one or
 * one from a template: Stall, Runtime, Health guard); a click opens it in the guard editor; Delete is refused, with the
 * reason, while it is used somewhere. Guards are attached to a pipeline, a stage or an action in the pipeline editor; a
 * definition has no on/off of its own (an attachment has). `?open=<id>` opens one (the way back from its action). */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { GuardEditor, loadSchema } from "./editor-window.js";
import * as model from "./model.js";

const listEl = document.querySelector("[data-guard-list]");
const emptyEl = document.querySelector("[data-guard-empty]");
const noMatchEl = document.querySelector("[data-guard-nomatch]");
const search = document.querySelector("[data-guard-search]");
const newButton = document.querySelector("[data-new-guard]");
const template = document.getElementById("guard-item-template");

const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const menu = new ActionMenu();
const editor = new GuardEditor(new Modal(document.getElementById("guard-modal")), {
  actionUrl: (actionId, guardId) => `/actions/${encodeURIComponent(actionId)}?guard=${encodeURIComponent(guardId)}`,
  confirm: (message, action) => confirm.open({ message, onConfirm: action }),
  onSaved: () => load(),
  onDeleted: () => load(),
});

const ORDER = ["stall", "runtime", "health"]; // the templates from the simplest on

let guards = [];
let schema = null;
let templates = [];

async function open(guard) {
  try {
    await editor.open(guard);
  } catch (error) {
    banner.show(error.message || t("guards.not_loaded"), { autoHide: 6000 });
  }
}

function render() {
  const shown = guards.filter((g) => model.matches(g, search.value, schema));
  listEl.replaceChildren(
    ...shown.map((guard) => {
      const item = template.content.firstElementChild.cloneNode(true);
      item.dataset.guardId = guard.id;
      const link = item.querySelector("a");
      link.href = `/guards?open=${encodeURIComponent(guard.id)}`;
      link.title = guard.description || "";
      link.addEventListener("click", (event) => {
        event.preventDefault();
        open(guard);
      });
      item.querySelector(".ge-item__name").textContent = guard.name;
      item.querySelector("[data-summary]").textContent = model.summaryLine(guard, schema);
      item.querySelector("[data-consequence]").textContent = t(`guards.consequence.${guard.consequence}`);
      item.querySelector("[data-used]").textContent = model.usedText(guard.used_by);
      const bin = item.querySelector("[data-delete]");
      const blocked = model.deleteBlocked(guard);
      bin.setAttribute("aria-label", blocked ? `${t("guards.delete_name", { name: guard.name })}: ${blocked}` : t("guards.delete_name", { name: guard.name }));
      bin.title = blocked || t("common.delete");
      bin.setAttribute("aria-disabled", String(Boolean(blocked)));
      bin.addEventListener("click", () => {
        if (blocked) return banner.show(blocked, { autoHide: 6000 });
        confirm.open({
          message: t("guards.delete_question", { name: guard.name }),
          onConfirm: async () => {
            await request(`/api/guards/${encodeURIComponent(guard.id)}`, { method: "DELETE" });
            await load();
          },
        });
      });
      return item;
    }),
  );
  emptyEl.hidden = guards.length > 0;
  noMatchEl.hidden = !guards.length || shown.length > 0;
}

async function load() {
  try {
    const [found, serverSchema, shipped] = await Promise.all([request("/api/guards"), loadSchema(), templates.length ? templates : request("/api/guards/templates")]);
    guards = found;
    schema = model.builderSchema(serverSchema);
    templates = shipped;
    banner.hide();
    render();
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
search.addEventListener("input", render);
banner.onRetry(load);

await load();
const wanted = new URLSearchParams(window.location.search).get("open");
if (wanted) {
  window.history.replaceState(null, "", window.location.pathname);
  const guard = guards.find((g) => g.id === wanted);
  if (guard) open(guard);
}
