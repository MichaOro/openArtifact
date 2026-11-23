/* The page of one agent (ADR-045): a header with the draft's state and Save / Discard / Publish, tabs for
 * the areas and an options panel that switches the optional ones on. Prompts and "Versions & use" are always
 * there; Inputs and Model & Limits are tabs while their switch (part of the draft) is on; the system prompt
 * shows inside Prompts; Quick test is a tab that lives only while the page is open. The form edits the draft
 * only; nothing an execution uses changes before "Publish". */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { OptionsPanel } from "../components/options-panel.js";
import { SettingsGroup, numberSetting } from "../components/settings-group.js";
import { Switch } from "../components/switch.js";
import { Tabs } from "../components/tabs.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { agentUses, discardDraft, getAgent, listProviders, previewAgent, publishAgent, republishVersion, saveDraft, updateAgent } from "./api.js";
import { agentChips, fieldLabel, optionsOf, providerInEffect, sampleHint, usableModels } from "./model.js";
import { chip, configFacts, el, previewView, problemList } from "./view.js";

const root = document.querySelector("[data-agent-editor]");
const missing = document.querySelector("[data-agent-missing]");
const ref = root.dataset.agentRef;
const banner = new AlertBar();
const nameDialog = new FormDialog(new Modal(document.getElementById("name-modal")));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const $ = (selector) => root.querySelector(selector);
const control = (key) => root.querySelector(`[data-field="${key}"]`);

const NUMBERS = ["temperature", "max_tokens", "request_timeout_seconds", "total_timeout_seconds", "retries", "max_iterations"];
const ORIGINS = { user: "in the browser", api: "through the API" };

let agent = null;
let providers = [];
let dirty = false;
let fieldCount = 0;

// ── tabs and options ───────────────────────────────────────────────────

const tabs = new Tabs($("[data-ag-tabs]"));
const TAB_OF = { inputs: "inputs", limits: "limits" };
const options = new OptionsPanel(
  $("[data-options]"),
  [
    { key: "system_prompt", label: "System prompt", help: "Adds a system prompt below the user prompt. Switched off it is kept but not sent." },
    { key: "inputs", label: "Inputs", help: "Values the agent needs from a run, used as ${input.NAME}. Switched off they are kept but the agent has none." },
    { key: "limits", label: "Model & Limits", help: "Choose the provider, the model and the limits. Switched off they are kept and the defaults apply." },
    { key: "test", label: "Quick test", help: "Fill the prompts with example values for the inputs. Not saved: it is off whenever this page opens." },
  ],
  (key, on) => {
    showOption(key, on);
    if (key === "inputs") renderSamples();
    if (key !== "test") changed(); // the other switches are part of the draft
  },
);

/** Show what an option switches: the system prompt field, the Quick test card, or a tab (activating does not jump to it). */
function showOption(key, on) {
  if (key === "system_prompt") $("[data-system-field]").hidden = !on;
  else if (key === "test") $("[data-quick-test]").hidden = !on;
  else tabs.setVisible(TAB_OF[key], on);
}

const active = new Switch($("[data-active]"));

// ── Model & Limits: two cards of optional settings (ADR-046); a setting not added is "not set" ──

const selectSetting = (key, label, hint, fallback) => ({
  key,
  label,
  hint,
  fallback,
  create: () => el("select", "field__control"),
  read: (select) => select.value || null,
  write: () => {}, // filled by onAdd and fillModelSelects
});
const modelGroup = new SettingsGroup(
  $('[data-settings="model"]'),
  [
    selectSetting("provider_id", "Provider", "Where the requests go.", "the default provider"),
    selectSetting("model", "Model", "The model of the provider.", "the provider's default model"),
    numberSetting("temperature", "Temperature", { min: 0, max: 2, step: 0.1, hint: "0 to 2.", fallback: "the model's own" }),
    numberSetting("max_tokens", "Max tokens", { min: 1, max: 8192, hint: "1 to 8192.", fallback: "the model's own" }),
  ],
  {
    onChange: () => {
      fillModelSelects(readValue("provider_id"), readValue("model"));
      changed();
    },
    onAdd: (key, select) => {
      if (key === "provider_id") select.addEventListener("change", () => fillModelSelects(select.value || null, null));
    },
  },
);
const limitsGroup = new SettingsGroup(
  $('[data-settings="limits"]'),
  [
    // by importance: the time limit guards every run, the iterations only matter with tools
    numberSetting("total_timeout_seconds", "Node time limit", { min: 1, max: 1800, hint: "Seconds, 1 to 1800; covers all attempts and waits.", fallback: 600, unit: " s" }),
    numberSetting("max_iterations", "Max iterations", { min: 1, max: 50, hint: "1 to 50; how many requests a node may make while the model calls tools. Only with tools.", fallback: 10, unit: ", only with tools" }),
    numberSetting("retries", "Retries", { min: 0, max: 4, hint: "0 to 4.", fallback: 3 }),
    numberSetting("request_timeout_seconds", "Request timeout", { min: 1, max: 300, hint: "Seconds, 1 to 300; one attempt.", fallback: 60, unit: " s" }),
  ],
  { onChange: () => changed() },
);

/** The value of a Model & Limits setting as the cards hold it (null: not added). */
function readValue(key) {
  return { ...modelGroup.read(), ...limitsGroup.read() }[key];
}

const inputMenu = new ActionMenu();

/** A select of fixed choices ([value, text]); the Type and the Required column use it. */
function choiceSelect(choices, value, label, key) {
  const select = el("select", "field__control");
  for (const [option, text] of choices) select.append(new Option(text, option));
  select.value = value;
  select.setAttribute("aria-label", label);
  select.dataset.input = key;
  return select;
}

function textInput(value, label, key, extra = {}) {
  const input = Object.assign(el("input", "field__control"), { type: "text", value: value ?? "", autocomplete: "off", ...extra });
  input.setAttribute("aria-label", label);
  input.dataset.input = key;
  return input;
}

/** One row of the inputs table: name, type, required or optional, default, the description if it has one, and its menu. */
function inputRow(input = { name: "", type: "string", required: false, default: null, description: "" }) {
  const row = el("li", "ag-input");
  const name = textInput(input.name, "Name", "name", { maxLength: 32, placeholder: "ticket", spellcheck: false });
  const type = choiceSelect([["string", "string"], ["number", "number"], ["boolean", "boolean"]], input.type, "Type", "type");
  const required = choiceSelect([["required", "Required"], ["optional", "Optional"]], input.required ? "required" : "optional", "Required", "required");
  required.classList.add("ag-input__required");
  const fallback = textInput(input.default == null ? "" : String(input.default), "Default", "default");
  const description = el("div", "ag-input__description");
  const more = el("button", "icon-button icon-button--sm ag-input__more");
  more.type = "button";
  more.setAttribute("aria-label", "Input actions");
  more.title = "Input actions";
  more.setAttribute("aria-haspopup", "menu");
  more.append(icon("more"));
  const sync = () => {
    const isRequired = required.value === "required";
    fallback.disabled = isRequired; // a required input has no default: the node must map it
    fallback.placeholder = isRequired ? "—" : "";
    if (isRequired) fallback.value = "";
  };
  required.addEventListener("change", sync);
  sync();
  more.addEventListener("click", () => {
    const has = Boolean(description.firstChild);
    inputMenu.toggle(
      more,
      [
        has
          ? { label: "Remove description", icon: "x", onSelect: () => setDescription(row, null) }
          : { label: "Add description", icon: "plus", onSelect: () => setDescription(row, "") },
        { label: "Remove input", icon: "trash", danger: true, onSelect: () => removeInput(row) },
      ],
      `Input ${name.value || ""}`.trim(),
    );
  });
  row.append(name, type, required, fallback, description, more);
  if (input.description) setDescription(row, input.description, { quiet: true });
  name.addEventListener("change", renderSamples);
  return row;
}

/** Give a row a description field (text) or take it away (null); the column follows the data. */
function setDescription(row, text, { quiet = false } = {}) {
  const cell = row.querySelector(".ag-input__description");
  if (text === null) cell.replaceChildren();
  else {
    const field = textInput(text, "Description", "description", { maxLength: 200 });
    cell.replaceChildren(field);
    if (!quiet) field.focus();
  }
  showDescriptionColumn();
  if (!quiet) changed();
}

function removeInput(row) {
  row.remove();
  showDescriptionColumn();
  changed();
  renderSamples();
}

/** The Description column is there while any input has a description (derived, never stored). */
function showDescriptionColumn() {
  const any = [...$("[data-inputs]").children].some((row) => row.querySelector('[data-input="description"]'));
  $("[data-inputs-table]").classList.toggle("has-description", any);
}

/** The inputs as the form has them; a default is sent in the input's own type. */
function readInputs() {
  return [...$("[data-inputs]").children].map((row) => {
    const get = (key) => row.querySelector(`[data-input="${key}"]`);
    const type = get("type").value;
    const raw = get("default").value.trim();
    let fallback = raw === "" ? null : raw;
    if (fallback !== null && type === "number" && !Number.isNaN(Number(raw))) fallback = Number(raw);
    if (fallback !== null && type === "boolean" && ["true", "false"].includes(raw.toLowerCase())) fallback = raw.toLowerCase() === "true";
    const required = get("required").value === "required";
    return { name: get("name").value.trim(), type, required, default: required ? null : fallback, description: get("description")?.value.trim() ?? "" };
  });
}

function readConfig() {
  const config = {
    system_prompt_enabled: options.get("system_prompt"),
    inputs_enabled: options.get("inputs"),
    limits_enabled: options.get("limits"),
    system_prompt: control("system_prompt").value,
    user_prompt: control("user_prompt").value,
    inputs: readInputs(),
    ...modelGroup.read(), // a setting that is not added is null: not set, the default applies
    ...limitsGroup.read(),
  };
  return config;
}

/** Fill the provider and model selects that are added (the model list follows the provider in effect). */
function fillModelSelects(providerId, model) {
  const providerSelect = modelGroup.control("provider_id");
  if (providerSelect) fillProviders(providerSelect, providerId);
  const modelSelect = modelGroup.control("model");
  if (modelSelect) fillModels(modelSelect, providerId, model);
}

function fillModels(select, providerId, selected) {
  const provider = providerInEffect(providers, providerId);
  const models = usableModels(provider);
  const fallback = provider?.default_model ? `Default of the provider (${provider.default_model})` : "Default of the provider (none set)";
  select.replaceChildren(new Option(provider ? fallback : "No provider", ""), ...models.map((id) => new Option(id, id)));
  if (selected && !models.includes(selected)) select.append(new Option(`${selected} (not enabled)`, selected));
  select.value = selected ?? "";
}

function fillProviders(select, selected) {
  const fallback = providers.find((p) => p.is_default);
  select.replaceChildren(new Option(fallback ? `Default provider (${fallback.name})` : "Default provider (none set)", ""), ...providers.map((p) => new Option(p.name, p.id)));
  if (selected && !providers.some((p) => p.id === selected)) select.append(new Option("(deleted provider)", selected));
  select.value = selected ?? "";
}

function fillForm(config) {
  for (const [key, on] of Object.entries(optionsOf(config))) {
    options.set(key, on);
    showOption(key, on);
  }
  control("system_prompt").value = config.system_prompt;
  control("user_prompt").value = config.user_prompt;
  $("[data-inputs]").replaceChildren(...config.inputs.map((input) => inputRow(input)));
  showDescriptionColumn();
  modelGroup.load(config);
  limitsGroup.load(config);
  fillModelSelects(config.provider_id, config.model);
  dirty = false;
  renderSamples();
}

/** Example values for the Quick test: one field per input with a grey example of what goes in; what was typed is kept. */
function renderSamples() {
  const host = $("[data-preview-values]");
  const typed = Object.fromEntries([...host.querySelectorAll("[data-sample]")].map((input) => [input.dataset.sample, input.value]));
  const inputs = options.get("inputs") ? readInputs().filter((input) => input.name) : [];
  $("[data-quick-empty]").hidden = inputs.length > 0;
  host.replaceChildren(
    ...inputs.map((input) => {
      const wrap = el("div", "field");
      const field = Object.assign(el("input", "field__control"), { type: "text", value: typed[input.name] ?? "", autocomplete: "off", placeholder: sampleHint(input) });
      field.id = `ag-sample-${input.name}`;
      field.dataset.sample = input.name;
      const label = el("label", "field__label", `Example for ${input.name}${input.required ? " *" : ""}`);
      label.htmlFor = field.id;
      wrap.append(label, field);
      return wrap;
    }),
  );
}

// ── what the server says ───────────────────────────────────────────────

function renderState() {
  const state = $("[data-draft-state]");
  if (dirty) state.textContent = "The draft has changes that are not saved yet.";
  else if (agent.published_number == null) state.textContent = "The draft is saved. Nothing is published yet: publish it to make the agent usable.";
  else if (agent.draft_changed) state.textContent = `The draft is saved and differs from the published version ${agent.published_number}. Executions keep using version ${agent.published_number} until you publish.`;
  else state.textContent = `The draft equals the published version ${agent.published_number}.`;
  $("[data-problems]").replaceChildren(...(dirty ? [] : problemList(agent.problems).children));
  $("[data-save]").disabled = !dirty;
  $("[data-discard]").disabled = agent.published_number == null || (!dirty && !agent.draft_changed);
  $("[data-publish]").disabled = !dirty && !agent.draft_changed;
}

function renderHead() {
  $("[data-agent-name]").textContent = agent.name;
  document.title = `${agent.name} · Agents · OpenArtifact`;
  $("[data-agent-description]").textContent = agent.description;
  $("[data-chips]").replaceChildren(...agentChips(agent).map(([text, tone]) => chip(text, tone)));
  active.on = agent.active;
  $("[data-fact-version]").replaceChildren(chip(agent.published_number == null ? "Not published" : `v${agent.published_number} published`, agent.published_number == null ? "warn" : "accent"));
  $("[data-fact-draft]").replaceChildren(chip(dirty ? "Not saved" : agent.draft_changed ? "Has changes" : "Saved", dirty || agent.draft_changed ? "warn" : ""));
  $("[data-fact-created]").textContent = formatTime(agent.created_at);
  $("[data-fact-updated]").textContent = formatTime(agent.updated_at);
}

function renderVersions() {
  const list = $("[data-versions]");
  list.replaceChildren(
    ...agent.versions.map((version) => {
      const row = el("li", "ag-row");
      const main = el("div", "ag-row__main");
      const origin = version.source_number != null ? `rollback to version ${version.source_number}` : "published";
      main.append(el("strong", "", `Version ${version.number}`), el("span", "ag-row__meta", `${origin} ${ORIGINS[version.published_via] ?? version.published_via} · ${formatTime(version.published_at)}`));
      row.append(main);
      if (version.current) row.append(chip("In use", "ok"));
      else {
        const again = el("button", "button button--ghost button--sm", "Publish again");
        again.type = "button";
        again.setAttribute("aria-label", `Publish version ${version.number} again`);
        again.addEventListener("click", () =>
          confirm.open({
            message: `Publish version ${version.number} again? This makes a new version with its content; the history stays as it is.`,
            confirmLabel: "Publish again",
            onConfirm: async () => showPublished(await republishVersion(agent.id, version.number), `Version ${version.number} is published again as version`),
          }),
        );
        row.append(again);
      }
      return row;
    }),
  );
  $("[data-versions-empty]").hidden = agent.versions.length > 0;
}

async function renderUses() {
  let uses = [];
  try {
    uses = await agentUses(agent.id);
  } catch {
    /* the list is an extra: the page works without it */
  }
  $("[data-uses]").replaceChildren(
    ...uses.map((use) => {
      const row = el("li", "ag-row");
      const main = el("div", "ag-row__main");
      const link = el("a", "", use.node_name);
      link.href = `/actions/${encodeURIComponent(use.graph_slug)}`;
      main.append(link, el("span", "ag-row__meta", `in action "${use.graph_name}"${use.overrides.length ? ` · sets itself: ${use.overrides.map(fieldLabel).join(", ")}` : " · uses the agent's settings as they are"}`));
      row.append(main);
      return row;
    }),
  );
  $("[data-uses-empty]").hidden = uses.length > 0;
  $("[data-fact-uses]").textContent = uses.length ? `${uses.length} node${uses.length === 1 ? "" : "s"}` : "none";
}

function show(detail, { form = true } = {}) {
  agent = detail;
  renderHead();
  if (form) fillForm(agent.draft);
  renderState();
  renderVersions();
  renderUses();
}

function notice(...children) {
  const box = $("[data-notice]");
  box.replaceChildren(...children);
  box.hidden = children.length === 0;
}

/** After publishing: what changed, and which nodes keep a value of their own for a changed field. */
function showPublished(result, lead) {
  show(result.agent);
  const parts = [el("p", "", `${lead} ${result.version.number}. Executions that start from now on use it; running ones keep the version they started with.`)];
  if (result.changed.length) parts.push(el("p", "", `Changed: ${result.changed.map(fieldLabel).join(", ")}.`));
  if (result.overriding.length) {
    parts.push(el("p", "", "These nodes set a changed field themselves and keep their own value. Reset the override in the node to follow the agent:"));
    const list = el("ul");
    for (const use of result.overriding) {
      const item = el("li");
      const link = el("a", "", `${use.node_name} in "${use.graph_name}"`);
      link.href = `/actions/${encodeURIComponent(use.graph_slug)}`;
      const kept = use.overrides.filter((key) => result.changed.includes(key)).map(fieldLabel);
      item.append(link, document.createTextNode(`: ${kept.join(", ")}`));
      list.append(item);
    }
    parts.push(list);
  }
  notice(...parts);
  $("[data-notice]").scrollIntoView({ block: "nearest" });
}

function fail(error) {
  const box = $("[data-save-error]");
  box.textContent = error ? (error.detail ?? error.message) : "";
  box.hidden = !error;
}

function changed() {
  dirty = true;
  renderState();
  renderHead();
}

async function run(action) {
  fail(null);
  try {
    await action();
  } catch (error) {
    fail(error);
  }
}

/** Save what the form holds as the draft (the server checks the bounds and says what is missing). */
async function save() {
  for (const key of NUMBERS) if (Number.isNaN(readValue(key))) throw new Error(`${fieldLabel(key)} must be a number.`);
  show(await saveDraft(agent.id, readConfig()), { form: false });
  dirty = false;
  renderState();
}

// ── wiring ─────────────────────────────────────────────────────────────

root.addEventListener("input", (event) => {
  if (event.target.closest("[data-field], [data-inputs]")) changed();
});
root.addEventListener("change", (event) => {
  if (event.target.closest("[data-field], [data-inputs]")) changed();
});
$("[data-add-input]").addEventListener("click", () => {
  const row = inputRow();
  $("[data-inputs]").append(row);
  row.querySelector("input").focus();
  changed();
});
$("[data-save]").addEventListener("click", () => run(save));
$("[data-fact-uses]").addEventListener("click", () => tabs.select("versions", { focus: true }));
$("[data-publish]").addEventListener("click", () =>
  run(async () => {
    if (dirty) await save();
    showPublished(await publishAgent(agent.id), "Published as version");
  }),
);
$("[data-discard]").addEventListener("click", () =>
  confirm.open({
    message: `Discard the draft and go back to the published version ${agent.published_number}?`,
    confirmLabel: "Discard",
    onConfirm: async () => {
      show(await discardDraft(agent.id));
      notice();
    },
  }),
);
$("[data-active]").addEventListener("click", () =>
  run(async () => {
    try {
      show(await updateAgent(agent.id, { active: !agent.active }), { form: false });
    } finally {
      active.on = agent.active; // the server's word, also when it refused
    }
  }),
);
$("[data-rename]").addEventListener("click", () =>
  nameDialog.open({
    title: "Agent",
    values: { name: agent.name, description: agent.description },
    onSubmit: async (values) => show(await updateAgent(agent.id, values), { form: false }),
  }),
);
$("[data-preview]").addEventListener("click", () =>
  run(async () => {
    if (dirty) await save(); // the preview shows the saved draft
    const values = Object.fromEntries([...root.querySelectorAll("[data-sample]")].filter((input) => input.value !== "").map((input) => [input.dataset.sample, input.value]));
    const result = $("[data-preview-result]");
    result.replaceChildren(...previewView(await previewAgent(agent.id, { source: "draft", values })));
    result.hidden = false;
  }),
);
window.addEventListener("beforeunload", (event) => {
  if (dirty) event.preventDefault();
});

async function load() {
  try {
    const [detail, list] = await Promise.all([getAgent(ref), listProviders()]);
    providers = list;
    banner.hide();
    root.hidden = false;
    show(detail);
  } catch (error) {
    if (error.status === 404) {
      missing.hidden = false;
      root.hidden = true;
    } else banner.show("The agent could not be loaded.", { retry: true });
  }
}

banner.onRetry(load);
load();

let refresh = 0;
connectEvents({
  onClosed: () => {},
  onOpen: () => {},
  onEvent: (type) => {
    if (type !== "agents.changed" && type !== "providers.changed") return;
    clearTimeout(refresh);
    refresh = setTimeout(async () => {
      try {
        if (type === "providers.changed") {
          providers = await listProviders();
          if (!dirty) {
            fillModelSelects(readValue("provider_id"), readValue("model"));
          }
        }
        show(await getAgent(ref), { form: !dirty }); // never overwrite what is being typed
      } catch {
        /* the next event or a reload repairs it */
      }
    }, 200);
  },
});
