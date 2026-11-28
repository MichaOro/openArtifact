/* The retention rules of the execution list: which finished executions are deleted. One dialog with two views in the same
 * frame: the list of rules (a name, a switch and a line about what each does) and, after a click on one, that rule in
 * the rule builder, with its name in the title ("Retention – name") and the way back next to the close button. Saving applies the rules that are on to what exists; the dialog says beforehand how many
 * executions that deletes. */
import { ActionDialog } from "../components/action-dialog.js";
import { RuleEditor } from "../components/rule-editor.js";
import { RuleList } from "../components/rule-list.js";
import * as listModel from "../components/rule-list-model.js";
import { InlineName } from "../components/inline-name.js";
import { icon } from "../components/icons.js";
import * as model from "../components/rule-model.js";
import { request } from "../http.js";
import { t, tn } from "../i18n.js";

const URL = "/api/settings/retention";
const PREVIEW_MS = 350;

const SCHEMA = {
  actions: [{ key: "delete", label: t("executions.retention_dialog.delete_execution"), phrase: t("executions.retention_dialog.delete_finished_executions_where"), effect: "deletes" }],
  fields: [
    {
      key: "status",
      label: t("common.status"),
      kind: "choice",
      options: [{ value: "done", label: t("common.done") }, { value: "failed", label: t("common.failed") }, { value: "stopped", label: t("common.stopped") }],
      operators: [{ key: "is", label: t("executions.retention_dialog.is") }, { key: "is_not", label: t("executions.retention_dialog.not") }],
    },
    {
      key: "pipeline",
      label: t("common.pipeline"),
      kind: "text",
      placeholder: t("executions.name_or_part_of_it"),
      operators: [{ key: "is", label: t("executions.retention_dialog.is") }, { key: "is_not", label: t("executions.retention_dialog.not") }, { key: "contains", label: t("executions.retention_dialog.contains") }],
    },
    {
      key: "started_by",
      label: t("executions.started_by"),
      kind: "choice",
      options: [{ value: "user", label: t("common.user") }, { value: "api", label: "API" }, { value: "mcp", label: "MCP" }, { value: "system", label: t("common.system") }],
      operators: [{ key: "is", label: t("executions.retention_dialog.is") }, { key: "is_not", label: t("executions.retention_dialog.not") }],
    },
    { key: "age", label: t("executions.retention_dialog.age"), kind: "duration", operators: [{ key: "older_than", label: t("executions.retention_dialog.older_than") }] },
    {
      key: "position",
      label: t("executions.retention_dialog.position_among_artifact_s_executions"),
      kind: "count",
      default: 50,
      operators: [{ key: "beyond", label: t("executions.retention_dialog.beyond_newest") }],
    },
  ],
};

export class RetentionDialog extends ActionDialog {
  /** @param {import("../components/modal.js").Modal} modal @param {{onSaved: (deleted: number) => void}} hooks */
  constructor(modal, { onSaved }) {
    super(modal, t("executions.retention_dialog.rules_could_not_be_saved"));
    this.onSaved = onSaved;
    this.form = this.root.querySelector("form");
    this.text = this.root.querySelector("[data-rule-text]");
    this.preview = this.root.querySelector("[data-preview]");
    this.label = this.root.querySelector("[data-submit-label]");
    this.listView = this.root.querySelector('[data-view="list"]');
    this.detailView = this.root.querySelector('[data-view="detail"]');
    this.#buildHeader();
    this.index = -1; // the open rule, or -1 for the list
    this.list = new RuleList(this.root.querySelector("[data-rules]"), SCHEMA, {
      onChange: () => this.#changed(),
      onOpen: (index) => this.#openRule(index),
    });
    this.editor = new RuleEditor(this.root.querySelector("[data-rule-editor]"), SCHEMA, {
      onChange: (change) => this.list.patch(this.index, change),
    });
    this.root.querySelector("[data-done]").addEventListener("click", () => this.#showList());
    // Escape in an open rule goes back to the list; only from the list does it close the dialog.
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key !== "Escape" || this.index < 0 || !this.modal.isOpen) return;
        if (event.target.closest?.(".inline-name--editing")) return; // Escape in the name field only leaves the field
        event.preventDefault();
        event.stopPropagation();
        this.#showList();
      },
      true,
    );
    this.timer = 0;
    this.turn = 0;
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.run(() => this.#save());
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
  }

  async open() {
    this.setError("");
    this.list.load([]);
    this.#showList(false);
    this.#describe();
    this.modal.open();
    try {
      const stored = await request(URL);
      this.list.load(stored.rules);
      this.#changed();
    } catch {
      this.setError(t("executions.retention_dialog.rules_could_not_be_loaded"));
    }
  }

  /** Show the rules as a list; the rule that was open gets the focus back. */
  #showList(focus = true) {
    const was = this.index;
    this.index = -1;
    this.detailView.hidden = true;
    this.listView.hidden = false;
    this.#showTitle();
    if (focus && was >= 0) this.list.focusRow(was);
  }

  /** Show one rule in the same frame: its name in the title, then the rule builder; the way back is in the header. */
  #openRule(index) {
    const rule = this.list.rules[index];
    this.index = index;
    this.listView.hidden = true;
    this.detailView.hidden = false;
    this.nameText.emptyText = listModel.labelOf({ name: "" }, index);
    this.nameText.setText(rule.name);
    this.#showTitle();
    this.editor.load(rule);
    this.nameText.element.focus();
  }

  /** The header: in the list the title is "Retention"; in an open rule it is "Retention – <name>" (the name renames the
   * rule in place, as every name does) and a back button sits next to the close button. */
  #buildHeader() {
    const header = this.root.querySelector(".modal__header");
    this.title = header.querySelector(".modal__title");
    const lead = Object.assign(document.createElement("span"), { className: "rl-title__lead", textContent: this.title.textContent });
    const sep = Object.assign(document.createElement("span"), { className: "rl-title__sep", textContent: " – " });
    sep.setAttribute("aria-hidden", "true");
    const name = Object.assign(document.createElement("span"), { className: "rl-title__name" });
    this.nameText = new InlineName(name, {
      label: t("components.rule_list.rule_name"),
      maxLength: 80,
      allowEmpty: true,
      onCommit: (value) => {
        this.list.patch(this.index, { name: value });
        this.nameText.setText(value);
      },
    });
    this.titleParts = [sep, name];
    this.title.classList.add("rl-title");
    this.title.replaceChildren(lead);
    this.back = Object.assign(document.createElement("button"), { type: "button", className: "button button--ghost button--sm rl-back", hidden: true });
    this.back.dataset.back = "";
    this.back.setAttribute("aria-label", t("components.rule_list.back_to_rules"));
    this.back.append(icon("chevron-left"), Object.assign(document.createElement("span"), { textContent: t("components.rule_list.rules") }));
    header.insertBefore(this.back, header.querySelector("[data-modal-close]"));
    this.back.addEventListener("click", () => this.#showList());
  }

  #showTitle() {
    const open = this.index >= 0;
    this.title.replaceChildren(this.title.firstElementChild, ...(open ? this.titleParts : []));
    this.back.hidden = !open;
  }

  #describe() {
    const rules = this.list.rules;
    const sentences = listModel.activeSentences(rules, SCHEMA);
    const none = listModel.kept(rules).length > 0 && listModel.countOn(rules) === 0 ? t("executions.retention_dialog.all_rules_are_off") : t("executions.retention_dialog.no_rules_nothing_happens_executions");
    this.text.replaceChildren(...(sentences.length ? sentences.map((s) => Object.assign(document.createElement("span"), { textContent: `${s.label}: ${s.text} ` })) : [document.createTextNode(none)]));
  }

  /** A rule changed: say it in words, and ask the server how many executions the rules match now. */
  #changed() {
    this.#describe();
    window.clearTimeout(this.timer);
    const rules = listModel.kept(this.list.rules);
    const complete = rules.every((r) => model.isComplete(r.when));
    this.submitButton.disabled = !complete;
    this.preview.hidden = true;
    this.label.textContent = t("common.save");
    if (!complete) {
      this.setError(t("executions.retention_dialog.complete_every_condition_value_missing"));
      return;
    }
    this.setError("");
    const turn = (this.turn += 1);
    this.timer = window.setTimeout(async () => {
      try {
        const { matching, per_rule: perRule } = await request(`${URL}/preview`, { method: "POST", body: JSON.stringify({ rules }) });
        if (turn !== this.turn) return;
        const effect = model.effectOf(SCHEMA, rules, perRule);
        this.preview.hidden = matching === 0;
        this.preview.textContent = effect === "deletes" ? tn("executions.retention_dialog.preview_deletes", matching) : tn("executions.retention_dialog.preview_applies", matching);
        const doomed = rules.some((r, i) => perRule[i] > 0 && r.action === "delete");
        this.label.textContent = matching ? (doomed && effect === "deletes" ? t("executions.retention_dialog.save_delete_matching", { matching }) : t("executions.retention_dialog.save_apply")) : t("common.save");
      } catch {
        /* the preview is a convenience: saving still tells the truth */
      }
    }, PREVIEW_MS);
  }

  async #save() {
    const saved = await request(URL, { method: "PUT", body: JSON.stringify({ rules: listModel.kept(this.list.rules) }) });
    this.onSaved(saved.deleted);
  }
}
