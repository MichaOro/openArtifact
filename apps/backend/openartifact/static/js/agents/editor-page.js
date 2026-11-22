/* The page of one agent: its draft (prompts, inputs, model and limits), publishing, the versions with
 * rollback, the preview and the nodes that use it. The form edits the draft only; nothing an
 * execution uses changes before "Publish". */
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { agentUses, discardDraft, getAgent, listProviders, previewAgent, publishAgent, republishVersion, saveDraft, updateAgent } from "./api.js";
import { agentChips, fieldLabel, numberOf, providerInEffect, usableModels } from "./model.js";
import { chip, configFacts, el, previewView, problemList } from "./view.js";

const root = document.querySelector("[data-agent-editor]");
const missing = document.querySelector("[data-agent-missing]");
const ref = root.dataset.agentRef;
const banner = new AlertBar();
const nameDialog = new FormDialog(new Modal(document.getElementById("name-modal")));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const $ = (selector) => root.querySelector(selector);
const control = (key) => root.querySelector(`[data-field="${key}"]`);

const NUMBERS = ["temperature", "max_tokens", "request_timeout_seconds", "total_timeout_seconds", "retries"];
const DEFAULTS = { request_timeout_seconds: 60, total_timeout_seconds: 600, retries: 3 };
const ORIGINS = { user: "in the browser", api: "through the API" };

let agent = null;
let providers = [];
let dirty = false;
let fieldCount = 0;

// ── the form ───────────────────────────────────────────────────────────

function setSwitch(button, on) {
  button.setAttribute("aria-checked", String(on));
  button.querySelector(".ge-switch__state").textContent = on ? "On" : "Off";
}

const isOn = (button) => button.getAttribute("aria-checked") === "true";

function inputRow(input = { name: "", type: "string", required: false, default: null, description: "" }) {
  const row = el("li", "ag-input");
  const make = (label, node, key) => {
    const wrap = el("div", "field");
    node.id = `ag-input-${(fieldCount += 1)}`;
    node.dataset.input = key;
    const text = el("label", "field__label", label);
    text.htmlFor = node.id;
    wrap.append(text, node);
    return wrap;
  };
  const name = Object.assign(el("input", "field__control"), { type: "text", value: input.name, maxLength: 32, placeholder: "ticket", autocomplete: "off", spellcheck: false });
  const type = el("select", "field__control");
  for (const option of ["string", "number", "boolean"]) type.append(new Option(option, option));
  type.value = input.type;
  const required = Object.assign(el("input"), { type: "checkbox", checked: input.required });
  required.dataset.input = "required";
  const requiredLabel = el("label", "ag-check");
  requiredLabel.append(required, el("span", "", "Required"));
  const fallback = Object.assign(el("input", "field__control"), { type: "text", value: input.default == null ? "" : String(input.default), autocomplete: "off" });
  const description = Object.assign(el("input", "field__control"), { type: "text", value: input.description ?? "", maxLength: 200, autocomplete: "off" });
  const remove = el("button", "icon-button icon-button--sm");
  remove.type = "button";
  remove.title = "Remove input";
  remove.setAttribute("aria-label", "Remove input");
  remove.append(icon("trash"));
  remove.addEventListener("click", () => {
    row.remove();
    changed();
    renderSamples();
  });
  const sync = () => {
    fallback.disabled = required.checked; // a required input has no default: the node must map it
    if (required.checked) fallback.value = "";
  };
  required.addEventListener("change", sync);
  sync();
  row.append(make("Name", name, "name"), make("Type", type, "type"), requiredLabel, make("Default", fallback, "default"), make("Description", description, "description"), remove);
  name.addEventListener("change", renderSamples);
  return row;
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
    return { name: get("name").value.trim(), type, required: get("required").checked, default: get("required").checked ? null : fallback, description: get("description").value.trim() };
  });
}

function readConfig() {
  const config = {
    system_prompt_enabled: isOn(control("system_prompt_enabled")),
    system_prompt: control("system_prompt").value,
    user_prompt: control("user_prompt").value,
    inputs: readInputs(),
    provider_id: control("provider_id").value || null,
    model: control("model").value || null,
  };
  for (const key of NUMBERS) {
    const value = numberOf(control(key).value);
    config[key] = value === null ? (DEFAULTS[key] ?? null) : value;
  }
  return config;
}

function fillModels(selected) {
  const select = control("model");
  const provider = providerInEffect(providers, control("provider_id").value || null);
  const models = usableModels(provider);
  const fallback = provider?.default_model ? `Default of the provider (${provider.default_model})` : "Default of the provider (none set)";
  select.replaceChildren(new Option(provider ? fallback : "No provider", ""), ...models.map((id) => new Option(id, id)));
  if (selected && !models.includes(selected)) select.append(new Option(`${selected} (not enabled)`, selected));
  select.value = selected ?? "";
}

function fillProviders(selected) {
  const select = control("provider_id");
  const fallback = providers.find((p) => p.is_default);
  select.replaceChildren(new Option(fallback ? `Default provider (${fallback.name})` : "Default provider (none set)", ""), ...providers.map((p) => new Option(p.name, p.id)));
  if (selected && !providers.some((p) => p.id === selected)) select.append(new Option("(deleted provider)", selected));
  select.value = selected ?? "";
}

function fillForm(config) {
  setSwitch(control("system_prompt_enabled"), config.system_prompt_enabled);
  $("[data-system-field]").hidden = !config.system_prompt_enabled;
  control("system_prompt").value = config.system_prompt;
  control("user_prompt").value = config.user_prompt;
  $("[data-inputs]").replaceChildren(...config.inputs.map(inputRow));
  fillProviders(config.provider_id);
  fillModels(config.model);
  for (const key of NUMBERS) control(key).value = config[key] ?? "";
  dirty = false;
  renderSamples();
}

/** Example values for the preview: one field per input, what was typed is kept. */
function renderSamples() {
  const host = $("[data-preview-values]");
  const typed = Object.fromEntries([...host.querySelectorAll("[data-sample]")].map((input) => [input.dataset.sample, input.value]));
  host.replaceChildren(
    ...readInputs()
      .filter((input) => input.name)
      .map((input) => {
        const wrap = el("div", "field");
        const field = Object.assign(el("input", "field__control"), { type: "text", value: typed[input.name] ?? "", autocomplete: "off" });
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
  setSwitch($("[data-active]"), agent.active);
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
  for (const key of NUMBERS) if (Number.isNaN(numberOf(control(key).value))) throw new Error(`${fieldLabel(key)} must be a number.`);
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
control("system_prompt_enabled").addEventListener("click", (event) => {
  const button = event.currentTarget;
  setSwitch(button, !isOn(button));
  $("[data-system-field]").hidden = !isOn(button);
  changed();
});
control("provider_id").addEventListener("change", () => fillModels(null));
$("[data-add-input]").addEventListener("click", () => {
  const row = inputRow();
  $("[data-inputs]").append(row);
  row.querySelector("input").focus();
  changed();
});
$("[data-save]").addEventListener("click", () => run(save));
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
$("[data-active]").addEventListener("click", () => run(async () => show(await updateAgent(agent.id, { active: !agent.active }), { form: false })));
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
            fillProviders(control("provider_id").value || null);
            fillModels(control("model").value || null);
          }
        }
        show(await getAgent(ref), { form: !dirty }); // never overwrite what is being typed
      } catch {
        /* the next event or a reload repairs it */
      }
    }, 200);
  },
});
