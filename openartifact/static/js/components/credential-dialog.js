/* The window that makes or changes a credential. It is the one place a credential is edited: the Credentials page opens it, and so
 * does the credential field of a node (a shortcut to the same data). Its form is a manifest (ui/forms/credential.yaml, ADR-062/065)
 * drawn by form-view.js, with the layout handle of every manifest window (ADR-063): the owner arranges the fields himself. The
 * fields of each kind of credential are the ones of credentials/types.py (a test keeps the manifest and the types the same). */
import { ActionDialog } from "./action-dialog.js";
import { FormView } from "./form-view.js";
import { getPath, setPath } from "./form-plan.js";
import { formStructure } from "./layout-model.js";
import { WindowLayout } from "./window-layout.js";
import { request } from "../http.js";
import { t } from "../i18n.js";

const base = "/api/credentials";
const send = (method, url, body) => request(url, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
const one = (ref) => `${base}/${encodeURIComponent(ref)}`;

/** The form manifest of the window (`GET /api/forms/credential`, in the language of the page), once until the layout changes. */
let formOnce = null;
const loadForm = () => (formOnce ??= request("/api/forms/credential").catch((error) => {
  formOnce = null;
  throw error;
}));

/** How a window asks "are you sure" when the page has no hook of its own (the editor page sets one). */
let confirmHook = null;
export function setCredentialConfirm(fn) {
  confirmHook = fn;
}

/** The key of a field of a kind of credential in the form's values (`github_pat.value`). */
const keyOf = (type, field) => `${type.id}.${field.name}`;

/**
 * @param {import("./modal.js").Modal} modal the markup of components/credential_modal.html
 * @param {{types: () => object[], saved?: () => Promise<void>|void, token?: (token: string, note: string) => void,
 *   confirm?: (options: object) => void}} hooks
 *   `types`: the credential types the server describes; `saved`: called after a save; `token`: shows a new access token;
 *   `confirm`: asks before the layout is reset (options of components/confirm-dialog.js)
 */
export class CredentialDialog extends ActionDialog {
  constructor(modal, hooks) {
    super(modal, t("agents.providers_page.could_not_save_please_try"));
    this.hooks = hooks;
    this.only = null;
    this.onSaved = null;
    this.body = this.root.querySelector("[data-credential-body]");
    this.form = this.root.querySelector("form");
    this.category = "external";
    this.credential = null;
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.run(() => this.#save());
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.layout = new WindowLayout({
      panel: this.root.querySelector(".modal__panel"),
      content: this.body,
      window: null,
      structure: () => formStructure(this.manifest),
      customised: () => Boolean(this.manifest?.layout_customised),
      reload: async () => {
        formOnce = null;
        this.manifest = await loadForm();
        this.layout.setWindow("forms/credential", { width: this.manifest.width ?? null });
        this.#draw();
      },
      confirm: (options) => (this.hooks.confirm ?? confirmHook)?.(options),
    });
    this.root.addEventListener("close", () => this.layout.cancel());
    const canClose = modal.canClose;
    modal.canClose = () => this.layout.guardClose(() => this.modal.close()) && canClose();
  }

  /** @param {"internal"|"external"} category @param {object|null} credential null: a new one
   * @param {{only?: string[]|null, onSaved?: ((name: string) => Promise<void>|void)|null}} [options] `only`: the ids of the types a node's
   *   field accepts (null: every type of the category) */
  async open(category, credential = null, { only = null, onSaved = null } = {}) {
    this.category = category;
    this.credential = credential;
    this.only = only;
    this.onSaved = onSaved;
    this.setError("");
    try {
      this.manifest = await loadForm();
      this.types = this.hooks.types().length ? this.hooks.types() : (this.fetched ??= await request(`${base}/types`));
    } catch {
      this.setError(t("credentials.credentials_page.credentials_could_not_be_loaded"));
      return;
    }
    this.kinds = this.types.filter((kind) => kind.category === category && (!only || only.includes(kind.id)));
    this.layout.setWindow("forms/credential", { width: this.manifest.width ?? null });
    this.titleEl.textContent = credential
      ? t("credentials.credentials_page.credential_name", { name: credential.name })
      : category === "internal"
        ? t("credentials.credentials_page.new_access_token")
        : t("credentials.new_credential");
    this.root.querySelector("[data-submit-label]").textContent = credential
      ? t("common.save")
      : category === "internal"
        ? t("credentials.credentials_page.generate_token")
        : t("credentials.credentials_page.store");
    this.#draw();
    this.modal.open();
    this.formView.focus(credential ? "description" : "name");
  }

  /** The values the form edits: the kind, the name, the description and, per kind, its own fields (`github_pat.base_url`). */
  #blank() {
    const kind = this.credential ? this.types.find((k) => k.id === this.credential.type) : this.kinds[0];
    const values = { type: kind?.id ?? "", name: this.credential?.name ?? "", description: this.credential?.description ?? "", expires: "never" };
    if (this.credential && kind) {
      const settings = this.credential.external?.settings ?? {};
      for (const f of kind.fields) if (!f.secret) setPath(values, keyOf(kind, f), settings[f.name] ?? "");
    }
    return values;
  }

  #draw() {
    const editing = Boolean(this.credential);
    const manifest = structuredClone(this.manifest);
    for (const section of manifest.sections) {
      // no choice of kind when one is fixed (a node's field accepts one) or the credential exists already
      section.fields = section.fields.filter((field) => !(field.key === "type" && (editing || this.kinds.length === 1)));
      // a stored value is kept when its field is left empty
      if (editing) for (const field of section.fields) if (field.config?.secret) field.required = false;
    }
    const kinds = this.kinds.map((k) => ({ value: k.id, label: k.label }));
    this.values = this.#blank();
    this.overrides = {
      type: { options: kinds, help: this.#kind(this.values.type)?.help || undefined },
      // (the help of an external credential is the manifest's; an override that says `undefined` would take it away)
      name: { ...(this.category === "internal" ? { help: t("credentials.name_help_internal") } : {}), config: { max_length: 64, readonly: editing } },
    };
    for (const kind of this.types) {
      for (const f of kind.fields) {
        if (f.secret && editing) this.overrides[keyOf(kind, f)] = { placeholder: t("credentials.credentials_page.leave_empty_keep_stored_value") };
      }
    }
    this.formView = new FormView(this.body, {
      manifest,
      values: this.values,
      overrides: this.overrides,
      normalize: (values, key) => {
        if (key === "type") this.overrides.type.help = this.#kind(values.type)?.help || undefined;
      },
    });
  }

  #kind(id) {
    return this.types.find((k) => k.id === id);
  }

  async #save() {
    if (!this.formView.validate()) throw new Error(t("credentials.fix_marked"));
    const values = this.values;
    const name = String(values.name ?? "").trim();
    const description = String(values.description ?? "").trim();
    const kind = this.#kind(values.type);
    const fields = Object.fromEntries((kind?.fields ?? []).map((f) => [f.name, String(getPath(values, keyOf(kind, f)) ?? "")]));
    if (this.credential) {
      await send("PATCH", one(this.credential.id), { description, fields });
    } else if (this.category === "internal") {
      const made = await send("POST", `${base}/internal`, { type: values.type, name, description, expires_in_seconds: values.expires && values.expires !== "never" ? Number(values.expires) : null });
      this.hooks.token?.(made.token, t("credentials.credentials_page.use_as_authorization_bearer_token"));
    } else {
      await send("POST", `${base}/external`, { type: values.type, name, description, fields });
    }
    await this.hooks.saved?.();
    await this.onSaved?.(name);
  }
}
