/* The agents page (ADR-069): the list of agents as cards or rows and the detail panel (Overview, Usage, Versions); create, change (name,
 * description) and delete. The Usage tab says where it is used (the agent nodes). An agent is edited on its own page
 * (/agents/{id}); a click selects, a double click and the pencil open it. The frame is components/management-page.js. */
import { AlertBar } from "../components/alert-bar.js";
import { ClampedText } from "../components/clamped-text.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { ManagementPage, cardBody, chip, make } from "../components/management-page.js";
import { ManifestDialog } from "../components/manifest-dialog.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { agentUses, createAgent, deleteAgent, getAgent, listAgents, listProviders, updateAgent } from "./api.js";
import { agentChips, fieldLabel, limitRows, optionsOf, showValue, useText } from "./model.js";
import { t, tn } from "../i18n.js";

const root = document.querySelector("[data-management]");
const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const dialog = new ManifestDialog(new Modal(document.getElementById("agent-modal")), { form: "agent", confirm: (options) => confirm.open(options) });

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
/** The day only, for a card: its one line of facts has no room for the time (the panel has both). */
const day = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
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
  // the text of a card is the description, when one is kept; without one nothing stands there (the prompt is in the panel)
  const part = (value, before = "") => {
    const span = make("span");
    span.append(document.createTextNode(before), make("b", "", value));
    return span;
  };
  const facts = [engineOf(agent), useText(agent.node_count)].filter(Boolean).map((value) => part(value));
  const date = agent.updated_at ? part(day(agent.updated_at), `${t("graph_list.changed")} `) : null;
  return cardBody({ title: agent.name, text: agent.description, chips: chipsOf(agent), facts, date });
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

/** Where the agent is used, as the Usage tab of the guards does: one row per agent node, the kind of place first, the action as a link that
 * opens it on the node, then what is special: not published yet (a node of the draft the published version of its action does not have),
 * only in the published version (the node was taken out of the draft), the fields it sets itself. A node always runs the published
 * version of the agent: nothing is pinned, so there is no version per row. */
function usage(body, agent) {
  const section = make("section", "mg-section");
  section.append(make("h3", "", t("graph_list.used_by")));
  const list = make("ul", "mg-uses");
  section.append(list, make("p", "field__help", t("agents.page.usage_follows_published")));
  body.append(section);
  list.append(make("li", "mg-card__facts", t("graph_list.loading")));
  agentUses(agent.id)
    .then((uses) => {
      list.replaceChildren(
        ...uses.map((use) => {
          const item = make("li");
          item.append(make("span", "mg-uses__kind", t(`agents.page.usage_kind.${use.graph_kind}`)));
          const link = make("a", "", `${use.node_name || t("agents.page.usage_unnamed_node")} · ${use.graph_name}`);
          link.href = `/${use.graph_kind === "pipeline" ? "pipelines" : "actions"}/${encodeURIComponent(use.graph_slug)}${use.in_draft ? `?select=${encodeURIComponent(use.node_id)}&agent=${encodeURIComponent(agent.id)}` : ""}`;
          item.append(link);
          if (use.in_draft && !use.published) item.append(chip(t("agents.page.usage_draft")));
          if (!use.in_draft) item.append(chip(t("agents.page.usage_only_published", { number: use.published_number })));
          if (use.overrides.length) item.append(chip(tn("agents.page.usage_overrides", use.overrides.length)));
          return item;
        }),
      );
      if (!uses.length) list.append(make("li", "mg-card__facts", t("agents.page.usage_none")));
    })
    .catch(() => list.replaceChildren(make("li", "mg-card__facts", t("agents.list_page.agents_could_not_be_loaded"))));
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
    placeholder: t("agents.page.select"),
    icon: () => "agent",
    title: (agent) => agent.name,
    chips: chipsOf,
    tabs: () => [
      { key: "overview", label: t("graph_list.tab_overview"), render: overview },
      { key: "usage", label: t("graph_list.tab_usage"), render: usage },
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
