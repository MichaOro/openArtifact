/* The credentials page (ADR-051): access tokens OpenArtifact makes (internal) and values users give for other
 * systems (external). A token is shown once, in its own dialog; nothing here ever holds a stored value. */
import { ActionMenu } from "../components/action-menu.js";
import { AlertBar } from "../components/alert-bar.js";
import { CredentialDialog } from "../components/credential-dialog.js";
import { ConfirmDialog } from "../components/confirm-dialog.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { Tabs } from "../components/tabs.js";
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";
import { formatTime } from "../tasks/history-format.js";
import { chip, el } from "../agents/view.js";
import { t, tn } from "../i18n.js";

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
        this.copy.querySelector("span").textContent = t("credentials.credentials_page.copied");
      } catch {
        this.copy.querySelector("span").textContent = t("credentials.credentials_page.select_copy_by_hand");
        getSelection().selectAllChildren(this.tokenEl);
      }
    });
  }

  show(token, note) {
    this.tokenEl.textContent = token;
    this.copy.querySelector("span").textContent = t("credentials.copy");
    modalNote(this.modal.dialog, note);
    this.modal.open();
    this.tokenEl.focus();
  }
}

function modalNote(dialog, text) {
  dialog.querySelector("[data-token-note]").textContent = text;
}

const tokenDialog = new TokenDialog(new Modal(document.getElementById("token-modal")));

const dialog = new CredentialDialog(new Modal(document.getElementById("credential-modal")), {
  types: () => types,
  saved: () => load(),
  token: (token, note) => tokenDialog.show(token, note),
});

// ── the lists ──────────────────────────────────────────────────────────

const STATUS = { active: [t("common.active"), "ok"], disabled: [t("credentials.credentials_page.disabled"), "warn"], expired: [t("credentials.credentials_page.expired"), "bad"], revoked: [t("credentials.credentials_page.revoked"), "bad"] };

function statusChip(c) {
  const [text, tone] = STATUS[c.status] ?? [c.status, ""];
  return chip(text, tone);
}

function testChip(c) {
  const meta = c.external;
  if (meta.last_test_ok === true) return chip(t("credentials.credentials_page.passed"), "ok");
  if (meta.last_test_ok === false) return chip(t("common.failed"), "bad");
  return chip(types.find((t) => t.id === c.type)?.testable ? t("credentials.credentials_page.not_tested") : t("credentials.credentials_page.no_test_type"));
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
    return found.length ? t("credentials.page.still_referred", { list: found.map((u) => `${u.name} (${u.where})`).join(", ") }) : t("credentials.page.nobody_refers");
  } catch {
    return "";
  }
}

function askToDelete(credential) {
  impact(credential).then((note) =>
    confirm.open({
      title: t("credentials.credentials_page.delete_credential"),
      message: credential.category === "internal" ? t("credentials.credentials_page.delete_subject_its_tokens_stop") : t("credentials.credentials_page.delete_subject_with_its_stored"),
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
    if (credential.status !== "revoked") items.push({ label: t("credentials.credentials_page.rotate"), icon: "refresh", onSelect: () => rotate(credential) });
    if (credential.status !== "revoked")
      items.push({ label: credential.enabled ? t("credentials.credentials_page.disable") : t("credentials.credentials_page.enable"), icon: credential.enabled ? "stop" : "play", onSelect: () => act(() => send("PUT", `${one(credential.id)}/enabled`, { enabled: !credential.enabled })) });
    if (credential.status !== "revoked") items.push({ label: t("credentials.credentials_page.revoke"), icon: "x", danger: true, onSelect: () => revoke(credential) });
  } else {
    const testable = types.find((t) => t.id === credential.type)?.testable;
    items.push({ label: t("providers.test_connection"), icon: "play", disabledReason: testable ? (credential.enabled ? undefined : t("credentials.credentials_page.enable_first")) : t("credentials.credentials_page.there_no_connection_test_type"), onSelect: () => act(async () => {
      const done = await send("POST", `${one(credential.id)}/test`);
      if (!done.external.last_test_ok) throw new Error(t("credentials.credentials_page.test_failed_last_test_message", { last_test_message: done.external.last_test_message }));
    }, t("credentials.credentials_page.test_passed")) });
    items.push({ label: t("common.edit"), icon: "pencil", onSelect: () => dialog.open("external", credential) });
    items.push({ label: credential.enabled ? t("credentials.credentials_page.disable") : t("credentials.credentials_page.enable"), icon: credential.enabled ? "stop" : "play", onSelect: () => act(() => send("PUT", `${one(credential.id)}/enabled`, { enabled: !credential.enabled })) });
  }
  items.push({ label: t("credentials.credentials_page.delete"), icon: "trash", danger: true, onSelect: () => askToDelete(credential) });
  menu.toggle(button, items, `Actions of ${credential.name}`);
}

function rotate(credential) {
  confirm.open({
    title: t("credentials.credentials_page.rotate_token"),
    message: t("credentials.credentials_page.make_new_token_subject_old"),
    subject: credential.name,
    confirmLabel: t("credentials.credentials_page.rotate_2"),
    tone: "primary",
    onConfirm: async () => {
      const made = await send("POST", `${one(credential.id)}/rotate`, {});
      await load();
      tokenDialog.show(made.token, t("credentials.credentials_page.old_token_works_while_longer"));
    },
  });
}

function revoke(credential) {
  confirm.open({
    title: t("credentials.credentials_page.revoke_credential"),
    message: t("credentials.credentials_page.revoke_subject_every_token_stops"),
    subject: credential.name,
    confirmLabel: t("credentials.credentials_page.revoke_2"),
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
  button.title = t("credentials.credentials_page.actions_name", { name: credential.name });
  button.setAttribute("aria-label", t("credentials.credentials_page.actions_name", { name: credential.name }));
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
  if (grace) status.append(chip(t("credentials.credentials_page.old_token_still_valid"), "warn"));
  row.append(nameCell(c), el("td", "", c.type_label), status, el("td", "", c.internal.expires_at ? formatTime(c.internal.expires_at) : t("credentials.never")), el("td", "", formatTime(c.created_at)), actionsCell(c));
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
  const used = el("td", "", uses.has(c.name) ? (uses.get(c.name) === 0 ? t("credentials.page.nothing") : tn("credentials.page.used_by", uses.get(c.name))) : "…");
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
    banner.show(t("credentials.credentials_page.credentials_could_not_be_loaded"), { retry: true });
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
