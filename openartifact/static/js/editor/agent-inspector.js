/* The inspector of an agent node: which agent it runs and how the agent's inputs are fed from the run (drawn here,
 * because only an agent has them), and the settings, which the shared layout draws (settings-layout.js): every
 * setting the agent supplies shows the agent's value ("Inherited") until the node sets its own ("Overridden").
 * What is in effect is asked from the server (POST /api/agents/{id}/preview with the node), which resolves it the
 * same way a run does, so the panel never computes inheritance itself. */
import { getAgent, listAgents, listProviders, previewAgent } from "../agents/api.js";
import { fieldNames, formatMapping, mappingRows, preview as oneLine, showValue, usableModels } from "../agents/model.js"; // `oneLine`: `preview` is also a name of the server's answer here
import { el, problemList } from "../agents/view.js";
import { icon } from "../components/icons.js";
import { infoTip } from "../components/info-tip.js";
import { field } from "./field.js";
import { rememberAgents } from "./node-types.js";
import { persistText, whenFieldFree } from "./persist-policy.js";
import { ReferenceNames } from "./reference-names.js";
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
      this.#versionBadge(agent, detail);
      const status = this.#status(agent);
      if (status) extras.push(status);
      if (preview) {
        if (preview.problems.length) extras.push(problemList(preview.problems));
        const inputs = this.#inputs(detail.published.inputs);
        if (inputs) extras.push(inputs);
      }
    } else if (agentId) {
      extras.push(problemList([t("editor.agent_inspector.chosen_agent_does_not_exist")]));
    }
    const inherits = this.type.settings.filter((s) => s.inherits).map((s) => s.key);
    // never under a focused text field: the draw waits until the field is left (persist-policy.js)
    whenFieldFree(this.element, () => this.element.replaceChildren(
      buildSettings({
        node: this.node,
        editor: this.editor,
        suggest: this.editor.suggestions?.(this.node) ?? null,
        // the switch "Use system prompt" is not drawn: setting a system prompt of its own switches it on (the agent's own
        // editor has the switch); without a published agent nothing is inherited
        skip: preview ? ["agent_id", "inputs", "system_prompt_enabled"] : ["agent_id", "inputs", "system_prompt_enabled", ...inherits],
        extras,
        inheritance: preview ? this.#inheritance(preview, providers) : null,
      }),
    ));
    const panel = this.element.closest("[data-refocus]");
    const fresh = panel && Date.now() - Number(panel.dataset.refocusAt) < 3000;
    const wanted = focusKey ? `agent-${focusKey}` : fresh ? panel.dataset.refocus : null; // the panel drew while this block was still on its way
    if (wanted) this.element.querySelector(`[data-focus-key="${wanted}"]`)?.focus();
  }

  /** The agent's side of the settings: what is in effect, as the server resolves it. */
  #inheritance(preview, providers) {
    const states = new Map(preview.settings.map((s) => [s.key, s]));
    const provider = providers.find((p) => p.name === preview.provider) ?? null;
    return {
      source: t("common.agent"),
      state: (key) => states.get(key) ?? null,
      show: (setting, value) => (Array.isArray(value) ? fieldNames(value) : oneLine(showValue(this.#shown(setting.key, value, providers), setting.type === "lines" ? "lines" : ""))),
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

  /** What is wrong with the agent for this node (nothing published, inactive); nothing when all is well. */
  #status(agent) {
    const state = [
      agent.published_number == null ? t("editor.agent_inspector.nothing_published_yet_node_will") : null,
      agent.active ? null : t("editor.agent_inspector.agent_inactive_node_will_fail"),
    ].filter(Boolean);
    return state.length ? el("p", "ag-node__status", state.join(" ")) : null;
  }

  /** The version the node runs, as a small badge next to the close button of the window: the time it was published
   * on hover, and a click (after a question) opens the agent's own editor. */
  #versionBadge(agent, detail) {
    const header = this.element.closest("dialog")?.querySelector(".modal__header");
    if (!header) return;
    header.querySelector("[data-node-version]")?.remove();
    if (agent.published_number == null) return;
    const published = detail?.versions?.find((v) => v.number === agent.published_number)?.published_at;
    const when = published ? new Date(published).toLocaleString(document.documentElement.lang || undefined) : null;
    const badge = el("button", "chip-button", `v${agent.published_number}`);
    badge.type = "button";
    badge.dataset.nodeVersion = "";
    badge.title = when ? t("editor.agent_inspector.version_published_at", { when }) : t("editor.agent_inspector.version_published");
    badge.setAttribute("aria-label", `${badge.title}. ${t("editor.agent_inspector.open_agent")}`);
    badge.addEventListener("click", () =>
      this.editor.confirm({
        title: t("editor.agent_inspector.open_agent"),
        message: t("editor.agent_inspector.open_agent_question", { agent: agent.name }),
        confirmLabel: t("editor.agent_inspector.open_agent"),
        tone: "primary",
        onConfirm: async () => {
          window.location.href = `/agents/${encodeURIComponent(agent.id)}`;
        },
      }),
    );
    header.prepend(badge);
  }

  /**
   * The inputs of the agent, as this node sees them: the ones that come from the artifact are fixed by the agent (shown, not
   * editable), the ones that take a value have a field (typed text or a reference such as ${card.title}), a line left
   * over for an input that now comes from the artifact is shown as ignored, and a name the agent no longer declares can be removed.
   */
  #inputs(declared) {
    const rows = mappingRows(declared, this.config.inputs ?? "");
    // what the agent fixes (inputs of the artifact) is not listed: with nothing else to map the section is not there
    if (declared.length && !rows.value.length && !rows.stale.length && !rows.undeclared.length) return null;
    const wrap = el("div", "ge-inspector__section");
    const head = el("h3", "ge-inspector__heading-tip");
    head.append(document.createTextNode(t("common.inputs")), infoTip(t("editor.agent_inspector.inputs_help"), { label: t("common.inputs") }).button);
    wrap.append(head);
    if (!declared.length) wrap.append(el("p", "ge-inspector__note", t("editor.agent_inspector.agent_declares_no_inputs")));
    const fields = new Map();
    const error = el("p", "field__error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const commit = async () => {
      const mapping = Object.fromEntries([...fields].map(([name, input]) => [name, input.names ? input.names.stored(input.value) : input.value]));
      const message = await this.save("inputs", formatMapping(mapping) || null, { redraw: false });
      error.textContent = message ?? "";
      error.hidden = !message;
      if (!message) await this.render();
      return message;
    };
    const unsavedText = t("agents.editor_page.not_saved");
    const mapped = (value, focusName) => {
      const input = Object.assign(el("input", "field__control"), { type: "text", value, autocomplete: "off", spellcheck: false });
      input.dataset.focusKey = `agent-input-${focusName}`;
      const suggest = this.editor.suggestions?.(this.node);
      if (suggest) {
        input.names = new ReferenceNames(() => suggest.nodes()); // the field shows the names of the nodes it refers to, never their ids
        input.value = input.names.display(value);
        suggestReferences(input, suggest, { allowSecrets: false });
      }
      persistText(input, async () => commit(), { unsavedText });
      fields.set(focusName, input);
      return input;
    };
    for (const row of rows.value) {
      const input = mapped(row.value, row.name);
      input.placeholder = row.required ? t("editor.agent_inspector.type_value_or_reference") : row.default != null ? t("editor.agent_inspector.default_value", { value: row.default }) : t("common.empty");
      const box = field(t("editor.agent_inspector.value_for", { name: row.name }), input);
      const facts = [row.type, row.required ? t("common.required") : t("agents.editor_page.optional"), row.description].filter(Boolean).join(" · ");
      box.append(el("p", "field__help", facts));
      wrap.append(box);
    }
    const removable = (row, text) => {
      // a line the run ignores or fails on is shown, and it can be removed
      const input = mapped(row.value, row.name);
      const remove = el("button", "button button--ghost button--sm is-danger");
      remove.type = "button";
      remove.dataset.focusKey = `agent-input-remove-${row.name}`;
      remove.setAttribute("aria-label", t("editor.agent_inspector.remove_mapping_of", { name: row.name }));
      remove.append(icon("trash"), document.createTextNode(t("editor.agent_inspector.remove_mapping")));
      remove.addEventListener("click", () => {
        fields.delete(row.name);
        commit();
      });
      const stale = el("div", "ag-node__stale");
      stale.append(field(text, input), remove);
      wrap.append(stale);
    };
    for (const row of rows.stale) removable(row, t("editor.agent_inspector.stale_line", { name: row.name }));
    for (const row of rows.undeclared) removable(row, t("editor.agent_inspector.name_not_declared_by_agent", { name: row.name }));
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
