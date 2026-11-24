/* The attach dialog of the guards (ADR-060): "Attach guard…" of the shield popup opens it. One field, a combobox
 * (components/combobox.js) of the guards of the library that may watch the scope and are not attached to it yet; typing
 * narrows the list (name first, then its description and what it does: "hea" finds the Health guard and a guard that
 * says it watches health). Attach is there once one is chosen. */
import { Combobox } from "../components/combobox.js";
import { t } from "../i18n.js";
import * as model from "./model.js";

export class GuardAttachDialog {
  /**
   * @param {import("../components/modal.js").Modal} modal the #guard-attach-modal (templates/components/guard_attach_modal.html)
   * @param {{attach: (guard: object, scope: object) => Promise<void>}} hooks
   */
  constructor(modal, hooks) {
    this.modal = modal;
    this.hooks = hooks;
    this.root = modal.dialog;
    this.submit = this.root.querySelector("[data-submit]");
    this.scopeText = this.root.querySelector("[data-attach-scope]");
    this.box = new Combobox(this.root.querySelector("[data-attach-combobox]"), {
      label: t("guards.guard"),
      options: [],
      placeholder: t("guards.attach_placeholder"),
      emptyText: t("guards.no_match"),
      onChange: (option) => {
        this.submit.disabled = !option;
      },
    });
    this.root.querySelector("[data-cancel]").addEventListener("click", () => this.modal.close());
    this.root.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const chosen = this.box.selected;
      if (!chosen) return;
      this.submit.disabled = true;
      this.modal.close(); // first: closing gives the focus back to where the dialog was opened, the popup then takes it
      await this.hooks.attach(chosen.guard, this.scope);
    });
  }

  /** Open it for a scope: `guards` is the library (with its attachments), `schema` the rule builder's guard schema. */
  open({ scope, guards, schema }) {
    this.scope = scope;
    this.box.input.value = "";
    this.box.selected = null;
    this.submit.disabled = true;
    this.box.setOptions(
      model.attachable(guards, scope.type, scope.id).map((guard) => ({ value: guard.id, label: guard.name, description: model.summaryLine(guard, schema), keywords: guard.description ?? "", guard })),
    );
    this.scopeText.textContent = t(`guards.attach_to_${scope.type}`, { name: scope.name });
    this.modal.open();
    this.box.focus();
  }
}
