/* The agents page: the list, creating and deleting. An agent is edited on its own page (/agents/{id}). */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { createAgent, deleteAgent, listAgents } from "./api.js";
import { agentChips, useText } from "./model.js";
import { chip } from "./view.js";
import { t, tn } from "../i18n.js";

const listEl = document.querySelector("[data-agent-list]");
const emptyEl = document.querySelector("[data-agent-empty]");
const template = document.getElementById("agent-item-template");
const banner = new AlertBar();
const nameDialog = new FormDialog(new Modal(document.getElementById("name-modal")));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));

let agents = [];

function render() {
  listEl.replaceChildren(
    ...agents.map((agent) => {
      const item = template.content.firstElementChild.cloneNode(true);
      item.dataset.agentId = agent.id;
      item.querySelector(".ge-item__link").href = `/agents/${encodeURIComponent(agent.id)}`;
      item.querySelector(".ge-item__name").textContent = agent.name;
      item.querySelector(".ge-item__meta").textContent = [agent.description, useText(agent.node_count)].filter(Boolean).join(" · ");
      item.querySelector("[data-chips]").replaceChildren(...agentChips(agent).map(([text, tone]) => chip(text, tone)));
      const remove = item.querySelector("[data-delete]");
      const used = agent.node_count;
      if (used) {
        const hint = item.querySelector(".ag-item__hint");
        hint.textContent = tn("agents.list_page.refers", used);
        hint.hidden = false;
        hint.id = `agent-hint-${agent.id}`;
        remove.setAttribute("aria-disabled", "true");
        remove.setAttribute("aria-describedby", hint.id);
        remove.title = t("agents.list_page.use_cannot_be_deleted");
      }
      remove.addEventListener("click", () => {
        if (used) return;
        confirm.open({
          message: t("agents.list_page.delete_agent_subject_with_all"),
          subject: agent.name,
          onConfirm: async () => {
            await deleteAgent(agent.id);
            await load();
          },
        });
      });
      return item;
    }),
  );
  emptyEl.hidden = agents.length > 0;
}

async function load() {
  try {
    agents = await listAgents();
    banner.hide();
    render();
  } catch {
    banner.show(t("agents.list_page.agents_could_not_be_loaded"), { retry: true });
  }
}

document.querySelector("[data-new-agent]").addEventListener("click", () =>
  nameDialog.open({
    title: t("agents.new_agent"),
    onSubmit: async ({ name, description }) => {
      const created = await createAgent({ name, description });
      window.location.assign(`/agents/${encodeURIComponent(created.id)}`);
    },
  }),
);
banner.onRetry(load);

let refresh = 0;
connectEvents({
  onClosed: () => {},
  onOpen: () => load(),
  onEvent: (type) => {
    if (type !== "agents.changed") return;
    clearTimeout(refresh);
    refresh = setTimeout(load, 150);
  },
});
