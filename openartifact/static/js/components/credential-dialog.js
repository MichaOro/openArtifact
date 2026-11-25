/* The window that makes or changes a credential (components/credential_modal.html). It is the one place a credential is edited: the
 * Credentials page opens it, and so does the credential field of a node (a shortcut to the same data). */
import { ActionDialog } from "../components/action-dialog.js";
import { request } from "../http.js";
import { el } from "../agents/view.js";
import { t } from "../i18n.js";

const base = "/api/credentials";
const send = (method, url, body) => request(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
const one = (ref) => `${base}/${encodeURIComponent(ref)}`;

/** The window that makes or changes a credential. The Credentials page and a node's credential field both use it.
 * @param {Modal} modal the markup of components/credential_modal.html
 * @param {{types: () => object[], saved?: () => Promise<void>|void, token?: (token: string, note: string) => void}} hooks
 *   `types`: the credential types the server describes; `saved`: called after a save; `token`: shows a new access token */
export class CredentialDialog extends ActionDialog {
  constructor(modal, hooks) {
    super(modal, t("agents.providers_page.could_not_save_please_try"));
    this.hooks = hooks;
    this.only = null;
    this.onSaved = null;
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
  open(category, credential = null, { only = null, onSaved = null } = {}) {
    this.category = category;
    this.credential = credential;
    this.only = only; // the types a node's field accepts (a list of ids), or null: all of the category
    this.onSaved = onSaved;
    this.form.reset();
    this.setError("");
    this.result.hidden = true;
    const kinds = this.hooks.types().filter((t) => t.category === category && (!this.only || this.only.includes(t.id)));
    this.field("type").replaceChildren(...kinds.map((t) => new Option(t.label, t.id)));
    if (credential) this.field("type").value = credential.type;
    this.field("name").value = credential?.name ?? "";
    this.field("name").readOnly = Boolean(credential);
    this.field("description").value = credential?.description ?? "";
    this.titleEl.textContent = credential ? t("credentials.credentials_page.credential_name", { name: credential.name }) : category === "internal" ? t("credentials.credentials_page.new_access_token") : t("credentials.new_credential");
    this.root.querySelector("[data-submit-label]").textContent = credential ? t("common.save") : category === "internal" ? t("credentials.credentials_page.generate_token") : t("credentials.credentials_page.store");
    for (const part of this.root.querySelectorAll("[data-only-new]")) part.hidden = Boolean(credential) || kinds.length === 1; // one accepted type: nothing to choose
    this.root.querySelector("[data-expiry]").hidden = category !== "internal" || Boolean(credential);
    this.root.querySelector("[data-name-help]").textContent =
      category === "external" ? "Capitals, digits and underscores, starting with a letter: it is what nodes write as ${secret:NAME}." : "Says who or what the token is for, for example the CI job.";
    this.#layout();
    this.modal.open();
    this.field("name").focus();
  }

  get type() {
    return this.hooks.types().find((t) => t.id === this.field("type").value);
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
      input.placeholder = this.credential && f.secret ? t("credentials.credentials_page.leave_empty_keep_stored_value") : f.placeholder;
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
    if (!name) throw new Error(t("agents.providers_page.please_enter_name"));
    const description = this.field("description").value.trim();
    if (this.credential) {
      await send("PATCH", one(this.credential.id), { description, fields: this.#fields() });
    } else if (this.category === "internal") {
      const expires = this.field("expires").value;
      const made = await send("POST", `${base}/internal`, { type: this.field("type").value, name, description, expires_in_seconds: expires ? Number(expires) : null });
      this.hooks.token?.(made.token, t("credentials.credentials_page.use_as_authorization_bearer_token"));
    } else {
      await send("POST", `${base}/external`, { type: this.field("type").value, name, description, fields: this.#fields() });
    }
    await this.hooks.saved?.();
    await this.onSaved?.(name);
  }
}

