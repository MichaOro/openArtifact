/* The guard editor (ADR-060, ADR-062): one window for one definition of the guard library, opened from the Guards page,
 * from the shield popup of a scope in the pipeline editor and from "New guard" there. Its title is "Guard – NAME" with
 * the name renamed in place (as every name of a window that saves, ADR-059); there is no Name row and no template row
 * (templates are in the page's New menu). The form itself is a manifest (ui/forms/guard.yaml) drawn by components/
 * form-view.js in two columns on a wide window: trigger and condition on the left, escalation, consequence and the
 * guard's own action (Logic) on the right; its custom widgets are in guards/widgets.js. Below it a live preview. The
 * header says in how many places the definition is used and carries the mark of the draft ("Draft", "v3 published"): Save keeps
 * the draft, and the mark's popup publishes it or throws it away (ADR-081; it saves a form that was changed first). Only the
 * published version applies where the guard is attached. */
import { FormView } from "../components/form-view.js";
import { PublicationControl } from "../editor/publication-control.js";
import { InlineName } from "../components/inline-name.js";
import { formStructure } from "../components/layout-model.js";
import { WindowLayout } from "../components/window-layout.js";
import * as rules from "../components/rule-model.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import * as model from "./model.js";
import "./widgets.js"; // registers the guard form's custom widgets

const URL = "/api/guards";
const PREVIEW_MS = 400;
const MAX_NAME = 120; // the server's limit (guards/schemas.py MAX_NAME)

const send = (url, method, data) => request(url, { method, body: JSON.stringify(data) });

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

/** What the window needs from the server once per page: the guard schema of the rule system. */
let schemaOnce = null;
export const loadSchema = () => (schemaOnce ??= request("/api/rules/schemas/guard").catch((error) => {
  schemaOnce = null;
  throw error;
}));

/** The form manifest of the editor (`GET /api/forms/guard`, in the language of the page), once per page. */
let formOnce = null;
export const loadForm = () => (formOnce ??= request("/api/forms/guard").catch((error) => {
  formOnce = null;
  throw error;
}));

export class GuardEditor {
  /**
   * @param {import("../components/modal.js").Modal} modal the #guard-modal (templates/components/guard_modal.html)
   * @param {{actionUrl: (actionId: string, guardId: string) => string, confirm: (text: string, action: () => Promise<void>, options?: {confirmLabel?: string, tone?: string}) => void,
   *   onSaved: (guard: object) => void, onDeleted?: (guard: object) => void}} hooks
   *   actionUrl: where the action editor opens an action (with the way back to here)
   */
  constructor(modal, hooks) {
    this.modal = modal;
    this.hooks = hooks;
    this.root = modal.dialog;
    this.body = this.root.querySelector("[data-guard-body]");
    this.error = this.root.querySelector("[data-form-error]");
    this.saveButton = this.root.querySelector("[data-submit]");
    this.deleteButton = this.root.querySelector("[data-delete]");
    this.root.querySelector("[data-cancel]").addEventListener("click", () => this.modal.close());
    this.root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.#save();
    });
    this.deleteButton.addEventListener("click", () => this.#delete());
    this.#buildHeader();
    // the layout handle of the window (ADR-063): its form is a manifest, so its sections and fields can be arranged
    this.layout = new WindowLayout({
      panel: this.root.querySelector(".modal__panel"),
      content: this.body,
      window: null,
      structure: () => formStructure(this.manifest),
      customised: () => Boolean(this.manifest?.layout_customised),
      reload: async () => {
        formOnce = null;
        this.manifest = await loadForm();
        this.layout.setWindow("forms/guard", { width: this.manifest.width ?? null });
        this.#draw();
      },
      confirm: ({ message, confirmLabel, onConfirm }) => this.hooks.confirm(message, async () => onConfirm(), { confirmLabel, tone: "primary" }),
    });
    this.root.addEventListener("close", () => this.layout.cancel());
    const canClose = modal.canClose;
    modal.canClose = () => this.layout.guardClose(() => this.modal.close()) && canClose();
    this.timer = 0;
    this.turn = 0;
    this.actions = [];
  }

  get isOpen() {
    return this.modal.isOpen;
  }

  /** A new definition; `attachTo` ({graphId, type, id, name}): attach it there once it is saved. */
  async openNew({ attachTo = null } = {}) {
    await this.#show(null, model.blank(""), attachTo);
    this.nameText.edit(); // a definition needs a name: the title starts as its field
  }

  /** A stored definition (as `GET /api/guards` returns it). */
  async open(guard) {
    await this.#show(guard, structuredClone({ ...guard, scope_types: guard.scope_types ?? [...model.SCOPES] }), null);
  }

  /** The header: "Guard – NAME" (the name renames in place) and, under it, how many places use the definition. */
  #buildHeader() {
    const title = this.root.querySelector(".modal__title");
    const lead = make("span", "rl-title__lead", title.textContent);
    const sep = make("span", "rl-title__sep", " – ");
    sep.setAttribute("aria-hidden", "true");
    const name = make("span", "rl-title__name gd-title__name");
    name.dataset.guardName = "";
    this.nameText = new InlineName(name, {
      label: t("guards.name_label"),
      maxLength: MAX_NAME,
      allowEmpty: true, // an empty name is refused with the reason below the field instead of being dropped silently
      keepOpenOnError: true,
      emptyText: t("guards.name_label"),
      onCommit: (value) => {
        if (!value) throw new Error(t("guards.name_needed"));
        this.state.name = value;
        this.nameText.setText(value);
        this.#setError("");
      },
    });
    title.classList.add("rl-title");
    title.replaceChildren(lead, sep, name);
    this.used = make("p", "gd-used");
    this.used.dataset.guardUsed = "";
    this.used.hidden = true;
    // the mark of the draft ("Draft", "v3 published") with its popup (Publish, Discard draft), beside how many places use the guard
    this.stateHost = make("span", "gd-state");
    this.stateHost.dataset.guardState = "";
    this.stateHost.hidden = true;
    const meta = make("div", "gd-meta"); // one line: the mark and, beside it, how many places use the guard
    meta.append(this.stateHost, this.used);
    title.after(meta);
    const calls = model.versionCalls(send);
    this.mark = new PublicationControl(this.stateHost, {
      texts: model.versionWords,
      popupParent: this.root.querySelector(".modal__panel"),
      calls: { publish: () => calls.publish(this.guard.id), discard: () => calls.discard(this.guard.id) },
      beforeAct: () => this.#store(), // a form that was changed is saved as the draft first
      onChanged: () => this.#reload(),
    });
  }

  /** The line under the title (where the guard is used, that only the published version applies there) and the mark of the draft. */
  #drawHeader() {
    const guard = this.guard;
    const count = guard?.used_by ?? 0;
    this.used.hidden = !guard;
    const parts = [count ? `${model.usedText(count)}. ${t("guards.used_note")}` : model.usedText(0)];
    if (guard && guard.published_version == null) parts.push(t("guards.not_published_note"));
    this.used.textContent = parts.join(" ");
    this.stateHost.hidden = !guard;
    if (guard) this.mark.update(guard);
  }

  /** After a publication or a discard: read the definition again (a discarded draft changes the form) and tell the page. */
  async #reload() {
    const fresh = await request(`${URL}/${this.guard.id}`);
    this.guard = fresh;
    this.state = structuredClone({ ...fresh, scope_types: fresh.scope_types ?? [...model.SCOPES] });
    this.nameText.setText(this.state.name);
    this.#setError("");
    this.#drawHeader();
    this.#draw();
    this.#preview();
    this.hooks.onSaved(fresh);
  }

  async #show(guard, state, attachTo) {
    this.guard = guard;
    this.attachTo = attachTo;
    this.state = state;
    this.#setError("");
    try {
      const [schema, actions, manifest] = await Promise.all([loadSchema(), request("/api/actions?purpose=guard"), loadForm()]);
      this.manifest = manifest;
      this.serverSchema = schema;
      this.schema = model.builderSchema(schema);
      this.actions = actions;
    } catch {
      this.actions ??= [];
      if (!this.serverSchema || !this.manifest) throw new Error(t("guards.not_loaded"));
    }
    this.layout.setWindow("forms/guard", { width: this.manifest.width ?? null });
    this.nameText.setText(state.name);
    this.saveButton.textContent = t("guards.save_draft");
    this.#drawHeader();
    this.deleteButton.hidden = !guard;
    const blocked = guard ? model.deleteBlocked(guard) : "";
    this.deleteButton.setAttribute("aria-disabled", String(Boolean(blocked)));
    this.deleteButton.title = blocked;
    this.#draw();
    this.modal.open();
    this.#preview();
  }

  #draw() {
    const parts = [];
    if (this.attachTo) parts.push(make("p", "field__help gd-scope", t(`guards.attach_after_save_${this.attachTo.type}`, { name: this.attachTo.name })));
    const host = make("div", "gd-formhost");
    this.previewEl = make("p", "field__help gd-preview");
    this.previewEl.setAttribute("role", "status");
    parts.push(host, this.previewEl);
    this.body.replaceChildren(...parts);
    this.form = new FormView(host, {
      manifest: this.manifest,
      values: this.state,
      context: this.#context(),
      overrides: this.#overrides(),
      normalize: (values, key) => this.#normalize(values, key),
      onChange: () => this.#changed(),
    });
  }

  /** What the custom widgets of the form need: the rule schema, the actions to pick from and the two buttons. */
  #context() {
    return {
      ruleSchema: this.schema,
      actions: this.actions,
      newAction: () => this.#newAction(),
      editAction: () => this.#save({ openAction: true }),
    };
  }

  /** What the code decides for the form: which consequences exist (the ones not built yet are shown but cannot be chosen). */
  #overrides() {
    const consequences = this.serverSchema.consequences;
    const options = consequences.map((c) => ({
      value: c.key,
      label: c.available ? t(`guards.consequence.${c.key}`) : `${t(`guards.consequence.${c.key}`)} (${t(`guards.needs.${c.key}`)})`,
      disabled: !c.available,
    }));
    const unavailable = consequences.filter((c) => !c.available).map((c) => t(`guards.needs.${c.key}`));
    return { consequence: { options, help: unavailable.length ? t("guards.not_yet", { list: unavailable.join("; ") }) : undefined } };
  }

  /** Switching the kind of trigger gives it what that kind needs (and drops what the other one had). */
  #normalize(values, key) {
    if (key !== "trigger.type") return;
    const trigger = values.trigger;
    values.trigger =
      trigger.type === "event"
        ? { type: "event", events: trigger.events ?? ["enter"] }
        : { type: "interval", every_seconds: trigger.every_seconds ?? 60, for_seconds: trigger.for_seconds ?? 0, cooldown_seconds: trigger.cooldown_seconds ?? 0 };
  }

  /** A new, empty action definition for this guard, chosen at once (saved with the guard). */
  async #newAction() {
    const name = t("guards.new_action_name", { name: this.state.name.trim() || t("guards.guard") });
    try {
      const created = await send("/api/actions", "POST", { name, purpose: "guard" });
      this.actions.push(created);
      this.actions.sort((a, b) => a.name.localeCompare(b.name));
      this.form.set("action_id", created.id);
      this.form.focus("action_id");
    } catch (error) {
      this.#setError(error.detail ?? t("guards.could_not_save"));
    }
  }

  // ── keeping it up to date ─────────────────────────────────────────

  #changed() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.#preview(), PREVIEW_MS);
  }

  async #preview() {
    const turn = (this.turn += 1);
    if (!this.previewEl) return;
    if (!this.guard?.used_by) {
      this.previewEl.textContent = t("guards.preview_unattached");
      return;
    }
    if (!rules.isComplete(this.state.when, this.schema) || !rules.countConditions(this.state.when)) {
      this.previewEl.textContent = t("guards.preview_empty");
      return;
    }
    try {
      const result = await send(`${URL}/preview`, "POST", { guard_id: this.guard.id, when: this.state.when });
      if (turn !== this.turn) return;
      this.previewEl.textContent = model.previewText(result);
    } catch {
      if (turn === this.turn) this.previewEl.textContent = "";
    }
  }

  /** Store the form as the draft (and attach a new definition where it was made for): the guard as the server has it now. A form with a
   * problem throws its reason (shown by the caller) and stores nothing. */
  async #store() {
    if (this.nameText.editing) {
      // the name field is still open: what it holds is the name
      const typed = this.nameText.element.querySelector("input")?.value.trim() ?? "";
      if (typed) {
        this.state.name = typed;
        this.nameText.setText(typed);
        this.nameText.element.querySelector(".inline-name__check")?.click();
      }
    }
    const fieldsOk = this.form.validate();
    const problem = model.problem(this.state, this.schema);
    if (problem || !fieldsOk) throw new Error(problem || t("guards.fix_marked"));
    const body = model.body(this.state);
    let saved = this.guard ? await send(`${URL}/${this.guard.id}`, "PATCH", body) : await send(URL, "POST", body);
    this.guard = saved;
    if (this.attachTo) {
      const place = this.attachTo;
      await send("/api/guard-attachments", "POST", { guard_id: saved.id, graph_id: place.graphId, scope_type: place.type, scope_id: model.isGraphScope(place.type) ? null : place.id });
      this.attachTo = null;
      saved = await request(`${URL}/${saved.id}`);
      this.guard = saved;
    }
    return saved;
  }

  /** Save the draft of the definition and close; `openAction`: instead open its action. */
  async #save({ openAction = false } = {}) {
    this.saveButton.disabled = true;
    try {
      let saved;
      try {
        saved = await this.#store();
      } catch (error) {
        if (!error.status && !error.fieldErrors) return this.#setError(error.message);
        throw error;
      }
      if (openAction && saved.action_id) {
        window.location.assign(this.hooks.actionUrl(saved.action_id, saved.id));
        return;
      }
      this.modal.close();
      this.hooks.onSaved(saved);
    } catch (error) {
      const fields = Object.values(error.fieldErrors ?? {});
      this.#setError(fields.length ? fields.join("; ") : (error.detail ?? error.message ?? t("guards.could_not_save")));
    } finally {
      this.saveButton.disabled = false;
    }
  }

  /** Delete after a confirmation; a definition that is used somewhere says why it cannot be deleted. */
  #delete() {
    const guard = this.guard;
    if (!guard) return;
    const blocked = model.deleteBlocked(guard);
    if (blocked) return this.#setError(blocked);
    this.hooks.confirm(t("guards.delete_question", { name: guard.name }), async () => {
      await request(`${URL}/${guard.id}`, { method: "DELETE" });
      this.modal.close();
      this.hooks.onDeleted?.(guard);
    });
  }

  #setError(message) {
    this.error.textContent = message;
    this.error.hidden = !message;
  }
}
