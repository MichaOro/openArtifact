/* The guard editor (ADR-060): one window for one definition of the guard library, opened from the Guards page, from the
 * shield popup of a scope in the pipeline editor and from "New guard…" there. Its title is "Guard – NAME" with the name
 * renamed in place (as every name of a window that saves, ADR-059); there is no Name row and no template row
 * (templates are in the page's New menu). Two parts: Settings (the scopes it can watch, trigger, condition, escalation,
 * consequence and fallback, a live preview) and Logic (its own action for "Run the guard's action": choose an action
 * definition or make a new one, and open it in the action editor). The header says in how many places it is used: a
 * change acts on all of them. */
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { RuleBuilder } from "../components/rule-builder.js";
import * as rules from "../components/rule-model.js";
import { request } from "../http.js";
import { t, tn } from "../i18n.js";
import * as model from "./model.js";

const URL = "/api/guards";
const FALLBACKS = ["pause", "abort", "continue"];
const PREVIEW_MS = 400;
const MAX_STEPS = 10;
const MAX_NAME = 120; // the server's limit (guards/schemas.py MAX_NAME)

const send = (url, method, data) => request(url, { method, body: JSON.stringify(data) });

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

let nextId = 0;

/** A label above a control, the way the other dialogs lay out a field. */
function field(labelText, control, help = null) {
  const wrap = make("div", "field");
  control.id ||= `gd-${(nextId += 1)}`;
  const label = make("label", "field__label", labelText);
  label.htmlFor = control.id;
  wrap.append(label, control);
  if (help) wrap.append(make("p", "field__help", help));
  return wrap;
}

function number(value, min = 0, label = "") {
  const input = Object.assign(make("input", "field__control gd-number"), { type: "number", min, step: 1, value: String(value) });
  if (label) input.setAttribute("aria-label", label);
  return input;
}

function select(options, value, label = "") {
  const el = make("select", "field__control");
  for (const [key, text, disabled] of options) {
    const option = new Option(text, key);
    option.disabled = Boolean(disabled);
    el.append(option);
  }
  el.value = value;
  if (label) el.setAttribute("aria-label", label);
  return el;
}

/** Ticked chips (the rule builder's `rb-chip`) for a few choices of which several may be on. */
function checkChips(label, choices, chosen, onChange) {
  const group = make("div", "rb-choices");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", label);
  for (const [key, text] of choices) {
    const wrap = make("label", "rb-chip");
    const box = Object.assign(make("input", "rb-chip__input"), { type: "checkbox", checked: chosen.includes(key) });
    box.dataset.choice = key;
    box.addEventListener("change", () => onChange(key, box.checked));
    const tick = make("span", "rb-chip__tick");
    tick.append(icon("check"));
    wrap.append(box, tick, make("span", "", text));
    group.append(wrap);
  }
  return group;
}

function section(title, ...children) {
  const box = make("fieldset", "gd-section");
  box.append(make("legend", "gd-section__title", title), ...children);
  return box;
}

/** What the window needs from the server once per page: the guard schema of the rule system. */
let schemaOnce = null;
export const loadSchema = () => (schemaOnce ??= request("/api/rules/schemas/guard").catch((error) => {
  schemaOnce = null;
  throw error;
}));

export class GuardEditor {
  /**
   * @param {import("../components/modal.js").Modal} modal the #guard-modal (templates/components/guard_modal.html)
   * @param {{actionUrl: (actionId: string, guardId: string) => string, confirm: (text: string, action: () => Promise<void>) => void,
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
    this.timer = 0;
    this.turn = 0;
    this.actions = [];
  }

  get isOpen() {
    return this.modal.isOpen;
  }

  /** A new definition; `attachTo` ({pipelineId, type, id, name}): attach it there once it is saved. */
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
    title.after(this.used);
  }

  async #show(guard, state, attachTo) {
    this.guard = guard;
    this.attachTo = attachTo;
    this.state = state;
    this.#setError("");
    try {
      const [schema, actions] = await Promise.all([loadSchema(), request("/api/actions")]);
      this.serverSchema = schema;
      this.schema = model.builderSchema(schema);
      this.actions = actions;
    } catch {
      this.actions ??= [];
      if (!this.serverSchema) throw new Error(t("guards.not_loaded"));
    }
    this.nameText.setText(state.name);
    const count = guard?.used_by ?? 0;
    this.used.hidden = !guard;
    this.used.textContent = count ? `${model.usedText(count)}. ${t("guards.used_note")}` : model.usedText(0);
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
    parts.push(this.#settingsPart(), this.#logicPart());
    this.body.replaceChildren(...parts);
  }

  // ── Settings ──────────────────────────────────────────────────────

  #settingsPart() {
    const part = make("section", "gd-part");
    part.dataset.guardPart = "settings";
    const heading = make("h3", "gd-part__title", t("guards.settings"));
    heading.id = `gd-settings-${(nextId += 1)}`;
    part.setAttribute("aria-labelledby", heading.id);
    this.previewEl = make("p", "field__help gd-preview");
    this.previewEl.setAttribute("role", "status");
    part.append(heading, this.#scopesPart(), this.#triggerPart(), this.#conditionPart(), this.#escalationPart(), this.#consequencePart(), this.previewEl);
    return part;
  }

  #scopesPart() {
    const s = this.state;
    const chips = checkChips(
      t("guards.can_watch"),
      model.SCOPES.map((scope) => [scope, t(`guards.scope.${scope}`)]),
      s.scope_types,
      (scope, on) => {
        const chosen = new Set(s.scope_types);
        if (on) chosen.add(scope);
        else chosen.delete(scope);
        s.scope_types = model.SCOPES.filter((x) => chosen.has(x));
      },
    );
    chips.dataset.guardScopes = "";
    return section(t("guards.can_watch"), chips);
  }

  #triggerPart() {
    const s = this.state;
    const kinds = make("div", "gd-chips");
    kinds.setAttribute("role", "group");
    kinds.setAttribute("aria-label", t("guards.trigger"));
    for (const kind of ["event", "interval"]) {
      const chip = make("button", "chip-button", t(`guards.trigger_${kind}`));
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(s.trigger.type === kind));
      chip.addEventListener("click", () => {
        s.trigger =
          kind === "event"
            ? { type: "event", events: s.trigger.events ?? ["enter"] }
            : { type: "interval", every_seconds: s.trigger.every_seconds ?? 60, for_seconds: s.trigger.for_seconds ?? 0, cooldown_seconds: s.trigger.cooldown_seconds ?? 0 };
        this.#redraw();
      });
      kinds.append(chip);
    }
    const box = section(t("guards.trigger"), kinds);
    if (s.trigger.type === "event") {
      const events = checkChips(
        t("guards.events"),
        model.EVENTS.map((name) => [name, t(`guards.event.${name}`)]),
        s.trigger.events,
        (name, on) => {
          const chosen = new Set(s.trigger.events);
          if (on) chosen.add(name);
          else chosen.delete(name);
          s.trigger.events = model.EVENTS.filter((e) => chosen.has(e));
          this.#changed();
        },
      );
      box.append(events, make("p", "field__help", t("guards.event_help")));
    } else {
      const row = make("div", "gd-row");
      for (const key of ["every_seconds", "for_seconds", "cooldown_seconds"]) {
        const input = number(s.trigger[key] ?? 0, key === "every_seconds" ? 1 : 0);
        input.addEventListener("input", () => {
          s.trigger[key] = Math.max(0, Math.round(Number(input.value) || 0));
          this.#changed();
        });
        row.append(field(t(`guards.${key}`), input));
      }
      box.append(row, make("p", "field__help", t("guards.interval_help")));
    }
    return box;
  }

  #conditionPart() {
    const host = make("div");
    this.builder = new RuleBuilder(host, this.schema, {
      onChange: (tree) => {
        this.state.when = tree;
        this.#changed();
      },
    });
    this.builder.load(this.state.when);
    return section(t("guards.condition"), host);
  }

  #escalationPart() {
    const s = this.state;
    const table = make("div", "gd-steps");
    s.escalation.forEach((step, i) => {
      const row = make("div", "gd-step");
      row.setAttribute("role", "group");
      row.setAttribute("aria-label", t("guards.step_n", { n: i + 1 }));
      const from = number(step.from_firing, 1, t("guards.from_firing"));
      from.addEventListener("input", () => {
        step.from_firing = Math.max(1, Math.round(Number(from.value) || 1));
        this.#changed();
      });
      const unit = step.every_runs != null ? "runs" : "seconds";
      const amount = number(step.every_runs ?? step.every_seconds ?? 1, 1, t("guards.every_amount"));
      const kind = select([["runs", t("guards.rounds")], ["seconds", t("components.rule_builder.units.seconds")]], unit, t("guards.every_unit"));
      const update = () => {
        const n = Math.max(1, Math.round(Number(amount.value) || 1));
        delete step.every_runs;
        delete step.every_seconds;
        step[kind.value === "runs" ? "every_runs" : "every_seconds"] = n;
        this.#changed();
      };
      amount.addEventListener("input", update);
      kind.addEventListener("change", update);
      const bin = make("button", "icon-button icon-button--sm is-danger");
      bin.type = "button";
      bin.setAttribute("aria-label", t("guards.remove_step"));
      bin.title = t("guards.remove_step");
      bin.append(icon("trash"));
      bin.addEventListener("click", () => {
        s.escalation.splice(i, 1);
        this.#redraw();
      });
      row.append(make("span", "gd-step__text", t("guards.from_firing")), from, make("span", "gd-step__text", t("guards.every")), amount, kind, bin);
      table.append(row);
    });
    const add = make("button", "button button--ghost button--sm");
    add.type = "button";
    add.append(icon("plus"), document.createTextNode(t("guards.add_step")));
    add.disabled = s.escalation.length >= MAX_STEPS;
    add.addEventListener("click", () => {
      const last = s.escalation.at(-1);
      s.escalation.push({ from_firing: last ? last.from_firing + 1 : 1, every_runs: 5 });
      this.#redraw();
    });
    return section(t("guards.escalation"), make("p", "field__help", t("guards.escalation_help")), table, add);
  }

  #consequencePart() {
    const s = this.state;
    const consequences = this.serverSchema.consequences;
    const options = consequences.map((c) => [c.key, c.available ? t(`guards.consequence.${c.key}`) : `${t(`guards.consequence.${c.key}`)} (${t(`guards.needs.${c.key}`)})`, !c.available]);
    const chooser = select(options, s.consequence);
    chooser.dataset.guardConsequence = "";
    chooser.addEventListener("change", () => {
      s.consequence = chooser.value;
      this.#redraw();
    });
    const unavailable = consequences.filter((c) => !c.available).map((c) => t(`guards.needs.${c.key}`));
    const box = section(t("guards.then"), field(t("guards.consequence_label"), chooser, unavailable.length ? t("guards.not_yet", { list: unavailable.join("; ") }) : null));
    if (s.consequence === "run_action") {
      const fallback = select(FALLBACKS.map((f) => [f, t(`guards.consequence.${f}`)]), s.fallback ?? "pause");
      fallback.addEventListener("change", () => (s.fallback = fallback.value));
      box.append(field(t("guards.fallback"), fallback, t("guards.fallback_help")));
    }
    return box;
  }

  // ── Logic ─────────────────────────────────────────────────────────

  /** The guard's own action: the Definition select with New and Edit, as in a node's settings. */
  #logicPart() {
    const s = this.state;
    const part = make("section", "gd-part");
    part.dataset.guardPart = "logic";
    const heading = make("h3", "gd-part__title", t("guards.logic"));
    heading.id = `gd-logic-${(nextId += 1)}`;
    part.setAttribute("aria-labelledby", heading.id);
    part.append(heading, make("p", "field__help", t("guards.logic_help")));
    if (s.consequence !== "run_action") {
      const use = make("button", "button button--ghost button--sm");
      use.type = "button";
      use.dataset.useAction = "";
      use.append(icon("action"), document.createTextNode(t("guards.use_action")));
      use.addEventListener("click", () => {
        s.consequence = "run_action";
        this.#redraw();
        this.body.querySelector("[data-guard-action]")?.focus();
      });
      part.append(make("p", "field__help", t("guards.logic_off")), use);
      return part;
    }
    const chooser = select([["", t("guards.action_none")], ...this.actions.map((a) => [a.id, a.name])], s.action_id ?? "");
    chooser.dataset.guardAction = "";
    chooser.addEventListener("change", () => {
      s.action_id = chooser.value || null;
      this.#redraw();
    });
    const bar = make("div", "ge-actionbar gd-actionbar");
    const newButton = make("button", "button button--ghost button--sm");
    newButton.type = "button";
    newButton.dataset.newAction = "";
    newButton.append(icon("plus"), document.createTextNode(t("common.new")));
    newButton.addEventListener("click", () => this.#newAction());
    const edit = make("button", "button button--ghost button--sm");
    edit.type = "button";
    edit.dataset.editAction = "";
    edit.append(icon("pencil"), document.createTextNode(t("common.edit")));
    edit.title = t("guards.edit_saves_first");
    edit.addEventListener("click", () => this.#save({ openAction: true }));
    bar.append(newButton, edit);
    part.append(field(t("guards.action_label"), chooser, s.action_id ? t("guards.edit_saves_first") : t("guards.action_made_on_save")), bar);
    return part;
  }

  /** A new, empty action definition for this guard, chosen at once (saved with the guard). */
  async #newAction() {
    const name = t("guards.new_action_name", { name: this.state.name.trim() || t("guards.guard") });
    try {
      const created = await send("/api/actions", "POST", { name });
      this.actions = [...this.actions, created].sort((a, b) => a.name.localeCompare(b.name));
      this.state.action_id = created.id;
      this.#redraw();
      this.body.querySelector("[data-guard-action]")?.focus();
    } catch (error) {
      this.#setError(error.detail ?? t("guards.could_not_save"));
    }
  }

  // ── keeping it up to date ─────────────────────────────────────────

  #redraw() {
    const focusKey = document.activeElement?.textContent;
    this.#draw();
    if (focusKey) [...this.body.querySelectorAll("button")].find((b) => b.textContent === focusKey)?.focus();
    this.#changed();
  }

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
      this.previewEl.textContent = result.running_scopes ? tn("guards.preview_fires", result.matching, { running: result.running_scopes }) : t("guards.preview_none_running");
    } catch {
      if (turn === this.turn) this.previewEl.textContent = "";
    }
  }

  /** Save the definition (and attach a new one where it was made for); `openAction`: then open its action. */
  async #save({ openAction = false } = {}) {
    if (this.nameText.editing) {
      // the name field is still open: what it holds is the name
      const typed = this.nameText.element.querySelector("input")?.value.trim() ?? "";
      if (typed) {
        this.state.name = typed;
        this.nameText.setText(typed);
        this.nameText.element.querySelector(".inline-name__check")?.click();
      }
    }
    const problem = model.problem(this.state, this.schema);
    if (problem) return this.#setError(problem);
    const body = model.body(this.state);
    this.saveButton.disabled = true;
    try {
      let saved = this.guard ? await send(`${URL}/${this.guard.id}`, "PATCH", body) : await send(URL, "POST", body);
      this.guard = saved;
      if (this.attachTo) {
        const place = this.attachTo;
        await send("/api/guard-attachments", "POST", { guard_id: saved.id, pipeline_id: place.pipelineId, scope_type: place.type, scope_id: place.type === "pipeline" ? null : place.id });
        this.attachTo = null;
        saved = await request(`${URL}/${saved.id}`);
        this.guard = saved;
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
