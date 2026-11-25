/* The agents page (ADR-069): the list of agents as cards or rows and the detail panel (Overview, Versions); create, change (name,
 * description) and delete. It is about the DEFINITION of an agent, not where it is used. An agent is edited on its own page
 * (/agents/{id}); a click selects, a double click and the pencil open it. The frame is components/management-page.js. */
import { AlertBar } from "../components/alert-bar.js";
import { ClampedText } from "../components/clamped-text.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { ManagementPage, chip, make } from "../components/management-page.js";
import { ManifestDialog } from "../components/manifest-dialog.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { createAgent, deleteAgent, getAgent, listAgents, listProviders, updateAgent } from "./api.js";
import { agentChips, fieldLabel, limitRows, optionsOf, showValue, useText } from "./model.js";
import { t, tn } from "../i18n.js";

const root = document.querySelector("[data-management]");
const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const dialog = new ManifestDialog(new Modal(document.getElementById("agent-modal")), { form: "agent", confirm: (options) => confirm.open(options) });

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const editorUrl = (agent) => `/agents/${encodeURIComponent(agent.id)}`;
const toneOf = { ok: "ok", warn: "warn", bad: "bad", accent: "accent", "": null };

let providers = new Map(); // id -> name
const providerName = (id) => providers.get(id) ?? null;

/** The provider and the model the agent sets itself ("liteLLM · free-pool"), or null when it sets neither. */
const engineOf = (agent) => [agent.provider_id ? providerName(agent.provider_id) : null, agent.model].filter(Boolean).join(" · ") || null;

const chipsOf = (agent) => agentChips(agent).map(([text, tone]) => chip(text, { tone: toneOf[tone] ?? null }));

// ── the detail of an agent (its prompts and settings): loaded when it is selected, kept while it has not changed ──
const details = new Map();
function detailOf(agent) {
  const key = `${agent.id}@${agent.updated_at}`;
  if (!details.has(key)) details.set(key, getAgent(agent.id));
  return details.get(key);
}

function card(agent) {
  const box = make("div", "mg-card__body");
  const head = make("div", "mg-card__head");
  head.append(make("h3", "mg-card__name", agent.name));
  const chips = make("div", "mg-card__chips");
  chips.append(...chipsOf(agent));
  head.append(chips);
  box.append(head);
  const start = agent.user_prompt_start || agent.description;
  if (start) box.append(make("p", "mg-card__text", start));
  const facts = make("p", "mg-card__facts");
  const engine = engineOf(agent);
  for (const [value, before] of [[engine, ""], [useText(agent.node_count), ""], [when(agent.updated_at), `${t("graph_list.changed")} `]]) {
    if (!value) continue;
    const part = make("span");
    part.append(document.createTextNode(before), make("b", "", value));
    facts.append(part);
  }
  box.append(facts);
  return box;
}

// ── the panel ────────────────────────────────────────────────────────
function fact(list, label, value) {
  if (value === null || value === undefined || value === "") return;
  list.append(make("dt", "", label), Object.assign(make("dd"), { textContent: value }));
}

function section(title, content) {
  const block = make("section", "mg-section");
  block.append(make("h3", "", title), content);
  return block;
}

/** The settings of an agent the page names: the limits it sets, only when its own limits are in effect. */
function settingsFacts(config) {
  const list = make("dl", "mg-facts");
  for (const [key, value] of limitRows(config)) fact(list, fieldLabel(key), showValue(value));
  return list;
}

function overview(body, agent) {
  body.append(make("p", "mg-card__facts", t("graph_list.loading")));
  detailOf(agent)
    .then((detail) => {
      // the published configuration is what runs; the draft is shown on request when it differs
      const both = detail.published && detail.draft_changed;
      let which = detail.published ? "published" : "draft";
      const draw = () => {
        const config = which === "published" ? detail.published : detail.draft;
        const prompts = make("div", "mg-prompts");
        if (both) {
          const switcher = make("div", "mg-prompt-switch");
          switcher.setAttribute("role", "group");
          for (const [key, label] of [["published", t("agents.page.published")], ["draft", t("agents.page.draft")]]) {
            const button = make("button", "button button--ghost button--sm", label);
            button.type = "button";
            button.dataset.show = key;
            button.setAttribute("aria-pressed", String(which === key));
            button.addEventListener("click", () => {
              which = key;
              draw();
            });
            switcher.append(button);
          }
          prompts.append(switcher);
        }
        prompts.append(section(t("agent_editor.user_prompt"), new ClampedText({ text: config.user_prompt, label: t("agent_editor.user_prompt"), empty: t("agents.page.no_prompt") }).element));
        if (optionsOf(config).system_prompt) prompts.append(section(t("agent_editor.system_prompt"), new ClampedText({ text: config.system_prompt, label: t("agent_editor.system_prompt"), empty: t("agents.page.no_prompt") }).element));
        const list = make("dl", "mg-facts");
        fact(list, t("graph_list.status"), detail.published_number == null ? t("agents.editor_page.not_published") : t("agents.editor_page.v_published_number_published", { published_number: detail.published_number }));
        if (detail.published_number != null && detail.draft_changed) fact(list, "", t("agents.model.draft_has_changes"));
        if (optionsOf(config).limits) {
          fact(list, t("common.provider"), config.provider_id ? providerName(config.provider_id) ?? config.provider_id : null);
          fact(list, fieldLabel("model"), config.model);
        }
        fact(list, t("graph_list.changed"), when(detail.updated_at));
        fact(list, t("graph_list.description"), detail.description || null);
        const settings = settingsFacts(config);
        const actions = make("div", "action-row");
        const open = make("a", "button button--primary button--sm", t("graph_list.open"));
        open.href = editorUrl(agent);
        const change = make("button", "button button--ghost button--sm", t("graph_list.properties"));
        change.type = "button";
        change.dataset.properties = "";
        change.addEventListener("click", () => openDialog(agent));
        actions.append(open, change);
        body.replaceChildren(prompts, list, ...(settings.children.length ? [section(t("agents.page.settings"), settings)] : []), actions);
      };
      draw();
    })
    .catch(() => body.replaceChildren(make("p", "mg-card__facts", t("agents.list_page.agents_could_not_be_loaded"))));
}

function versions(body, agent) {
  body.append(make("p", "mg-card__facts", t("graph_list.loading")));
  detailOf(agent)
    .then((detail) => {
      const list = make("ul", "mg-uses");
      for (const version of detail.versions) {
        const item = make("li");
        const via = version.source_number ? ` · ${t("agents.page.repeats", { number: version.source_number })}` : "";
        item.append(make("span", "mg-uses__kind", `v${version.number}${version.current ? ` · ${t("agents.page.current")}` : ""}`), document.createTextNode(`${when(version.published_at)}${via}`));
        list.append(item);
      }
      if (!detail.versions.length) list.append(make("li", "mg-card__facts", t("agents.editor_page.not_published")));
      const open = make("a", "button button--ghost button--sm", t("agents.page.manage_versions"));
      open.href = editorUrl(agent);
      body.replaceChildren(section(t("graph_list.tab_versions"), list), open);
    })
    .catch(() => body.replaceChildren(make("p", "mg-card__facts", t("agents.list_page.agents_could_not_be_loaded"))));
}

const page = new ManagementPage(root, {
  name: "agents",
  label: t("page.agents"),
  placeholder: t("agents.page.search"),
  emptyText: t("agents.no_agents_yet_create_the_first"),
  itemKey: (agent) => agent.id,
  search: (a) => `${a.name} ${a.description} ${a.user_prompt_start} ${a.model ?? ""} ${engineOf(a) ?? ""}`,
  sorts: [
    { key: "name", label: t("graph_list.sort_name"), compare: (a, b) => a.name.localeCompare(b.name) },
    { key: "name_desc", label: t("graph_list.sort_name_desc"), compare: (a, b) => b.name.localeCompare(a.name) },
    { key: "changed", label: t("graph_list.sort_changed"), compare: (a, b) => b.updated_at.localeCompare(a.updated_at) },
  ],
  card,
  editLabel: (agent) => t("graph_list.open_noun", { name: agent.name }),
  deleteLabel: () => t("agents.delete_agent"),
  // an agent that a node refers to cannot be deleted (its nodes would lose it): the bin says so
  deleteBlocked: (agent) => (agent.node_count ? tn("agents.list_page.refers", agent.node_count) : null),
  panel: {
    icon: () => "agent",
    title: (agent) => agent.name,
    chips: chipsOf,
    tabs: () => [
      { key: "overview", label: t("graph_list.tab_overview"), render: overview },
      { key: "versions", label: t("graph_list.tab_versions"), render: versions },
    ],
  },
  onOpen: (agent) => window.location.assign(editorUrl(agent)),
  onEdit: (agent) => window.location.assign(editorUrl(agent)),
  onDelete: (agent) =>
    confirm.open({
      message: t("agents.list_page.delete_agent_subject_with_all"),
      subject: agent.name,
      onConfirm: async () => {
        await deleteAgent(agent.id);
        await load();
      },
    }),
});

/** The window that makes (agent null) or changes an agent: its name and description. */
function openDialog(agent) {
  dialog.open({
    title: agent ? t("agents.page.edit_agent") : t("agents.new_agent"),
    values: { name: agent?.name ?? "", description: agent?.description ?? "" },
    submitLabel: agent ? t("common.save") : t("common.create"),
    onSubmit: async ({ name, description }) => {
      const fields = { name: String(name).trim(), description: String(description ?? "").trim() };
      if (!agent) {
        const created = await createAgent(fields);
        window.location.assign(editorUrl(created));
        return;
      }
      await updateAgent(agent.id, fields);
      await load();
    },
  });
}

async function load() {
  try {
    const [agents, known] = await Promise.all([listAgents(), listProviders().catch(() => [])]);
    providers = new Map(known.map((p) => [p.id, p.name]));
    page.setItems(agents);
    banner.hide();
  } catch {
    banner.show(t("agents.list_page.agents_could_not_be_loaded"), { retry: true });
  }
}

document.querySelector("[data-new-agent]").addEventListener("click", () => openDialog(null));
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
