/* The inspector of an agent node: which agent it runs and how the agent's inputs are fed from the run (drawn here,
 * because only an agent has them), and the settings, which the shared layout draws (settings-layout.js): every
 * setting the agent supplies shows the agent's value ("Inherited") until the node sets its own ("Overridden").
 * What is in effect is asked from the server (POST /api/agents/{id}/preview with the node), which resolves it the
 * same way a run does, so the panel never computes inheritance itself. */
import { getAgent, listAgents, listProviders, previewAgent } from "../agents/api.js";
import { formatMapping, mappingRows, showValue, usableModels } from "../agents/model.js";
import { el, problemList } from "../agents/view.js";
import { field } from "./field.js";
import { rememberAgents } from "./node-types.js";
import { suggestReferences } from "./reference-suggest.js";
import { buildSettings } from "./settings-layout.js";
import { t } from "../i18n.js";

let agentsPromise = null;
let providersPromise = null;

/** The agents and providers, fetched once per page and again after `forget()`. */
function lists() {
  agentsPromise ??= listAgents().then((agents) => {
    rememberAgents(agents);
    return agents;
  });
  providersPromise ??= listProviders();
  return Promise.all([agentsPromise, providersPromise]);
}

export function forget() {
  agentsPromise = null;
  providersPromise = null;
}

/** Load the agent names once, so the cards of a graph can show them (best effort). */
export async function loadAgentNames() {
  try {
    await lists();
  } catch {
    forget();
  }
}

class AgentBlock {
  /**
   * @param {object} node the agent node
   * @param {object} type the node's kind (its settings as the server describes them)
   * @param {object} editor saveSetting(node, setting, value), suggestions(node), showError(message)
   */
  constructor(node, type, editor) {
    this.node = node;
    this.type = type;
    this.editor = editor;
    this.element = el("div", "ge-inspector__section ag-node");
    /** Settings the user is about to override (the control is shown, nothing is saved yet). */
    this.opening = new Set();
    this.render();
  }

  setting(key) {
    return this.type.settings.find((s) => s.key === key);
  }

  get config() {
    return this.node.config ?? {};
  }

  /** Save one setting; draw the block again when the server took it. Resolves to the refusal, or null. */
  async save(key, value, { redraw = true } = {}) {
    const message = await this.editor.saveSetting(this.node, this.setting(key), value);
    if (!message && redraw) await this.render(key);
    return message;
  }

  async render(focusKey = null) {
    let agents = [];
    let providers = [];
    try {
      [agents, providers] = await lists();
    } catch {
      forget();
      this.element.replaceChildren(el("p", "ge-inspector__note", t("editor.agent_inspector.agents_could_not_be_loaded")));
      return;
    }
    const agentId = this.config.agent_id || "";
    const agent = agents.find((a) => a.id === agentId) ?? null;
    const extras = [this.#agentSelect(agents, agentId)];
    let preview = null;
    if (agent) {
      let detail = null;
      try {
        detail = await getAgent(agent.id);
        if (agent.published_number != null) preview = await previewAgent(agent.id, { source: "published", node_id: this.node.id });
      } catch (error) {
        extras.push(el("p", "ge-inspector__note", error.detail ?? error.message));
      }
      extras.push(this.#status(agent));
      if (preview) {
        if (preview.problems.length) extras.push(problemList(preview.problems));
        extras.push(this.#inputs(detail.published.inputs));
      }
    } else if (agentId) {
      extras.push(problemList([t("editor.agent_inspector.chosen_agent_does_not_exist")]));
    }
    const inherits = this.type.settings.filter((s) => s.inherits).map((s) => s.key);
    this.element.replaceChildren(
      buildSettings({
        node: this.node,
        editor: this.editor,
        suggest: this.editor.suggestions?.(this.node) ?? null,
        skip: preview ? ["agent_id", "inputs"] : ["agent_id", "inputs", ...inherits], // without a published agent nothing is inherited
        extras,
        inheritance: preview ? this.#inheritance(preview, providers) : null,
      }),
    );
    if (focusKey) this.element.querySelector(`[data-focus-key="agent-${focusKey}"]`)?.focus();
  }

  /** The agent's side of the settings: what is in effect, as the server resolves it. */
  #inheritance(preview, providers) {
    const states = new Map(preview.settings.map((s) => [s.key, s]));
    const provider = providers.find((p) => p.name === preview.provider) ?? null;
    return {
      source: t("common.agent"),
      state: (key) => states.get(key) ?? null,
      show: (setting, value) => showValue(this.#shown(setting.key, value, providers), setting.type === "lines" ? "lines" : ""),
      // a provider and a model are stored by id and chosen from lists the page knows
      setting: (setting) => {
        if (setting.key === "provider_id") return { ...setting, type: "select", choices: providers.map((p) => [p.id, p.name]), emptyLabel: "Choose a provider" };
        if (setting.key === "model") return { ...setting, type: "select", choices: usableModels(provider).map((id) => [id, id]), emptyLabel: "Choose a model" };
        return setting;
      },
      refresh: () => this.render(),
    };
  }

  #agentSelect(agents, agentId) {
    const select = el("select", "field__control");
    select.dataset.focusKey = "agent-agent_id";
    select.append(new Option(t("editor.agent_inspector.choose_agent"), ""));
    for (const agent of agents) {
      const flags = [agent.active ? null : "inactive", agent.published_number == null ? t("editor.agent_inspector.not_published") : null].filter(Boolean);
      select.append(new Option(flags.length ? `${agent.name} (${flags.join(", ")})` : agent.name, agent.id));
    }
    if (agentId && !agents.some((a) => a.id === agentId)) select.append(new Option(t("editor.agent_inspector.deleted_agent"), agentId));
    select.value = agentId;
    select.addEventListener("change", async () => {
      const message = await this.save("agent_id", select.value || null);
      if (message) this.editor.showError(message);
    });
    return field(t("common.agent"), select);
  }

  #status(agent) {
    const line = el("p", "ag-node__status");
    const link = el("a", "", t("editor.agent_inspector.open_agent"));
    link.href = `/agents/${encodeURIComponent(agent.id)}`;
    const state = [
      agent.published_number == null ? t("editor.agent_inspector.nothing_published_yet_node_will") : t("editor.agent_inspector.runs_version_published_number_version", { published_number: agent.published_number }),
      agent.active ? null : t("editor.agent_inspector.agent_inactive_node_will_fail"),
    ].filter(Boolean);
    line.append(document.createTextNode(`${state.join(" ")} `), link);
    return line;
  }

  /** One field per input the agent declares; the value may hold ${node...}, ${var...} or ${card...}. */
  #inputs(declared) {
    const wrap = el("div", "ge-inspector__section");
    wrap.append(el("h3", "", t("common.inputs")));
    const rows = mappingRows(declared, this.config.inputs ?? "");
    if (!rows.length) wrap.append(el("p", "ge-inspector__note", t("editor.agent_inspector.agent_declares_no_inputs")));
    const fields = new Map();
    const error = el("p", "field__error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const commit = async () => {
      const mapping = Object.fromEntries([...fields].map(([name, input]) => [name, input.value]));
      const message = await this.save("inputs", formatMapping(mapping) || null, { redraw: false });
      error.textContent = message ?? "";
      error.hidden = !message;
      if (!message) await this.render();
    };
    for (const row of rows) {
      const input = Object.assign(el("input", "field__control"), { type: "text", value: row.value, autocomplete: "off", spellcheck: false });
      input.dataset.focusKey = `agent-input-${row.name}`;
      input.placeholder = row.required ? "${(Node name).output}" : row.default != null ? t("editor.agent_inspector.default_value", { value: row.default }) : t("common.empty");
      input.addEventListener("change", commit);
      input.addEventListener("keydown", (event) => event.key === "Enter" && commit());
      const suggest = this.editor.suggestions?.(this.node);
      if (suggest) suggestReferences(input, suggest, { allowSecrets: false });
      fields.set(row.name, input);
      const label = row.declared ? `${row.name}${row.required ? " *" : ""} (${row.type})` : t("editor.agent_inspector.name_not_declared_by_agent", { name: row.name });
      wrap.append(field(label, input));
    }
    wrap.append(error);
    return wrap;
  }

  /** A provider is stored by id and shown by name. */
  #shown(key, value, providers) {
    return key === "provider_id" && value ? (providers.find((p) => p.id === value)?.name ?? "(deleted provider)") : value;
  }
}

/** The inspector block of an agent node. */
export function agentBlock(node, type, editor) {
  return new AgentBlock(node, type, editor).element;
}
