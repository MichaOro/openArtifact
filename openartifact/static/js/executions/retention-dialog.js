/* The retention rules of the execution list: which finished executions are deleted, as a rule builder in a dialog.
 * Saving applies the rules to what exists; the dialog says beforehand how many executions that deletes. */
import { ActionDialog } from "../components/action-dialog.js";
import { RuleSet } from "../components/rule-set.js";
import * as model from "../components/rule-model.js";
import { request } from "../http.js";
import { plural } from "../tasks/history-format.js";
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
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: t("executions.retention_dialog.not") }],
    },
    {
      key: "pipeline",
      label: t("common.pipeline"),
      kind: "text",
      placeholder: t("executions.name_or_part_of_it"),
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: t("executions.retention_dialog.not") }, { key: "contains", label: "contains" }],
    },
    {
      key: "started_by",
      label: t("executions.started_by"),
      kind: "choice",
      options: [{ value: "user", label: t("common.user") }, { value: "api", label: "API" }, { value: "mcp", label: "MCP" }, { value: "system", label: t("common.system") }],
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: t("executions.retention_dialog.not") }],
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
    this.rules = new RuleSet(this.root.querySelector("[data-rules]"), SCHEMA, { onChange: () => this.#changed() });
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
    this.rules.load([]);
    this.#describe();
    this.modal.open();
    try {
      const stored = await request(URL);
      this.rules.load(stored.rules);
      this.#changed();
    } catch {
      this.setError(t("executions.retention_dialog.rules_could_not_be_loaded"));
    }
  }

  #describe() {
    const sentences = this.rules.read().map((rule, i) => ({ i, text: model.describeRule(rule, SCHEMA) })).filter((s) => s.text);
    this.text.replaceChildren(...(sentences.length ? sentences.map((s) => Object.assign(document.createElement("span"), { textContent: `Rule ${s.i + 1}: ${s.text} ` })) : [document.createTextNode(t("executions.retention_dialog.no_rules_nothing_happens_executions"))]));
  }

  /** A rule changed: say it in words, and ask the server how many executions the rules match now. */
  #changed() {
    this.#describe();
    window.clearTimeout(this.timer);
    const rules = this.rules.read();
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
        this.preview.textContent = tn("executions.retention_dialog.preview", matching, { effect: effect || t("executions.retention_dialog.applies_rules") });
        const doomed = rules.some((r, i) => perRule[i] > 0 && r.action === "delete");
        this.label.textContent = matching ? (doomed && effect === "deletes" ? t("executions.retention_dialog.save_delete_matching", { matching }) : t("executions.retention_dialog.save_apply")) : t("common.save");
      } catch {
        /* the preview is a convenience: saving still tells the truth */
      }
    }, PREVIEW_MS);
  }

  async #save() {
    const saved = await request(URL, { method: "PUT", body: JSON.stringify({ rules: this.rules.read() }) });
    this.onSaved(saved.deleted);
  }
}
