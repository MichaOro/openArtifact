/* The retention rules of the execution list: which finished executions are deleted, as a rule builder in a dialog.
 * Saving applies the rules to what exists; the dialog says beforehand how many executions that deletes. */
import { ActionDialog } from "../components/action-dialog.js";
import { RuleSet } from "../components/rule-set.js";
import * as model from "../components/rule-model.js";
import { request } from "../http.js";
import { plural } from "../tasks/history-format.js";

const URL = "/api/settings/retention";
const PREVIEW_MS = 350;

const SCHEMA = {
  actions: [{ key: "delete", label: "Delete the execution", phrase: "Delete finished executions where", effect: "deletes" }],
  fields: [
    {
      key: "status",
      label: "Status",
      kind: "choice",
      options: [{ value: "done", label: "Done" }, { value: "failed", label: "Failed" }, { value: "stopped", label: "Stopped" }],
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: "is not" }],
    },
    {
      key: "pipeline",
      label: "Pipeline",
      kind: "text",
      placeholder: "Name or part of it",
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: "is not" }, { key: "contains", label: "contains" }],
    },
    {
      key: "started_by",
      label: "Started by",
      kind: "choice",
      options: [{ value: "user", label: "User" }, { value: "api", label: "API" }, { value: "mcp", label: "MCP" }, { value: "system", label: "System" }],
      operators: [{ key: "is", label: "is" }, { key: "is_not", label: "is not" }],
    },
    { key: "age", label: "Age", kind: "duration", operators: [{ key: "older_than", label: "is older than" }] },
    {
      key: "position",
      label: "Position among the artifact's executions",
      kind: "count",
      default: 50,
      operators: [{ key: "beyond", label: "is beyond the newest" }],
    },
  ],
};

export class RetentionDialog extends ActionDialog {
  /** @param {import("../components/modal.js").Modal} modal @param {{onSaved: (deleted: number) => void}} hooks */
  constructor(modal, { onSaved }) {
    super(modal, "The rules could not be saved. Please try again.");
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
      this.setError("The rules could not be loaded.");
    }
  }

  #describe() {
    const sentences = this.rules.read().map((rule, i) => ({ i, text: model.describeRule(rule, SCHEMA) })).filter((s) => s.text);
    this.text.replaceChildren(...(sentences.length ? sentences.map((s) => Object.assign(document.createElement("span"), { textContent: `Rule ${s.i + 1}: ${s.text} ` })) : [document.createTextNode("No rules: nothing happens to executions automatically.")]));
  }

  /** A rule changed: say it in words, and ask the server how many executions the rules match now. */
  #changed() {
    this.#describe();
    window.clearTimeout(this.timer);
    const rules = this.rules.read();
    const complete = rules.every((r) => model.isComplete(r.when));
    this.submitButton.disabled = !complete;
    this.preview.hidden = true;
    this.label.textContent = "Save";
    if (!complete) {
      this.setError("Complete every condition (a value is missing).");
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
        this.preview.textContent = `${plural(matching, "execution")} match${matching === 1 ? "es" : ""} now: saving ${effect || "applies the rules to"} ${matching === 1 ? "it" : "them"}.`;
        const doomed = rules.some((r, i) => perRule[i] > 0 && r.action === "delete");
        this.label.textContent = matching ? (doomed && effect === "deletes" ? `Save and delete ${matching}` : "Save and apply") : "Save";
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
