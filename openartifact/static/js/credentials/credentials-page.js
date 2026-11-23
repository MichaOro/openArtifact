/* The credentials page (ADR-051): access tokens OpenArtifact makes (internal) and values users give for other
 * systems (external). A token is shown once, in its own dialog; nothing here ever holds a stored value. */
import { ActionDialog } from "../components/action-dialog.js";
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { Tabs } from "../components/tabs.js";
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { chip, el } from "../agents/view.js";

const base = "/api/credentials";
const one = (ref) => `${base}/${encodeURIComponent(ref)}`;
const send = (method, url, body) => request(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

const banner = new AlertBar();
const menu = new ActionMenu();
const confirm = new ConfirmDialog(new Modal(document.getElementById("confirm-modal")));
const tabs = new Tabs(document.querySelector("[data-cred-tabs]"));
const lists = { internal: document.querySelector('[data-list="internal"]'), external: document.querySelector('[data-list="external"]') };
const empties = { internal: document.querySelector('[data-empty="internal"]'), external: document.querySelector('[data-empty="external"]') };

let types = [];
let credentials = [];
/** name -> uses of external credentials (null while unknown): "Used by" is only what the application can see. */
const uses = new Map();

// ── dialogs ────────────────────────────────────────────────────────────

class TokenDialog {
  constructor(modal) {
    this.modal = modal;
    this.tokenEl = modal.dialog.querySelector("[data-token]");
    this.copy = modal.dialog.querySelector("[data-copy]");
    // the token leaves the page with the dialog: it is shown once and must not stay in the document
    modal.dialog.addEventListener("close", () => this.tokenEl.replaceChildren());
    this.copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(this.tokenEl.textContent);
        this.copy.querySelector("span").textContent = "Copied";
      } catch {
        this.copy.querySelector("span").textContent = "Select and copy by hand";
        getSelection().selectAllChildren(this.tokenEl);
      }
    });
  }

  show(token, note) {
    this.tokenEl.textContent = token;
    this.copy.querySelector("span").textContent = "Copy";
    modalNote(this.modal.dialog, note);
    this.modal.open();
    this.tokenEl.focus();
  }
}

function modalNote(dialog, text) {
  dialog.querySelector("[data-token-note]").textContent = text;
}

const tokenDialog = new TokenDialog(new Modal(document.getElementById("token-modal")));

class CredentialDialog extends ActionDialog {
  constructor(modal) {
    super(modal, "Could not save. Please try again.");
    this.form = this.root.querySelector("form");
    this.dynamic = this.root.querySelector("[data-dynamic]");
    this.result = this.root.querySelector("[data-test-result]");
    this.category = "external";
    this.credential = null;
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.run(() => this.#save());
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.field("type").addEventListener("change", () => this.#layout());
  }

  field(name) {
    return this.form.elements.namedItem(name);
  }

  /** @param {"internal"|"external"} category @param {object|null} credential null: a new one */
  open(category, credential = null) {
    this.category = category;
    this.credential = credential;
    this.form.reset();
    this.setError("");
    this.result.hidden = true;
    const kinds = types.filter((t) => t.category === category);
    this.field("type").replaceChildren(...kinds.map((t) => new Option(t.label, t.id)));
    if (credential) this.field("type").value = credential.type;
    this.field("name").value = credential?.name ?? "";
    this.field("name").readOnly = Boolean(credential);
    this.field("description").value = credential?.description ?? "";
    this.titleEl.textContent = credential ? `Credential ${credential.name}` : category === "internal" ? "New access token" : "New credential";
    this.root.querySelector("[data-submit-label]").textContent = credential ? "Save" : category === "internal" ? "Generate token" : "Store";
    for (const part of this.root.querySelectorAll("[data-only-new]")) part.hidden = Boolean(credential);
    this.root.querySelector("[data-expiry]").hidden = category !== "internal" || Boolean(credential);
    this.root.querySelector("[data-name-help]").textContent =
      category === "external" ? "Capitals, digits and underscores, starting with a letter: it is what nodes write as ${secret:NAME}." : "Says who or what the token is for, for example the CI job.";
    this.#layout();
    this.modal.open();
    this.field("name").focus();
  }

  get type() {
    return types.find((t) => t.id === this.field("type").value);
  }

  #layout() {
    const type = this.type;
    this.root.querySelector("[data-type-help]").textContent = type?.help ?? "";
    this.dynamic.replaceChildren();
    if (this.category !== "external" || !type) return;
    const settings = this.credential?.external?.settings ?? {};
    for (const f of type.fields) {
      const wrap = el("div", "field");
      const id = `cr-f-${f.name}`;
      const label = el("label", "field__label", f.label);
      label.htmlFor = id;
      const input = el("input", "field__control");
      Object.assign(input, { id, name: `f_${f.name}`, type: f.secret ? "password" : "text", autocomplete: f.secret ? "new-password" : "off", spellcheck: false, maxLength: 8192 });
      input.placeholder = this.credential && f.secret ? "Leave empty to keep the stored value" : f.placeholder;
      if (!f.secret) input.value = settings[f.name] ?? "";
      wrap.append(label, input);
      if (f.help) wrap.append(el("p", "field__help", f.help));
      this.dynamic.append(wrap);
    }
  }

  #fields() {
    return Object.fromEntries((this.type?.fields ?? []).map((f) => [f.name, this.form.elements.namedItem(`f_${f.name}`).value]));
  }

  async #save() {
    const name = this.field("name").value.trim();
    if (!name) throw new Error("Please enter a name.");
    const description = this.field("description").value.trim();
    if (this.credential) {
      await send("PATCH", one(this.credential.id), { description, fields: this.#fields() });
    } else if (this.category === "internal") {
      const expires = this.field("expires").value;
      const made = await send("POST", `${base}/internal`, { type: this.field("type").value, name, description, expires_in_seconds: expires ? Number(expires) : null });
      tokenDialog.show(made.token, "Use it as: Authorization: Bearer <token>");
    } else {
      await send("POST", `${base}/external`, { type: this.field("type").value, name, description, fields: this.#fields() });
    }
    await load();
  }
}

const dialog = new CredentialDialog(new Modal(document.getElementById("credential-modal")));

// ── the lists ──────────────────────────────────────────────────────────

const STATUS = { active: ["Active", "ok"], disabled: ["Disabled", "warn"], expired: ["Expired", "bad"], revoked: ["Revoked", "bad"] };

function statusChip(c) {
  const [text, tone] = STATUS[c.status] ?? [c.status, ""];
  return chip(text, tone);
}

function testChip(c) {
  const meta = c.external;
  if (meta.last_test_ok === true) return chip("Passed", "ok");
  if (meta.last_test_ok === false) return chip("Failed", "bad");
  return chip(types.find((t) => t.id === c.type)?.testable ? "Not tested" : "No test for this type");
}

async function act(run, message = "") {
  try {
    await run();
    banner.hide();
    if (message) banner.show(message, { autoHide: 4000 });
  } catch (error) {
    banner.show(error.detail ?? error.message, { autoHide: 12000 });
  }
  await load();
}

/** What would stop working, from what the application can see (nodes and providers); the rest it cannot know. */
async function impact(credential) {
  try {
    const found = await request(`${one(credential.id)}/uses`);
    return found.length ? `Still referred to by: ${found.map((u) => `${u.name} (${u.where})`).join(", ")}. They will fail until the credential exists again.` : "No node or provider refers to it.";
  } catch {
    return "";
  }
}

function askToDelete(credential) {
  impact(credential).then((note) =>
    confirm.open({
      title: "Delete credential",
      message: credential.category === "internal" ? "Delete {subject}? Its tokens stop working at once." : "Delete {subject} with its stored value?",
      subject: credential.name,
      note,
      onConfirm: async () => {
        await send("DELETE", one(credential.id));
        await load();
      },
    }),
  );
}

function openMenu(button, credential) {
  const items = [];
  const internal = credential.category === "internal";
  if (internal) {
    if (credential.status !== "revoked") items.push({ label: "Rotate…", icon: "refresh", onSelect: () => rotate(credential) });
    if (credential.status !== "revoked")
      items.push({ label: credential.enabled ? "Disable" : "Enable", icon: credential.enabled ? "stop" : "play", onSelect: () => act(() => send("PUT", `${one(credential.id)}/enabled`, { enabled: !credential.enabled })) });
    if (credential.status !== "revoked") items.push({ label: "Revoke…", icon: "x", danger: true, onSelect: () => revoke(credential) });
  } else {
    const testable = types.find((t) => t.id === credential.type)?.testable;
    items.push({ label: "Test connection", icon: "play", disabledReason: testable ? (credential.enabled ? undefined : "Enable it first") : "There is no connection test for this type", onSelect: () => act(async () => {
      const done = await send("POST", `${one(credential.id)}/test`);
      if (!done.external.last_test_ok) throw new Error(`The test failed: ${done.external.last_test_message}`);
    }, "The test passed.") });
    items.push({ label: "Edit", icon: "pencil", onSelect: () => dialog.open("external", credential) });
    items.push({ label: credential.enabled ? "Disable" : "Enable", icon: credential.enabled ? "stop" : "play", onSelect: () => act(() => send("PUT", `${one(credential.id)}/enabled`, { enabled: !credential.enabled })) });
  }
  items.push({ label: "Delete…", icon: "trash", danger: true, onSelect: () => askToDelete(credential) });
  menu.toggle(button, items, `Actions of ${credential.name}`);
}

function rotate(credential) {
  confirm.open({
    title: "Rotate token",
    message: "Make a new token for {subject}? The old one keeps working for the grace period (1 hour by default), then stops.",
    subject: credential.name,
    confirmLabel: "Rotate",
    tone: "primary",
    onConfirm: async () => {
      const made = await send("POST", `${one(credential.id)}/rotate`, {});
      await load();
      tokenDialog.show(made.token, "The old token works for a while longer, then stops.");
    },
  });
}

function revoke(credential) {
  confirm.open({
    title: "Revoke credential",
    message: "Revoke {subject}? Every token of it stops working at the next request, and this cannot be undone.",
    subject: credential.name,
    confirmLabel: "Revoke",
    onConfirm: async () => {
      await send("POST", `${one(credential.id)}/revoke`);
      await load();
    },
  });
}

function actionsCell(credential) {
  const cell = el("td");
  const button = el("button", "icon-button icon-button--sm");
  button.type = "button";
  button.title = `Actions of ${credential.name}`;
  button.setAttribute("aria-label", `Actions of ${credential.name}`);
  button.append(icon("more"));
  button.addEventListener("click", () => openMenu(button, credential));
  cell.append(button);
  return cell;
}

function nameCell(c) {
  const cell = el("td");
  cell.append(el("span", "cred-name", c.name));
  if (c.description) cell.append(el("span", "cred-sub", c.description));
  return cell;
}

function internalRow(c) {
  const row = el("tr");
  row.dataset.credential = c.name;
  const grace = c.internal.tokens.filter((t) => t.state === "grace").length;
  const status = el("td");
  status.append(statusChip(c));
  if (grace) status.append(chip("Old token still valid", "warn"));
  row.append(nameCell(c), el("td", "", c.type_label), status, el("td", "", c.internal.expires_at ? formatTime(c.internal.expires_at) : "Never"), el("td", "", formatTime(c.created_at)), actionsCell(c));
  return row;
}

function externalRow(c) {
  const row = el("tr");
  row.dataset.credential = c.name;
  const status = el("td");
  status.append(statusChip(c));
  const test = el("td");
  test.append(testChip(c));
  if (c.external.last_test_at) test.append(el("span", "cred-sub", `${formatTime(c.external.last_test_at)}${c.external.last_test_message ? `: ${c.external.last_test_message}` : ""}`));
  const used = el("td", "", uses.has(c.name) ? (uses.get(c.name) === 0 ? "Nothing" : `${uses.get(c.name)} node${uses.get(c.name) === 1 ? "" : "s"} or provider${uses.get(c.name) === 1 ? "" : "s"}`) : "…");
  row.append(nameCell(c), el("td", "", c.type_label), status, test, used, actionsCell(c));
  return row;
}

function render() {
  const internal = credentials.filter((c) => c.category === "internal");
  const external = credentials.filter((c) => c.category === "external");
  lists.internal.replaceChildren(...internal.map(internalRow));
  lists.external.replaceChildren(...external.map(externalRow));
  empties.internal.hidden = internal.length > 0;
  empties.external.hidden = external.length > 0;
}

async function loadUses() {
  await Promise.all(
    credentials
      .filter((c) => c.category === "external")
      .map(async (c) => {
        try {
          uses.set(c.name, (await request(`${one(c.id)}/uses`)).length);
        } catch {
          uses.delete(c.name);
        }
      }),
  );
  render();
}

async function load() {
  try {
    [types, credentials] = await Promise.all([types.length ? types : request(`${base}/types`), request(base)]);
    render();
    loadUses();
  } catch {
    banner.show("Credentials could not be loaded.", { retry: true });
  }
}

for (const button of document.querySelectorAll("[data-new]")) button.addEventListener("click", () => dialog.open(button.dataset.new));
banner.onRetry(load);

let refresh = 0;
connectEvents({
  onClosed: () => {},
  onOpen: () => load(),
  onEvent: (type) => {
    if (type !== "credentials.changed" || dialog.modal.isOpen) return;
    clearTimeout(refresh);
    refresh = setTimeout(load, 200);
  },
});
