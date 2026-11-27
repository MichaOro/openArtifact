/* The page of one agent (ADR-045): a header with the draft's state and Save / Discard / Publish, tabs for
 * the areas and an options panel that switches the optional ones on. Prompts and "Versions & use" are always
 * there; Inputs and Model & Limits are tabs while their switch (part of the draft) is on; the system prompt
 * shows inside Prompts; Quick test is a tab that lives only while the page is open. The form edits the draft
 * only; nothing an execution uses changes before "Publish". */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { FormDialog } from "../components/form-dialog.js";
import { foldEntries, foldSeparator } from "../components/fold-list.js";
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { LeaveGuard } from "../components/leave-guard.js";
import { MarkdownBar } from "../components/markdown-bar.js";
import { fitColumn, fitSelect, refitWhenFontsLoad } from "../components/select-fit.js";
import { Modal } from "../components/modal.js";
import { OptionsPanel } from "../components/options-panel.js";
import { SettingsGroup, numberSetting } from "../components/settings-group.js";
import { Sortable } from "../components/sortable.js";
import { SchemaFields } from "../components/schema-fields.js";
import { Switch } from "../components/switch.js";
import { Tabs } from "../components/tabs.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { agentUses, discardDraft, getVersion, removeAgentReference, getAgent, listProviders, previewAgent, publishAgent, republishVersion, saveDraft, updateAgent } from "./api.js";
import { ARTIFACT_PARTS, agentChips, fieldLabel, optionsOf, partOf, partText, providerInEffect, sampleHint, sourceOf, usableModels } from "./model.js";
import { inputsView, limitsView, promptsView } from "./version-view.js";
import { attachCopy } from "../components/copy-button.js";
import { chip, configFacts, el, previewView, problemList } from "./view.js";
import { t, tn } from "../i18n.js";

const root = document.querySelector("[data-agent-editor]");
const missing = document.querySelector("[data-agent-missing]");
const ref = root.dataset.agentRef;
const banner = new AlertBar();
const nameDialog = new FormDialog(new Modal(document.getElementById("name-modal")));
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const $ = (selector) => root.querySelector(selector);
const control = (key) => root.querySelector(`[data-field="${key}"]`);
// The prompts are Markdown by convention and go to the model as they are written (ADR-077); the bar only helps to write them.
for (const key of ["user_prompt", "system_prompt"]) new MarkdownBar(control(key));
const promptCopies = ["user_prompt", "system_prompt"].map((key) => attachCopy(control(key), undefined, { always: true })); // the whole prompt in one click

// The answer format (ADR-085): the shape of the final answer as a flat list of fields; the editor is the one of the Hand Over Tool.
const answerFormat = new SchemaFields({ label: t("agent_editor.answer_format"), onInput: () => changed(), onSettle: () => changed() });
$("[data-answer-format]").append(answerFormat.element);

const NUMBERS = ["temperature", "max_tokens", "request_timeout_seconds", "total_timeout_seconds", "retries", "max_iterations", "token_budget", "tool_result_chars"];
const ORIGINS = { user: t("agents.editor_page.browser"), api: t("agents.editor_page.through_api") };

let agent = null;
let providers = [];
let dirty = false;
let versionsExpanded = false; // the folded middle of a long list of versions is shown
let fieldCount = 0;

// ── tabs and options ───────────────────────────────────────────────────

const tabs = new Tabs($("[data-ag-tabs]"));
const TAB_OF = { inputs: "inputs", limits: "limits" };
const options = new OptionsPanel(
  $("[data-options]"),
  [
    { key: "system_prompt", label: t("agent_editor.system_prompt"), help: t("agents.editor_page.add_system_prompt_below_user") },
    { key: "inputs", label: t("common.inputs"), help: t("agents.editor_page.declare_values_agent_needs_from") },
    { key: "limits", label: t("common.model_and_limits"), help: t("agents.editor_page.override_default_provider_model_limits") },
    { key: "test", label: t("agent_editor.quick_test"), help: t("agents.editor_page.fill_prompts_with_example_values") },
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

// The identity: name and description are edited in place; the pencil opens the full dialog (name-modal).
const nameText = new InlineName($("[data-agent-name]"), {
  label: t("agents.editor_page.agent_name"),
  maxLength: 100,
  keepOpenOnError: true,
  onCommit: async (name) => show(await updateAgent(agent.id, { name }), { form: false }),
});
const descriptionText = new InlineName($("[data-agent-description]"), {
  label: t("common.description"),
  maxLength: 2000,
  keepOpenOnError: true,
  multiline: true,
  allowEmpty: true,
  emptyText: t("agents.editor_page.add_description"),
  onCommit: async (description) => show(await updateAgent(agent.id, { description }), { form: false }),
});

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
    selectSetting("provider_id", t("common.provider"), t("agents.editor_page.where_requests_go"), t("agents.editor_page.default_provider")),
    selectSetting("model", t("agents.editor_page.model"), t("agents.editor_page.model_provider"), t("agents.editor_page.provider_s_default_model")),
    numberSetting("temperature", t("agents.editor_page.temperature"), { min: 0, max: 2, step: 0.1, hint: "0 to 2.", fallback: t("agents.editor_page.model_s_own") }),
    numberSetting("max_tokens", t("agents.editor_page.max_tokens"), { min: 1, max: 8192, hint: "1 to 8192.", fallback: t("agents.editor_page.model_s_own") }),
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
    numberSetting("total_timeout_seconds", t("agents.editor_page.node_time_limit"), { min: 1, max: 1800, hint: t("agents.editor_page.seconds_1_1800_covers_all"), fallback: 900, unit: " s" }),
    numberSetting("max_iterations", t("agents.editor_page.max_iterations"), { min: 1, max: 500, hint: t("agents.editor_page.1_50_how_many_requests"), fallback: 100, unit: t("agents.editor_page.only_with_tools") }),
    numberSetting("token_budget", t("agents.editor_page.token_budget"), { min: 1000, max: 10000000, hint: t("agents.editor_page.token_budget_hint"), fallback: t("agents.editor_page.no_budget") }),
    numberSetting("tool_result_chars", t("agents.editor_page.tool_result_limit"), { min: 500, max: 100000, hint: t("agents.editor_page.tool_result_limit_hint"), fallback: 12000, unit: t("agents.editor_page.only_with_tools") }),
    numberSetting("retries", t("agents.editor_page.retries"), { min: 0, max: 4, hint: t("agents.editor_page.0_4_request_tried_again"), fallback: 3 }),
    numberSetting("request_timeout_seconds", t("agents.editor_page.request_timeout"), { min: 1, max: 300, hint: t("agents.editor_page.seconds_1_300_one_attempt"), fallback: 60, unit: " s" }),
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
  fitSelect(select); // as wide as its longest choice: the text is never cut
  return select;
}

/** The three choice columns of the inputs table are as wide as their longest choice, whatever the rows hold or may hold later (the
 * Type column shows the types of a value or the parts of the artifact, whichever the row's source says). */
function fitInputColumns() {
  const table = $("[data-inputs-table]");
  const selects = (key) => table.querySelectorAll(`select[data-input="${key}"]`);
  const types = [...ARTIFACT_PARTS.map(partText), "string", "number", "boolean", t("agents.editor_page.source_value"), t("agents.editor_page.source_artifact")];
  fitColumn(table, "--ag-col-source", selects("source"), { extra: types.slice(-2) });
  fitColumn(table, "--ag-col-type", selects("type"), { extra: types.slice(0, -2) });
  fitColumn(table, "--ag-col-required", selects("required"));
}
new MutationObserver(fitInputColumns).observe($("[data-inputs]"), { childList: true });
refitWhenFontsLoad(fitInputColumns);

function textInput(value, label, key, extra = {}) {
  const input = Object.assign(el("input", "field__control"), { type: "text", value: value ?? "", autocomplete: "off", ...extra });
  input.setAttribute("aria-label", label);
  input.dataset.input = key;
  return input;
}

/** One row of the inputs table: name, type, required or optional, default, the description if it has one, and its menu. */
function inputRow(input = { name: "", source: "value", type: "string", required: false, default: null, description: "" }) {
  const row = el("li", "ag-input field-group__row");
  const name = textInput(input.name, t("common.name"), "name", { maxLength: 32, placeholder: "ticket", spellcheck: false });
  const source = choiceSelect([["value", t("agents.editor_page.source_value")], ["artifact", t("agents.editor_page.source_artifact")]], sourceOf(input), t("agent_editor.comes_from"), "source");
  source.title = t("agents.editor_page.source_help");
  // the second choice follows the first: the type of a value, the part of the artifact
  const type = choiceSelect([], "", t("common.type"), "type");
  const required = choiceSelect([["required", t("common.required")], ["optional", t("agents.editor_page.optional")]], input.required ? "required" : "optional", t("common.required"), "required");
  required.classList.add("ag-input__required");
  const fallback = textInput(input.default == null ? "" : String(input.default), t("common.default"), "default");
  const description = el("div", "ag-input__description field-group__wide");
  const more = el("button", "icon-button icon-button--sm ag-input__more field-group__end");
  more.type = "button";
  more.setAttribute("aria-label", t("agents.editor_page.input_actions"));
  more.title = t("agents.editor_page.input_actions");
  more.setAttribute("aria-haspopup", "menu");
  more.append(icon("more"));
  const fillType = () => {
    const choices = source.value === "artifact" ? ARTIFACT_PARTS.map((part) => [part, partText(part)]) : [["string", "string"], ["number", "number"], ["boolean", "boolean"]];
    const wanted = source.value === "artifact" ? partOf(input) : (input.type ?? "string");
    const keep = [...type.options].some((o) => o.value === type.value) && choices.some(([v]) => v === type.value) ? type.value : wanted;
    type.replaceChildren(...choices.map(([value, text]) => new Option(text, value)));
    type.value = choices.some(([v]) => v === keep) ? keep : choices[0][0];
    type.setAttribute("aria-label", source.value === "artifact" ? t("common.part") : t("common.type"));
    type.title = source.value === "artifact" ? t("agents.editor_page.part_help") : "";
  };
  const sync = () => {
    const isRequired = required.value === "required";
    const isArtifact = source.value === "artifact";
    required.disabled = isArtifact; // an input from the artifact is always there: it is neither required nor optional
    fallback.disabled = isRequired || isArtifact; // a required input has no default: the node must map it; the artifact has no default text
    fallback.placeholder = isRequired || isArtifact ? "—" : "";
    if (isRequired || isArtifact) fallback.value = "";
    if (isArtifact) required.value = "optional";
  };
  fillType();
  required.addEventListener("change", sync);
  source.addEventListener("change", () => {
    fillType();
    sync();
    renderSamples();
  });
  type.addEventListener("change", renderSamples);
  sync();
  more.addEventListener("click", () => {
    const has = Boolean(description.firstChild);
    inputMenu.toggle(
      more,
      [
        has
          ? { label: t("agents.editor_page.remove_description"), icon: "x", onSelect: () => setDescription(row, null) }
          : { label: t("agents.editor_page.add_description_2"), icon: "plus", onSelect: () => setDescription(row, "") },
        { label: t("agents.editor_page.remove_input"), icon: "trash", danger: true, onSelect: () => removeInput(row) },
      ],
      `Input ${name.value || ""}`.trim(),
    );
  });
  const grip = el("button", "icon-button icon-button--sm ag-input__grip");
  grip.type = "button";
  grip.setAttribute("aria-label", t("agents.editor_page.drag_input"));
  grip.title = t("agents.editor_page.drag_input_help");
  grip.append(icon("grip"));
  row.append(grip, name, source, type, required, fallback, description, more);
  if (input.description) setDescription(row, input.description, { quiet: true });
  name.addEventListener("change", renderSamples);
  return row;
}

/** Give a row a description field (text) or take it away (null); the column follows the data. */
function setDescription(row, text, { quiet = false } = {}) {
  const cell = row.querySelector(".ag-input__description");
  if (text === null) cell.replaceChildren();
  else {
    const field = textInput(text, t("common.description"), "description", { maxLength: 200 });
    cell.replaceChildren(field);
    if (!quiet) field.focus();
  }
  showDescriptionColumn();
  if (!quiet) changed();
}

/** The rows are the data: a drag has moved the row already, the arrow keys ask for it. Either way the order is a change of the draft. */
function moveInput(from, to, by) {
  const list = $("[data-inputs]");
  const row = list.children[by === "key" ? from : to];
  if (by === "key") list.insertBefore(row, list.children[to + (to > from ? 1 : 0)] ?? null);
  row.querySelector(".ag-input__grip").focus();
  const live = $("[data-inputs-live]");
  live.textContent = "";
  const name = row.querySelector('[data-input="name"]').value || t("agents.editor_page.input_unnamed");
  window.setTimeout(() => (live.textContent = t("agents.editor_page.input_moved", { name, position: to + 1, total: list.children.length })), 0);
  changed();
  renderSamples();
}
new Sortable($("[data-inputs]"), { handle: ".ag-input__grip", onMove: moveInput });

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
  $("[data-inputs-table]").classList.toggle("field-group--long", any); // seven elements in a row: it breaks in pairs earlier
}

/** The inputs as the form has them; a default is sent in the input's own type. */
function readInputs() {
  return [...$("[data-inputs]").children].map((row) => {
    const get = (key) => row.querySelector(`[data-input="${key}"]`);
    const source = get("source").value;
    if (source === "artifact") return { name: get("name").value.trim(), source, part: get("type").value, description: get("description")?.value.trim() ?? "" };
    const type = get("type").value;
    const raw = get("default").value.trim();
    let fallback = raw === "" ? null : raw;
    if (fallback !== null && type === "number" && !Number.isNaN(Number(raw))) fallback = Number(raw);
    if (fallback !== null && type === "boolean" && ["true", "false"].includes(raw.toLowerCase())) fallback = raw.toLowerCase() === "true";
    const required = get("required").value === "required";
    return { name: get("name").value.trim(), source, type, required, default: required ? null : fallback, description: get("description")?.value.trim() ?? "" };
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
    answer_format: answerFormat.value(),
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
  const fallback = provider?.default_model ? t("agents.editor_page.default_provider_default_model", { default_model: provider.default_model }) : t("agents.editor_page.default_provider_none_set");
  select.replaceChildren(new Option(provider ? fallback : t("agents.editor_page.no_provider"), ""), ...models.map((id) => new Option(id, id)));
  if (selected && !models.includes(selected)) select.append(new Option(`${selected} (not enabled)`, selected));
  select.value = selected ?? "";
}

function fillProviders(select, selected) {
  const fallback = providers.find((p) => p.is_default);
  select.replaceChildren(new Option(fallback ? t("agents.editor_page.default_provider_name", { name: fallback.name }) : t("agents.editor_page.default_provider_none_set_2"), ""), ...providers.map((p) => new Option(p.name, p.id)));
  if (selected && !providers.some((p) => p.id === selected)) select.append(new Option(t("agents.editor_page.deleted_provider"), selected));
  select.value = selected ?? "";
}

function fillForm(config) {
  for (const [key, on] of Object.entries(optionsOf(config))) {
    options.set(key, on);
    showOption(key, on);
  }
  control("system_prompt").value = config.system_prompt;
  control("user_prompt").value = config.user_prompt;
  for (const copy of promptCopies) copy.refresh(); // the fields were filled without an input event
  $("[data-inputs]").replaceChildren(...config.inputs.map((input) => inputRow(input)));
  showDescriptionColumn();
  answerFormat.list = (config.answer_format ?? []).map((field) => ({ ...field }));
  answerFormat.draw();
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
      if (sourceOf(input) === "artifact") {
        // fixed by the definition: the preview uses a general example, there is nothing to type
        wrap.append(el("p", "field__help", t("agents.editor_page.quick_artifact_note", { name: input.name })));
        return wrap;
      }
      const field = Object.assign(el("input", "field__control"), { type: "text", value: typed[input.name] ?? "", autocomplete: "off", placeholder: sampleHint(input) });
      field.id = `ag-sample-${input.name}`;
      field.dataset.sample = input.name;
      const label = el("label", "field__label", t("agents.editor_page.example_for", { name: input.name }) + (input.required ? " *" : ""));
      label.htmlFor = field.id;
      wrap.append(label, field);
      return wrap;
    }),
  );
}

// ── what the server says ───────────────────────────────────────────────

function renderState() {
  const state = $("[data-draft-state]");
  if (dirty) state.textContent = t("agents.editor_page.draft_has_changes_not_saved");
  else if (agent.published_number == null) state.textContent = t("agents.editor_page.draft_saved_nothing_published_yet");
  else if (agent.draft_changed) state.textContent = t("agents.editor_page.draft_saved_differs_from_published", { published_number: agent.published_number, published_number2: agent.published_number });
  else state.textContent = t("agents.editor_page.draft_equals_published_version_published", { published_number: agent.published_number });
  $("[data-problems]").replaceChildren(...(dirty ? [] : problemList(agent.problems).children));
  $("[data-save]").disabled = !dirty;
  $("[data-discard]").disabled = agent.published_number == null || (!dirty && !agent.draft_changed);
  $("[data-publish]").disabled = !dirty && !agent.draft_changed;
}

function renderHead() {
  nameText.setText(agent.name);
  document.title = t("agents.editor_page.name_agents_openartifact", { name: agent.name });
  descriptionText.setText(agent.description ?? "");
  $("[data-chips]").replaceChildren(...agentChips(agent).map(([text, tone]) => chip(text, tone)));
  active.on = agent.active;
  $("[data-fact-version]").replaceChildren(chip(agent.published_number == null ? t("agents.editor_page.not_published") : t("agents.editor_page.v_published_number_published", { published_number: agent.published_number }), agent.published_number == null ? "warn" : "accent"));
  $("[data-fact-draft]").replaceChildren(chip(dirty ? t("agents.editor_page.not_saved") : agent.draft_changed ? t("agents.editor_page.has_changes") : t("agents.editor_page.saved"), dirty || agent.draft_changed ? "warn" : ""));
  $("[data-fact-created]").textContent = formatTime(agent.created_at);
  $("[data-fact-updated]").textContent = formatTime(agent.updated_at);
}

/** Versions: a compact row each, like Status & info; the one executions use is "In use", an older one can be published again. */
function renderVersions() {
  const list = $("[data-versions]");
  // a long list folds its middle: the newest two and the very first version stay, the rest is behind "Show more versions (N)"
  const entries = foldEntries(agent.versions, { head: 2, tail: 1, expanded: versionsExpanded });
  list.replaceChildren(
    ...entries.map((entry) => {
      if (entry.fold) {
        return foldSeparator({
          count: entry.fold,
          expanded: versionsExpanded,
          label: versionsExpanded ? t("agents.editor_page.hide_versions", { count: entry.fold }) : t("agents.editor_page.show_more_versions", { count: entry.fold }),
          onToggle: () => {
            versionsExpanded = !versionsExpanded;
            renderVersions();
            list.querySelector(".fold-separator__button")?.focus();
          },
        });
      }
      const version = entry.item;
      const row = el("li", "ag-version");
      const head = el("div", "ag-version__head");
      head.append(el("strong", "", t("agents.editor_page.version_number", { number: version.number })));
      if (version.current) head.append(chip(t("agents.editor_page.use"), "ok"));
      const origin = version.source_number != null ? t("agents.editor_page.rollback_version_source_number", { source_number: version.source_number }) : t("agents.editor_page.published_word");
      row.append(head, el("span", "ag-row__meta", `${formatTime(version.published_at)} · ${origin} ${ORIGINS[version.published_via] ?? version.published_via}`));
      const buttons = el("div", "ag-version__buttons");
      if (!version.current) {
        // the version in use is what the editor's tabs show already: only an earlier one needs "Show"
        const showButton = el("button", "button button--ghost button--sm", t("agents.editor_page.show"));
        showButton.type = "button";
        showButton.setAttribute("aria-label", t("agents.editor_page.show_version_number", { number: version.number }));
        showButton.addEventListener("click", () => openVersion(version));
        buttons.append(showButton);
        const again = el("button", "button button--ghost button--sm ag-version__again", t("agent_editor.publish_again"));
        again.type = "button";
        again.setAttribute("aria-label", t("agents.editor_page.publish_version_number_again", { number: version.number }));
        again.addEventListener("click", () => confirmRepublish(version));
        buttons.append(again);
        row.append(buttons);
      }
      return row;
    }),
  );
  $("[data-versions-empty]").hidden = agent.versions.length > 0;
}

/** Publishing an earlier version again: it makes something new, so the question has the accent, not red. */
function confirmRepublish(version) {
  confirm.open({
    message: t("agents.editor_page.publish_version_number_again_makes", { number: version.number }),
    confirmLabel: t("agent_editor.publish_again"),
    tone: "primary",
    onConfirm: async () => showPublished(await republishVersion(agent.id, version.number), t("agents.editor_page.version_number_published_again_as", { number: version.number })),
  });
}

// ── a published version, read-only (ADR-049) ──

const versionModal = new Modal(document.getElementById("version-modal"));
const versionRoot = document.getElementById("version-modal");
const versionTabs = new Tabs(versionRoot.querySelector("[data-version-tabs]"));
let shownVersion = null;

async function openVersion(version) {
  const full = await getVersion(agent.id, version.number);
  shownVersion = version;
  versionRoot.querySelector(".modal__title").textContent = t("agents.editor_page.version_number", { number: version.number });
  const origin = version.source_number != null ? t("agents.editor_page.rollback_version_source_number_2", { source_number: version.source_number }) : t("agents.editor_page.published_word");
  versionRoot.querySelector("[data-version-facts]").textContent = (version.current ? t("agents.editor_page.use_2") : "") + t("agents.editor_page.version_facts", { origin, via: ORIGINS[version.published_via] ?? version.published_via, time: formatTime(version.published_at) });
  const panels = { prompts: promptsView(full.config), inputs: inputsView(full.config), limits: limitsView(full.config, providers) };
  for (const [name, view] of Object.entries(panels)) {
    versionRoot.querySelector(`[data-version-panel="${name}"]`).replaceChildren(...(view ? [view] : []));
    versionTabs.setVisible(name, Boolean(view));
  }
  versionTabs.select("prompts", { notify: false });
  versionRoot.querySelector("[data-version-again]").hidden = version.current;
  versionModal.open();
}

versionRoot.querySelector("[data-version-again]").addEventListener("click", () => {
  versionModal.close();
  confirmRepublish(shownVersion);
});

const referenceDialog = new ConfirmDialog(new Modal(document.getElementById("reference-modal")));

/** Take the agent out of one node: its agent_id is emptied through the graph API, nothing else changes. */
function confirmRemoveReference(use) {
  referenceDialog.open({
    title: t("agents.editor_page.remove_agent_reference"),
    message: t("agents.editor_page.will_remove_connection_agent_from"),
    subject: use.graph_name,
    note: t("agents.editor_page.action_will_no_longer_use"),
    confirmLabel: t("agents.editor_page.remove_reference"),
    onConfirm: async () => {
      await removeAgentReference(use.graph_id, use.node_id);
      await renderUses(); // the server's list: an error leaves the dialog open with its message
    },
  });
}

/** Used by: a card per agent node with where it is, what it overrides, Open and Remove reference. */
async function renderUses() {
  let uses = [];
  try {
    uses = await agentUses(agent.id);
  } catch {
    /* the list is an extra: the page works without it */
  }
  $("[data-uses]").replaceChildren(
    ...uses.map((use) => {
      const row = el("li", "ag-use");
      const main = el("div", "ag-use__main");
      main.append(
        el("strong", "", use.node_name),
        el("span", "ag-row__meta", t("agents.editor_page.agent_node_action_graph_name", { graph_name: use.graph_name })),
        el("span", "ag-row__meta", use.overrides.length ? t("agents.editor_page.sets_itself", { fields: use.overrides.map(fieldLabel).join(", ") }) : t("agents.editor_page.uses_agent_settings")),
      );
      const open = el("a", "button button--ghost button--sm");
      open.href = `/actions/${encodeURIComponent(use.graph_slug)}?select=${encodeURIComponent(use.node_id)}&agent=${encodeURIComponent(agent.id)}`;
      open.append(icon("action"), document.createTextNode(t("agents.editor_page.open")));
      open.setAttribute("aria-label", t("agents.editor_page.open_node_name_graph_name", { node_name: use.node_name, graph_name: use.graph_name }));
      const remove = el("button", "icon-button icon-button--sm is-danger");
      remove.type = "button";
      remove.title = t("agents.editor_page.remove_reference");
      remove.setAttribute("aria-label", t("agents.editor_page.remove_reference_node_name_graph", { node_name: use.node_name, graph_name: use.graph_name }));
      remove.append(icon("trash"));
      remove.addEventListener("click", () => confirmRemoveReference(use));
      if (use.in_draft && !use.published) main.append(el("span", "ag-row__meta", t("agents.page.usage_draft_note")));
      if (!use.in_draft) main.append(el("span", "ag-row__meta", t("agents.page.usage_only_published", { number: use.published_number })));
      const actions = el("div", "ag-use__actions");
      actions.append(open);
      if (use.in_draft) actions.append(remove); // a node only the published version has is not in the draft: there is nothing to take the agent out of
      row.append(main, actions);
      return row;
    }),
  );
  $("[data-uses-empty]").hidden = uses.length > 0;
  $("[data-fact-uses]").textContent = uses.length ? tn("count.node", uses.length) : t("common.none");
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
  const parts = [el("p", "", t("agents.editor_page.lead_number_executions_start_from", { lead, number: result.version.number }))];
  if (result.changed.length) parts.push(el("p", "", `Changed: ${result.changed.map(fieldLabel).join(", ")}.`));
  if (result.overriding.length) {
    parts.push(el("p", "", t("agents.editor_page.these_nodes_set_changed_field")));
    const list = el("ul");
    for (const use of result.overriding) {
      const item = el("li");
      const link = el("a", "", t("agents.editor_page.node_name_graph_name", { node_name: use.node_name, graph_name: use.graph_name }));
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
  // a field the server refused says why (the answer format: a name the agent's own data uses), not only "check your input"
  const refused = Object.values(error?.fieldErrors ?? {})[0];
  box.textContent = error ? (error.detail ?? (refused ? String(refused).replace(/^Value error, /, "") : error.message)) : "";
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
  for (const key of NUMBERS) if (Number.isNaN(readValue(key))) throw new Error(t("agents.editor_page.fieldlabel_must_be_number", { fieldLabel: fieldLabel(key) }));
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
    showPublished(await publishAgent(agent.id), t("agents.editor_page.published_as_version"));
  }),
);
$("[data-discard]").addEventListener("click", () =>
  confirm.open({
    message: t("agents.editor_page.discard_draft_go_back_published", { published_number: agent.published_number }),
    confirmLabel: t("index.discard"),
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
    title: t("common.agent"),
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
// unsaved changes: the page's own links ask in a dialog (Stay / Leave without saving / Save and leave)
new LeaveGuard(new Modal(document.getElementById("leave-modal")), { isDirty: () => dirty, save: () => save() });

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
    } else banner.show(t("agents.editor_page.agent_could_not_be_loaded"), { retry: true });
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
