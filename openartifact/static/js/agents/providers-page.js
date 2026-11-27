/* The LLM providers page: the providers with their models, the dialog that tests and saves one, and
 * the switches of the models. A provider is only ever saved after its connection test passed (the
 * server refuses it otherwise); "Test connection" shows the steps of that test without saving. */
import { ActionDialog } from "../components/action-dialog.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { isPlainHttp } from "./model.js";
import { addModel, checkProvider, createProvider, deleteModel, deleteProvider, listProviders, listSecrets, putSecret, refreshModels, testProvider, updateModel, updateProvider } from "./api.js";
import { chip, el } from "./view.js";
import { t } from "../i18n.js";

const listEl = document.querySelector("[data-provider-list]");
const emptyEl = document.querySelector("[data-provider-empty]");
const banner = new AlertBar();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const KINDS = { openrouter: t("agents.providers_page.openrouter"), openai_compatible: t("agents.providers_page.openai_compatible") };

let providers = [];
/** Which providers have their model list open, and what is typed into its filter. */
const openModels = new Set();
const filters = new Map();

// ── the dialog ─────────────────────────────────────────────────────────

class ProviderDialog extends ActionDialog {
  constructor(modal) {
    super(modal, t("agents.providers_page.could_not_save_please_try"));
    this.form = this.root.querySelector("form");
    this.result = this.root.querySelector("[data-check-result]");
    this.provider = null;
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.run(() => this.#save());
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.root.querySelector("[data-test]").addEventListener("click", () => this.run(() => this.#test(), { close: false }));
    this.field("kind").addEventListener("change", () => this.#layout());
    this.field("base_url").addEventListener("input", () => this.#layout());
  }

  field(name) {
    return this.form.elements.namedItem(name);
  }

  /** @param {object|null} provider null: a new one */
  async open(provider = null) {
    this.provider = provider;
    this.form.reset();
    this.setError("");
    this.result.hidden = true;
    this.titleEl.textContent = provider ? t("agents.providers_page.provider_name", { name: provider.name }) : t("providers.new_provider");
    this.field("kind").value = provider?.kind ?? (providers.some((p) => p.kind === "openrouter") ? "openai_compatible" : "openrouter");
    this.field("kind").querySelector('[value="openrouter"]').disabled = !provider && providers.some((p) => p.kind === "openrouter");
    this.field("name").value = provider?.name ?? "";
    this.field("base_url").value = provider && provider.kind !== "openrouter" ? provider.base_url : "";
    this.field("secret_name").value = provider?.secret_name ?? "";
    this.field("allow_http").checked = provider?.allow_http ?? false;
    this.field("is_default").checked = provider?.is_default ?? providers.length === 0;
    this.#layout();
    this.modal.open();
    this.field("name").focus();
    try {
      const names = await listSecrets();
      this.root.querySelector("#pv-secrets").replaceChildren(...names.map((s) => new Option(s.name, s.name)));
    } catch {
      /* without the list the name is typed by hand */
    }
  }

  #layout() {
    const custom = this.field("kind").value !== "openrouter";
    for (const part of this.root.querySelectorAll("[data-custom]")) part.hidden = !custom;
    for (const part of this.root.querySelectorAll("[data-only-new]")) part.hidden = Boolean(this.provider) || (part.hasAttribute("data-custom") && !custom);
    const plain = custom && isPlainHttp(this.field("base_url").value);
    this.root.querySelector("[data-http-warning]").hidden = !plain;
    this.root.querySelector("[data-http-confirm]").hidden = !plain; // https needs no confirmation
    // a new OpenRouter provider is named for the user; the suggestion goes when the kind changes
    const name = this.field("name");
    if (!this.provider && !custom && !name.value) name.value = "OpenRouter";
    else if (!this.provider && custom && name.value === "OpenRouter") name.value = "";
  }

  /** What the form describes, as the API takes it for a new provider. */
  #values() {
    const custom = this.field("kind").value !== "openrouter";
    const models = this.field("models")
      .value.split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    return {
      kind: this.field("kind").value,
      name: this.field("name").value.trim(),
      base_url: custom ? this.field("base_url").value.trim() : null,
      secret_name: this.field("secret_name").value.trim() || null,
      allow_http: custom && isPlainHttp(this.field("base_url").value) && this.field("allow_http").checked,
      is_default: this.field("is_default").checked,
      models: custom && !this.provider ? models.map((model_id) => ({ model_id })) : [],
      default_model: custom && !this.provider && models.length ? models[0] : null,
    };
  }

  /** A key typed into the dialog goes to the secret store first; the provider only gets the name. */
  async #storeKey(values) {
    const key = this.field("api_key").value;
    if (!key) return;
    if (!values.secret_name) throw new Error(t("agents.providers_page.name_secret_api_key_stored"));
    await putSecret(values.secret_name, key);
    this.field("api_key").value = "";
  }

  #show(result) {
    const lines = result.steps.map((step) => {
      const line = el("p", "ag-check-step", `${step.ok ? "✓" : "✗"} ${step.message}`);
      line.dataset.ok = String(step.ok);
      return line;
    });
    for (const warning of result.warnings) lines.push(el("p", "ag-warning", warning));
    this.result.replaceChildren(...lines);
    this.result.hidden = false;
  }

  async #test() {
    const values = this.#values();
    if (!values.name) values.name = "test";
    await this.#storeKey(values);
    this.#show(await testProvider(values));
  }

  async #save() {
    const values = this.#values();
    if (!values.name) throw new Error(t("agents.providers_page.please_enter_name"));
    await this.#storeKey(values);
    if (this.provider) {
      const { kind } = values;
      const changes = { ...values };
      delete changes.kind; // the kind, the models and the default model are not changed here
      delete changes.models;
      delete changes.default_model;
      if (kind === "openrouter") delete changes.base_url;
      if (kind === "openrouter") delete changes.allow_http;
      await updateProvider(this.provider.id, changes);
    } else {
      await createProvider(values);
    }
    await load();
  }
}

const dialog = new ProviderDialog(new Modal(document.getElementById("provider-modal")));

// ── the list ───────────────────────────────────────────────────────────

function tool(text, glyph, onClick, label = text, danger = false) {
  const button = el("button", `button button--ghost button--sm${danger ? " is-danger" : ""}`);
  button.type = "button";
  if (glyph) button.append(icon(glyph));
  button.append(document.createTextNode(text));
  button.setAttribute("aria-label", label);
  button.addEventListener("click", onClick);
  return button;
}

/** Run a request of the page; a refusal is shown in the alert bar, then the list is read again. */
async function act(request, message = "") {
  try {
    await request();
    banner.hide();
    if (message) banner.show(message, { autoHide: 4000 });
  } catch (error) {
    banner.show(error.detail ?? error.message, { autoHide: 12000 });
  }
  await load();
}

function modelRow(provider, model) {
  const row = el("li", "ag-model");
  row.dataset.available = String(model.available);
  row.dataset.modelId = model.model_id;
  const label = el("label");
  const box = Object.assign(el("input", "check"), { type: "checkbox", checked: model.enabled });
  box.setAttribute("aria-label", t("agents.providers_page.use_model_model_id", { model_id: model.model_id }));
  box.addEventListener("change", () => act(() => updateModel(provider.id, model.id, { enabled: box.checked })));
  label.append(box, el("span", "ag-model__id", model.model_id));
  if (model.label && model.label !== model.model_id) label.append(el("span", "ag-model__label", model.label));
  row.append(label);
  if (provider.default_model === model.model_id) row.append(chip(t("common.default"), "accent"));
  else if (model.enabled && model.available) row.append(tool(t("agents.providers_page.make_default"), null, () => act(() => updateProvider(provider.id, { default_model: model.model_id })), t("agents.providers_page.make_model_id_default_model", { model_id: model.model_id })));
  if (!model.available) row.append(chip(t("agents.providers_page.no_longer_listed"), "warn"));
  if (model.source === "manual") {
    row.append(chip(t("agents.providers_page.by_hand")));
    const remove = el("button", "icon-button icon-button--sm is-danger");
    remove.type = "button";
    remove.title = t("agents.providers_page.delete_model");
    remove.setAttribute("aria-label", t("agents.providers_page.delete_model_model_id", { model_id: model.model_id }));
    remove.append(icon("trash"));
    remove.addEventListener("click", () => act(() => deleteModel(provider.id, model.id)));
    row.append(remove);
  }
  return row;
}

function modelsBlock(provider) {
  const block = el("details", "ag-models");
  block.open = openModels.has(provider.id);
  block.addEventListener("toggle", () => (block.open ? openModels.add(provider.id) : openModels.delete(provider.id)));
  const enabled = provider.models.filter((m) => m.enabled).length;
  block.append(el("summary", "", t("agents.providers_page.models_enabled_length_switched", { enabled, length: provider.models.length })));
  const tools = el("div", "ag-models__tools");
  const list = el("ul", "ag-model-list");
  list.setAttribute("aria-label", t("agents.providers_page.models_name", { name: provider.name }));
  const filter = Object.assign(el("input", "field__control"), { type: "search", placeholder: t("agents.providers_page.filter_models"), value: filters.get(provider.id) ?? "" });
  filter.setAttribute("aria-label", t("agents.providers_page.filter_models_name", { name: provider.name }));
  const apply = () => {
    const wanted = filter.value.trim().toLowerCase();
    filters.set(provider.id, filter.value);
    for (const row of list.children) row.hidden = wanted !== "" && !row.textContent.toLowerCase().includes(wanted);
  };
  filter.addEventListener("input", apply);
  const filterField = el("div", "field");
  filterField.append(filter);
  tools.append(filterField);
  if (provider.kind !== "openrouter") {
    const name = Object.assign(el("input", "field__control"), { type: "text", placeholder: "model-id", maxLength: 200, autocomplete: "off", spellcheck: false });
    name.setAttribute("aria-label", t("agents.providers_page.model_name_define_by_hand", { name: provider.name }));
    const add = () => name.value.trim() && act(() => addModel(provider.id, { model_id: name.value.trim() }));
    name.addEventListener("keydown", (event) => event.key === "Enter" && add());
    const nameField = el("div", "field");
    nameField.append(name);
    tools.append(nameField, tool(t("agents.providers_page.add_model"), "plus", add, t("agents.providers_page.add_model_name_by_hand", { name: provider.name })));
  }
  list.append(...provider.models.map((model) => modelRow(provider, model)));
  block.append(tools, list);
  apply();
  return block;
}

function card(provider) {
  const item = el("li", "ag-provider glass");
  item.dataset.providerId = provider.id;
  const head = el("div", "ag-provider__head");
  const chips = el("span", "ag-chips");
  chips.append(chip(KINDS[provider.kind] ?? provider.kind));
  if (provider.is_default) chips.append(chip(t("agents.providers_page.default_provider"), "accent"));
  if (provider.check_ok === true) chips.append(chip(t("agents.providers_page.connection_tested"), "ok"));
  if (provider.check_ok === false) chips.append(chip(t("agents.providers_page.last_test_failed"), "bad"));
  const tools = el("div", "ag-provider__tools");
  tools.append(
    tool(t("agents.providers_page.test"), "play", () => act(async () => {
      const result = await checkProvider(provider.id);
      if (!result.ok) throw new Error(t("agents.providers_page.test_failed", { message: result.steps.find((s) => !s.ok)?.message ?? "" }));
    }, t("agents.providers_page.connection_name_works", { name: provider.name })), t("agents.providers_page.test_connection_name", { name: provider.name })),
    tool(t("agents.providers_page.refresh_models"), "refresh", () => act(() => refreshModels(provider.id), t("agents.providers_page.model_list_up_date")), t("agents.providers_page.fetch_model_list_name_again", { name: provider.name })),
    tool(t("common.edit"), "pencil", () => dialog.open(provider), t("agents.providers_page.edit_provider_name", { name: provider.name })),
    tool(t("common.delete"), "trash", () =>
      confirm.open({
        message: t("agents.providers_page.delete_provider_subject_with_its"),
        subject: provider.name,
        onConfirm: async () => {
          await deleteProvider(provider.id);
          await load();
        },
      }), t("agents.providers_page.delete_provider_name", { name: provider.name }), true),
  );
  head.append(el("h3", "ag-provider__name", provider.name), chips, tools);
  const facts = el("dl", "ag-provider__facts");
  const fact = (term, value) => facts.append(el("dt", "", term), el("dd", "", value));
  fact(t("agents.providers_page.address"), provider.base_url);
  fact("API key", provider.secret_name ? `secret ${provider.secret_name}${provider.secret_exists ? "" : t("agents.providers_page.does_not_exist_requests_will")}` : "none");
  fact(t("agents.providers_page.default_model"), provider.default_model ?? "none");
  if (provider.kind !== "openrouter" && isPlainHttp(provider.base_url)) fact("Unencrypted connection", provider.allow_http ? "confirmed (HTTP)" : "not confirmed"); // https shows nothing
  if (provider.checked_at) fact(t("credentials.last_test"), `${formatTime(provider.checked_at)}: ${provider.check_message ?? ""}`);
  item.append(head, facts, ...provider.warnings.map((warning) => el("p", "ag-warning", warning)), modelsBlock(provider));
  return item;
}

function render() {
  listEl.replaceChildren(...providers.map(card));
  emptyEl.hidden = providers.length > 0;
}

async function load() {
  try {
    providers = await listProviders();
    render();
  } catch {
    banner.show(t("agents.providers_page.providers_could_not_be_loaded"), { retry: true });
  }
}

document.querySelector("[data-new-provider]").addEventListener("click", () => dialog.open());
banner.onRetry(load);

let refresh = 0;
connectEvents({
  onClosed: () => {},
  onOpen: () => load(),
  onEvent: (type) => {
    if (type !== "providers.changed" || dialog.modal.isOpen) return;
    clearTimeout(refresh);
    refresh = setTimeout(load, 200);
  },
});
