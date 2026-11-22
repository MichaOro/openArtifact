/* The inspector of an agent node: which agent it runs, how the agent's inputs are fed from the run,
 * and the settings. Every setting shows the agent's value ("From agent") until the node sets its own
 * ("Overridden"); "Reset" removes the node's value again. What is in effect is asked from the server
 * (POST /api/agents/{id}/preview with the node), which resolves it the same way a run does, so the
 * panel never computes inheritance itself. */
import { getAgent, listAgents, listProviders, previewAgent } from "../agents/api.js";
import { OVERRIDES, formatMapping, mappingRows, overridesOf, showValue, usableModels } from "../agents/model.js";
import { chip, el, problemList } from "../agents/view.js";
import { field } from "./field.js";
import { rememberAgents } from "./node-types.js";
import { suggestReferences } from "./reference-suggest.js";
import { createControl, settingValue } from "./setting-controls.js";

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
      this.element.replaceChildren(el("p", "ge-inspector__note", "The agents could not be loaded. Select the node again to retry."));
      return;
    }
    const agentId = this.config.agent_id || "";
    const agent = agents.find((a) => a.id === agentId) ?? null;
    const parts = [this.#agentSelect(agents, agentId)];
    if (agent) {
      let preview = null;
      let detail = null;
      try {
        detail = await getAgent(agent.id);
        if (agent.published_number != null) preview = await previewAgent(agent.id, { source: "published", node_id: this.node.id });
      } catch (error) {
        parts.push(el("p", "ge-inspector__note", error.detail ?? error.message));
      }
      parts.push(this.#status(agent));
      if (preview) {
        if (preview.problems.length) parts.push(problemList(preview.problems));
        parts.push(this.#inputs(detail.published.inputs), this.#settings(preview, providers));
      }
    } else if (agentId) {
      parts.push(problemList(["The chosen agent does not exist any more. Choose another one."]));
    }
    const failure = this.setting("on_failure");
    parts.push(createControl(failure, settingValue(this.node, failure), (value) => this.editor.saveSetting(this.node, failure, value)).element);
    this.element.replaceChildren(...parts);
    if (focusKey) this.element.querySelector(`[data-focus-key="agent-${focusKey}"]`)?.focus();
  }

  #agentSelect(agents, agentId) {
    const select = el("select", "field__control");
    select.dataset.focusKey = "agent-agent_id";
    select.append(new Option("Choose an agent", ""));
    for (const agent of agents) {
      const flags = [agent.active ? null : "inactive", agent.published_number == null ? "not published" : null].filter(Boolean);
      select.append(new Option(flags.length ? `${agent.name} (${flags.join(", ")})` : agent.name, agent.id));
    }
    if (agentId && !agents.some((a) => a.id === agentId)) select.append(new Option("(deleted agent)", agentId));
    select.value = agentId;
    select.addEventListener("change", async () => {
      const message = await this.save("agent_id", select.value || null);
      if (message) this.editor.showError(message);
    });
    return field("Agent", select);
  }

  #status(agent) {
    const line = el("p", "ag-node__status");
    const link = el("a", "", "Open agent");
    link.href = `/agents/${encodeURIComponent(agent.id)}`;
    const state = [
      agent.published_number == null ? "Nothing is published yet: the node will fail." : `Runs version ${agent.published_number} (the version published when an execution starts).`,
      agent.active ? null : "The agent is inactive: the node will fail.",
    ].filter(Boolean);
    line.append(document.createTextNode(`${state.join(" ")} `), link);
    return line;
  }

  /** One field per input the agent declares; the value may hold ${node...}, ${var...} or ${card...}. */
  #inputs(declared) {
    const wrap = el("div", "ge-inspector__section");
    wrap.append(el("h3", "", "Inputs"));
    const rows = mappingRows(declared, this.config.inputs ?? "");
    if (!rows.length) wrap.append(el("p", "ge-inspector__note", "This agent declares no inputs."));
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
      input.placeholder = row.required ? "${node.NAME.output}" : row.default != null ? `default: ${row.default}` : "empty";
      input.addEventListener("change", commit);
      input.addEventListener("keydown", (event) => event.key === "Enter" && commit());
      const suggest = this.editor.suggestions?.(this.node);
      if (suggest) suggestReferences(input, suggest, { allowSecrets: false });
      fields.set(row.name, input);
      const label = row.declared ? `${row.name}${row.required ? " *" : ""} (${row.type})` : `${row.name} (not declared by the agent: clear it)`;
      wrap.append(field(label, input));
    }
    wrap.append(error);
    return wrap;
  }

  #settings(preview, providers) {
    const wrap = el("div", "ge-inspector__section");
    const head = el("h3", "", "Settings");
    wrap.append(head, el("p", "ge-inspector__note", "Each setting follows the agent until this node sets its own value."));
    const states = new Map(preview.settings.map((s) => [s.key, s]));
    const provider = providers.find((p) => p.name === preview.provider) ?? null;
    for (const override of OVERRIDES) wrap.append(this.#override(override, states.get(override.key), providers, provider));
    const set = overridesOf(this.config);
    if (set.length) {
      const all = el("button", "button button--ghost button--sm", `Reset all ${set.length} overrides`);
      all.type = "button";
      all.dataset.focusKey = "agent-reset-all";
      all.addEventListener("click", async () => {
        for (const key of set) await this.save(key, null, { redraw: false });
        this.opening.clear();
        await this.render("reset-all");
      });
      wrap.append(all);
    }
    return wrap;
  }

  /** One setting: the agent's value, or the node's own with its control and "Reset". */
  #override(override, state, providers, provider) {
    const { key, label } = override;
    const overridden = state.overridden || this.opening.has(key);
    const box = el("div", "ag-override");
    box.dataset.overridden = String(overridden);
    box.dataset.setting = key;
    const head = el("div", "ag-override__head");
    const toggle = el("button", "button button--ghost button--sm", overridden ? "Reset" : "Override");
    toggle.type = "button";
    toggle.dataset.focusKey = `agent-${key}`;
    toggle.setAttribute("aria-label", overridden ? `Reset ${label} to the agent's value` : `Override ${label} in this node`);
    head.append(el("span", "ag-override__label", label), chip(overridden ? "Overridden" : "From agent", overridden ? "accent" : ""), toggle);
    box.append(head);
    const inherited = showValue(this.#shown(key, state.inherited, providers), override.kind);
    const error = el("p", "field__error");
    error.setAttribute("role", "alert");
    error.hidden = true;
    const fail = (message) => {
      error.textContent = message ?? "";
      error.hidden = !message;
    };
    if (!overridden) {
      box.append(el("p", "ag-override__inherited", inherited));
      toggle.addEventListener("click", async () => {
        const start = this.#startValue(override, state.inherited);
        if (start === null) {
          this.opening.add(key); // nothing to copy: show the control and save what is entered
          await this.render(key);
        } else fail(await this.save(key, start));
      });
      box.append(error);
      return box;
    }
    toggle.addEventListener("click", async () => {
      this.opening.delete(key);
      if (state.overridden) fail(await this.save(key, null));
      else await this.render(key);
    });
    const control = this.#control(override, state.overridden ? state.value : null, providers, provider, async (value) => {
      const message = await this.save(key, value, { redraw: false });
      fail(message);
      if (!message) {
        this.opening.delete(key);
        if (!state.overridden || override.kind === "provider") await this.render(key);
      }
    });
    control.setAttribute("aria-label", label);
    box.append(control, el("p", "ag-override__inherited", `Agent: ${inherited}`), error);
    return box;
  }

  /** A provider is stored by id and shown by name. */
  #shown(key, value, providers) {
    return key === "provider_id" && value ? (providers.find((p) => p.id === value)?.name ?? "(deleted provider)") : value;
  }

  /** What an override starts with: the agent's value where there is one to copy, else null (ask). */
  #startValue(override, inherited) {
    if (override.kind === "switch") return !inherited; // overriding a switch means the other position
    if (inherited === null || inherited === undefined || inherited === "") return null;
    return inherited;
  }

  #control(override, value, providers, provider, commit) {
    const { kind } = override;
    if (kind === "switch") {
      const button = el("button", "ge-switch");
      button.type = "button";
      button.setAttribute("role", "switch");
      button.setAttribute("aria-checked", String(Boolean(value)));
      button.append(el("span", "ge-switch__state", value ? "On" : "Off"), el("span", "ge-switch__thumb"));
      button.addEventListener("click", () => commit(!value));
      return button;
    }
    if (kind === "provider" || kind === "model") {
      const select = el("select", "field__control");
      const options = kind === "provider" ? providers.map((p) => [p.id, p.name]) : usableModels(provider).map((id) => [id, id]);
      select.append(new Option(kind === "provider" ? "Choose a provider" : "Choose a model", ""));
      for (const [id, text] of options) select.append(new Option(text, id));
      if (value && !options.some(([id]) => id === value)) select.append(new Option(`${value} (not available)`, value));
      select.value = value ?? "";
      select.addEventListener("change", () => select.value && commit(select.value));
      return select;
    }
    if (kind === "lines") {
      const area = Object.assign(el("textarea", "field__control field__control--lines"), { rows: 5, value: value ?? "", spellcheck: false });
      area.addEventListener("change", () => area.value !== "" && commit(area.value));
      return area;
    }
    const input = Object.assign(el("input", "field__control"), { type: "number", value: value ?? "", min: String(override.min), max: String(override.max), step: String(override.step ?? 1) });
    const send = () => {
      const number = Number(input.value);
      if (input.value.trim() === "" || Number.isNaN(number)) return;
      commit(kind === "integer" ? Math.round(number) : number);
    };
    input.addEventListener("change", send);
    input.addEventListener("keydown", (event) => event.key === "Enter" && send());
    return input;
  }
}

/** The inspector block of an agent node. */
export function agentBlock(node, type, editor) {
  return new AgentBlock(node, type, editor).element;
}
