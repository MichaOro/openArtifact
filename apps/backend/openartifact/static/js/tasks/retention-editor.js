/* The retention editor of the history: how many executions of the artifact to keep, by count
 * and/or by age. A collapsible area with two number fields; saving replaces the policy on the
 * server, which prunes at once. The typed values are never lost: a refused save only shows why. */
import { plural } from "./history-format.js";

/** The one-line summary of a policy ({keep_last, keep_hours, effective_default_keep}). */
export function describePolicy({ keep_last: last, keep_hours: hours, effective_default_keep: fallback }) {
  const parts = [];
  if (last != null) parts.push(`newest ${last}`);
  if (hours != null) parts.push(`not older than ${plural(hours, "hour")}`);
  return parts.length ? `Keeping: ${parts.join(" and ")}` : `Default: newest ${fallback}`;
}

export class RetentionEditor {
  /**
   * @param {object} options
   * @param {HTMLDetailsElement} options.root
   * @param {(values: {keep_last: number|null, keep_hours: number|null}) => Promise<{policy: object, deleted: number}>} options.save
   * @param {(result: {policy: object, deleted: number}) => void} options.onSaved
   */
  constructor({ root, save, onSaved }) {
    this.root = root;
    this.save = save;
    this.onSaved = onSaved;
    this.busy = false;
    this.dirty = false;
    this.policy = null;
    this.form = root.querySelector("form");
    this.state = root.querySelector("[data-policy-state]");
    this.help = root.querySelector("[data-policy-help]");
    this.result = root.querySelector("[data-policy-result]");
    this.formError = root.querySelector("[data-form-error]");
    this.button = root.querySelector("[data-policy-save]");
    this.inputs = Object.fromEntries([...this.form.querySelectorAll("input")].map((input) => [input.name, input]));
    for (const input of Object.values(this.inputs)) {
      input.addEventListener("input", () => {
        this.dirty = true;
        this.#fieldError(input, "");
        this.result.textContent = "";
      });
    }
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.#submit();
    });
  }

  /** Show the policy the server has; typed but unsaved values stay. */
  setPolicy(policy) {
    this.policy = policy;
    this.state.textContent = describePolicy(policy);
    this.help.textContent =
      "Leave a field empty for no limit. With nothing set, the newest " +
      `${policy.effective_default_keep} executions are kept. With both set, an execution is kept only if it is ` +
      "among the newest N and younger than H hours. A running execution and the newest one are never removed automatically.";
    if (!this.dirty && !this.busy) this.#fill(policy);
  }

  /** Forget the typed values and the last result (another artifact). */
  reset() {
    this.dirty = false;
    this.result.textContent = "";
    this.#clearErrors();
    this.#fill({ keep_last: null, keep_hours: null });
  }

  #fill(policy) {
    this.inputs.keep_last.value = policy.keep_last ?? "";
    this.inputs.keep_hours.value = policy.keep_hours ?? "";
  }

  #read() {
    return Object.fromEntries(Object.entries(this.inputs).map(([name, input]) => [name, input.value.trim() === "" ? null : Number(input.value)]));
  }

  async #submit() {
    if (this.busy) return;
    this.#clearErrors();
    this.result.textContent = "";
    this.#setBusy(true);
    try {
      const result = await this.save(this.#read());
      this.dirty = false;
      this.#setBusy(false);
      this.setPolicy(result.policy);
      this.result.textContent = `${plural(result.deleted, "execution")} removed`;
      this.onSaved(result);
    } catch (error) {
      this.#setBusy(false);
      this.#showError(error);
    }
  }

  #showError(error) {
    const [name, message] = Object.entries(error.fieldErrors ?? {}).find(([field]) => field in this.inputs) ?? [];
    if (name !== undefined) {
      this.#fieldError(this.inputs[name], message);
      this.inputs[name].focus();
      return;
    }
    this.formError.textContent = error.detail ?? error.message ?? "Could not save. Please try again.";
    this.formError.hidden = false;
  }

  #fieldError(input, message) {
    const error = input.parentElement.querySelector("[data-field-error]");
    error.textContent = message;
    error.hidden = !message;
    input.setAttribute("aria-invalid", String(Boolean(message)));
  }

  #clearErrors() {
    for (const input of Object.values(this.inputs)) this.#fieldError(input, "");
    this.formError.textContent = "";
    this.formError.hidden = true;
  }

  #setBusy(busy) {
    this.busy = busy;
    this.button.setAttribute("aria-disabled", String(busy));
    this.button.setAttribute("aria-busy", String(busy));
  }
}
