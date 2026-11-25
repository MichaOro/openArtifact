/* A window whose fields are a form manifest (ui/forms/<name>.yaml, ADR-062/065): ONE component for all of them, so that a new window
 * costs a manifest and a few lines. It draws the manifest with form-view.js, carries the layout handle of every manifest window
 * (ADR-063: the owner arranges the fields himself), validates, shows what the server refuses and closes when the request went well.
 *
 *   const dialog = new ManifestDialog(new Modal(document.getElementById("action-modal")), { form: "action", confirm });
 *   dialog.open({ title, values, overrides, submitLabel, normalize, onSubmit: async (values) => {...} });
 *
 * What the code decides (the choices a field offers, what a change implies, the request) is handed in, never written in the markup. */
import { ActionDialog } from "./action-dialog.js";
import { FormView } from "./form-view.js";
import { formStructure } from "./layout-model.js";
import { WindowLayout } from "./window-layout.js";
import { request } from "../http.js";
import { t } from "../i18n.js";

export class ManifestDialog extends ActionDialog {
  /**
   * @param {import("./modal.js").Modal} modal the markup of components/manifest_modal.html
   * @param {{form: string, confirm?: (options: object) => void}} options `form`: the name of the manifest (`GET /api/forms/<form>`);
   *   `confirm`: asks before the layout is reset (options of components/confirm-dialog.js)
   */
  constructor(modal, { form, confirm = null }) {
    super(modal, t("agents.providers_page.could_not_save_please_try"));
    this.formName = form;
    this.body = this.root.querySelector("[data-manifest-body]");
    this.onSubmit = null;
    this.root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.run(() => this.#submit());
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.layout = new WindowLayout({
      panel: this.root.querySelector(".modal__panel"),
      content: this.body,
      window: null,
      structure: () => formStructure(this.manifest),
      customised: () => Boolean(this.manifest?.layout_customised),
      reload: async () => {
        this.manifest = await this.#load(true);
        this.layout.setWindow(`forms/${this.formName}`, { width: this.manifest.width ?? null });
        this.#draw();
      },
      confirm: (options) => confirm?.(options),
    });
    this.root.addEventListener("close", () => this.layout.cancel());
    const canClose = modal.canClose;
    modal.canClose = () => this.layout.guardClose(() => this.modal.close()) && canClose();
  }

  #load(again = false) {
    if (again) this.pending = null;
    this.pending ??= request(`/api/forms/${this.formName}`).catch((error) => {
      this.pending = null;
      throw error;
    });
    return this.pending;
  }

  /**
   * @param {object} options
   * @param {string} options.title the title of the window
   * @param {object} [options.values] what the form starts with (keys of the manifest's fields)
   * @param {Record<string, object>} [options.overrides] what the window decides for a field by key (`{options: [...], help, ...}`)
   * @param {(values: object, key: string) => void} [options.normalize] keeps the values consistent after a change
   * @param {string} [options.submitLabel]
   * @param {(values: object) => Promise<unknown>} options.onSubmit the request; a refusal is shown in the window
   */
  async open({ title, values = {}, overrides = {}, normalize = null, submitLabel = null, onSubmit }) {
    this.setError("");
    try {
      this.manifest = await this.#load();
    } catch {
      this.setError(t("components.manifest_dialog.could_not_be_loaded"));
      return;
    }
    this.values = structuredClone(values);
    this.overrides = overrides;
    this.normalize = normalize;
    this.onSubmit = onSubmit;
    this.titleEl.textContent = title;
    this.root.querySelector("[data-submit-label]").textContent = submitLabel ?? t("common.save");
    this.layout.setWindow(`forms/${this.formName}`, { width: this.manifest.width ?? null });
    this.#draw();
    this.modal.open();
    this.formView.focus(this.manifest.sections[0]?.fields[0]?.key);
  }

  #draw() {
    this.formView = new FormView(this.body, { manifest: this.manifest, values: this.values, overrides: this.overrides, normalize: this.normalize ?? undefined });
  }

  async #submit() {
    if (!this.formView.validate()) throw new Error(t("components.manifest_dialog.fix_marked"));
    await this.onSubmit(this.values);
  }
}
