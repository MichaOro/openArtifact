/* Guards in the pipeline editor (ADR-060): a guard watches the pipeline, a stage or an action and is shown as a
 * shield chip (the pipeline's in the tool bar, a stage's in its header, an action's in its settings), never as a
 * node of the canvas. The Guard window edits one: its trigger (events of the scope or an interval with for and
 * cooldown), its condition (the rule builder with the server's guard schema), the escalation steps, the consequence
 * (the ones that are not built yet are shown disabled with what they need), the fallback, whether it is on, and a
 * live preview of how many running scopes it would fire on now. Its own action is an action definition, edited in
 * the action editor like any other. */
import { icon } from "../components/icons.js";
import { RuleBuilder } from "../components/rule-builder.js";
import * as rules from "../components/rule-model.js";
import { createSwitch, Switch } from "../components/switch.js";
import { request } from "../http.js";
import { t, tn } from "../i18n.js";

const URL = "/api/guards";
const EVENTS = ["enter", "pass", "error", "leave", "fail"];
const FALLBACKS = ["pause", "abort", "continue"];
const PREVIEW_MS = 400;
const MAX_STEPS = 10;

const send = (url, method, data) => request(url, { method, body: JSON.stringify(data) });

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

/** A label above a control, the way the other dialogs lay out a field. */
function field(labelText, control, help = null) {
  const wrap = make("div", "field");
  const id = control.id || `gd-${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  const label = make("label", "field__label", labelText);
  label.htmlFor = id;
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

const keyOf = (fieldKey) => fieldKey.replace(/\.$/, "").replace(/\./g, "_");

/** The server's guard schema as the rule builder takes it, with its labels from the dictionary. */
export function builderSchema(schema) {
  return {
    actions: schema.consequences.map((c) => ({ key: c.key, label: t(`guards.consequence.${c.key}`), phrase: "", effect: "" })),
    fields: schema.fields.map((f) => ({
      key: f.key,
      prefix: f.prefix ?? undefined,
      kind: f.kind,
      label: t(`guards.field.${keyOf(f.key)}`),
      minimum: f.minimum,
      units: f.units,
      default: f.kind === "duration" ? 600 : f.kind === "count" ? 5 : 0,
      options: f.options.map((o) => ({ value: o, label: t(`guards.last_status.${o}`) })),
      operators: f.operators.map((o) => ({ key: o, label: t(`guards.operator.${o}`) })),
    })),
  };
}

/** How a stage header gets its chips when the canvas draws it (set by the pipeline editor). */
export const stageChips = { provider: null };

/** The shield chips of the guards of one scope; a chip opens its guard. */
export function chipsOf(guards, onOpen) {
  const row = make("span", "ge-guards");
  for (const guard of guards) {
    const chip = make("button", "chip-button ge-guards__chip");
    chip.type = "button";
    chip.dataset.guardId = guard.id;
    chip.title = t("guards.open_guard", { name: guard.name });
    chip.setAttribute("aria-label", guard.enabled ? t("guards.open_guard", { name: guard.name }) : t("guards.open_guard_off", { name: guard.name }));
    chip.classList.toggle("is-off", !guard.enabled);
    chip.append(icon("shield"), make("span", "ge-guards__name", guard.name));
    chip.addEventListener("click", (event) => {
      event.stopPropagation();
      onOpen(guard);
    });
    chip.addEventListener("pointerdown", (event) => event.stopPropagation()); // not the start of dragging the stage
    row.append(chip);
  }
  return row;
}

/** The guards of the pipeline that is edited, the schema and the templates. */
export class GuardStore {
  constructor(pipelineId) {
    this.pipelineId = pipelineId;
    this.guards = [];
    this.schema = null;
    this.templates = [];
  }

  async load() {
    const [guards, schema, templates] = await Promise.all([
      request(`${URL}?pipeline_id=${encodeURIComponent(this.pipelineId)}`),
      this.schema ? Promise.resolve(this.schema) : request("/api/rules/schemas/guard"),
      this.templates.length ? Promise.resolve(this.templates) : request(`${URL}/templates`),
    ]);
    this.guards = guards;
    this.schema = schema;
    this.templates = templates;
  }

  forScope(type, id) {
    return this.guards.filter((g) => g.scope_type === type && (type === "pipeline" || g.scope_id === id));
  }
}

/** The Guard window: one guard, new or stored. */
export class GuardDialog {
  /**
   * @param {import("../components/modal.js").Modal} modal the #guard-modal
   * @param {GuardStore} store
   * @param {{actionsPath: string, pipelineSlug: () => string, confirm: (text: string, action: () => Promise<void>) => void, onChanged: () => void}} hooks
   */
  constructor(modal, store, hooks) {
    this.modal = modal;
    this.store = store;
    this.hooks = hooks;
    this.root = modal.dialog;
    this.body = this.root.querySelector("[data-guard-body]");
    this.error = this.root.querySelector("[data-form-error]");
    this.title = this.root.querySelector(".modal__title");
    this.saveButton = this.root.querySelector("[data-submit]");
    this.deleteButton = this.root.querySelector("[data-delete]");
    this.root.querySelector("[data-cancel]").addEventListener("click", () => this.modal.close());
    this.root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.#save();
    });
    this.deleteButton.addEventListener("click", () => this.#delete());
    this.timer = 0;
    this.turn = 0;
  }

  /** A new guard on a scope (`type`: pipeline, stage or action; `name`: what the window says it watches). */
  openNew(type, id, name) {
    this.guard = null;
    this.scope = { type, id, name };
    this.#show({
      name: t("guards.new_name"),
      trigger: { type: type === "action" ? "interval" : "event", events: ["enter"], every_seconds: 60, for_seconds: 0, cooldown_seconds: 0 },
      when: rules.emptyGroup(),
      consequence: "pause",
      fallback: "pause",
      escalation: [],
      enabled: true,
      definition_id: null,
    });
  }

  open(guard, name) {
    this.guard = guard;
    this.scope = { type: guard.scope_type, id: guard.scope_id, name };
    this.#show(structuredClone(guard));
  }

  #show(state) {
    this.state = state;
    this.template = "";
    this.title.textContent = this.guard ? t("guards.guard_name", { name: this.guard.name }) : t("guards.new_guard");
    this.deleteButton.hidden = !this.guard;
    this.#setError("");
    this.#draw();
    this.modal.open();
    this.#preview();
  }

  #draw() {
    const s = this.state;
    const parts = [];
    parts.push(make("p", "field__help gd-scope", t(`guards.watches_${this.scope.type}`, { name: this.scope.name })));
    if (!this.guard) {
      const offered = this.store.templates.filter((tpl) => tpl.scope_types.includes(this.scope.type));
      const chooser = select([["", t("guards.blank")], ...offered.map((tpl) => [tpl.key, t(`guards.template.${tpl.key}`)])], this.template);
      chooser.addEventListener("change", () => this.#useTemplate(chooser.value));
      const help = this.template ? t(`guards.template.${this.template}_summary`) : t("guards.template_help");
      parts.push(field(t("guards.start_from"), chooser, help));
    }
    const name = Object.assign(make("input", "field__control"), { type: "text", maxLength: 120, value: s.name, required: true });
    name.addEventListener("input", () => (s.name = name.value));
    name.dataset.autofocus = "";
    parts.push(field(t("common.name"), name));
    parts.push(this.#triggerPart(), this.#conditionPart(), this.#escalationPart(), this.#consequencePart(), this.#enabledPart());
    this.previewEl = make("p", "field__help gd-preview");
    this.previewEl.setAttribute("role", "status");
    parts.push(this.previewEl);
    this.body.replaceChildren(...parts);
  }

  #triggerPart() {
    const s = this.state;
    const box = make("fieldset", "gd-section");
    box.append(make("legend", "gd-section__title", t("guards.trigger")));
    const kinds = make("div", "gd-chips");
    kinds.setAttribute("role", "group");
    kinds.setAttribute("aria-label", t("guards.trigger"));
    for (const kind of ["event", "interval"]) {
      const chip = make("button", "chip-button", t(`guards.trigger_${kind}`));
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(s.trigger.type === kind));
      chip.addEventListener("click", () => {
        s.trigger = kind === "event" ? { type: "event", events: s.trigger.events ?? ["enter"] } : { type: "interval", every_seconds: s.trigger.every_seconds ?? 60, for_seconds: s.trigger.for_seconds ?? 0, cooldown_seconds: s.trigger.cooldown_seconds ?? 0 };
        this.#redraw();
      });
      kinds.append(chip);
    }
    box.append(kinds);
    if (s.trigger.type === "event") {
      const events = make("div", "rb-choices");
      events.setAttribute("role", "group");
      events.setAttribute("aria-label", t("guards.events"));
      for (const name of EVENTS) {
        const label = make("label", "rb-chip");
        const box2 = Object.assign(make("input", "rb-chip__input"), { type: "checkbox", checked: s.trigger.events.includes(name) });
        box2.addEventListener("change", () => {
          const chosen = new Set(s.trigger.events);
          if (box2.checked) chosen.add(name);
          else chosen.delete(name);
          s.trigger.events = EVENTS.filter((e) => chosen.has(e));
          this.#changed();
        });
        const tick = make("span", "rb-chip__tick");
        tick.append(icon("check"));
        label.append(box2, tick, make("span", "", t(`guards.event.${name}`)));
        events.append(label);
      }
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
    const box = make("fieldset", "gd-section");
    box.append(make("legend", "gd-section__title", t("guards.condition")));
    const host = make("div");
    this.schema = builderSchema(this.store.schema);
    this.builder = new RuleBuilder(host, this.schema, { onChange: (tree) => {
      this.state.when = tree;
      this.#changed();
    } });
    this.builder.load(this.state.when);
    box.append(host);
    return box;
  }

  #escalationPart() {
    const s = this.state;
    const box = make("fieldset", "gd-section");
    box.append(make("legend", "gd-section__title", t("guards.escalation")));
    box.append(make("p", "field__help", t("guards.escalation_help")));
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
    box.append(table, add);
    return box;
  }

  #consequencePart() {
    const s = this.state;
    const box = make("fieldset", "gd-section");
    box.append(make("legend", "gd-section__title", t("guards.then")));
    const options = this.store.schema.consequences.map((c) => [c.key, c.available ? t(`guards.consequence.${c.key}`) : `${t(`guards.consequence.${c.key}`)} (${t(`guards.needs.${c.key}`)})`, !c.available]);
    const chooser = select(options, s.consequence);
    chooser.addEventListener("change", () => {
      s.consequence = chooser.value;
      this.#redraw();
    });
    const unavailable = this.store.schema.consequences.filter((c) => !c.available).map((c) => t(`guards.needs.${c.key}`));
    box.append(field(t("guards.consequence_label"), chooser, unavailable.length ? t("guards.not_yet", { list: unavailable.join("; ") }) : null));
    if (s.consequence === "run_action") {
      const fallback = select(FALLBACKS.map((f) => [f, t(`guards.consequence.${f}`)]), s.fallback ?? "pause");
      fallback.addEventListener("change", () => (s.fallback = fallback.value));
      box.append(field(t("guards.fallback"), fallback, t("guards.fallback_help")));
      if (s.definition_id) {
        const link = make("a", "button button--ghost button--sm", t("guards.edit_action"));
        link.href = `${this.hooks.actionsPath}/${encodeURIComponent(s.definition_id)}?from=${encodeURIComponent(this.hooks.pipelineSlug())}`;
        link.prepend(icon("action"));
        box.append(link);
      } else {
        box.append(make("p", "field__help", t("guards.action_made_on_save")));
      }
    }
    return box;
  }

  #enabledPart() {
    const wrap = make("div", "field gd-enabled");
    const label = make("span", "field__label", t("guards.enabled"));
    label.id = "gd-enabled-label";
    const button = createSwitch(label.id);
    button.setAttribute("aria-checked", String(this.state.enabled));
    new Switch(button, { onChange: (on) => (this.state.enabled = on) });
    wrap.append(label, button);
    return wrap;
  }

  #redraw() {
    const focusKey = document.activeElement?.textContent;
    this.#draw();
    if (focusKey) [...this.body.querySelectorAll("button")].find((b) => b.textContent === focusKey)?.focus();
    this.#changed();
  }

  #useTemplate(key) {
    this.template = key;
    const tpl = this.store.templates.find((x) => x.key === key);
    if (tpl) {
      const guard = structuredClone(tpl.guard);
      Object.assign(this.state, { ...guard, name: t(`guards.template.${key}`) });
      this.state.trigger = { events: ["enter"], every_seconds: 60, for_seconds: 0, cooldown_seconds: 0, ...guard.trigger };
    }
    this.#redraw();
  }

  /** What the server takes: the trigger without the fields of the other kind. */
  #body() {
    const s = this.state;
    const trigger = s.trigger.type === "event" ? { type: "event", events: s.trigger.events } : { type: "interval", every_seconds: s.trigger.every_seconds, for_seconds: s.trigger.for_seconds ?? 0, cooldown_seconds: s.trigger.cooldown_seconds ?? 0 };
    return { name: s.name.trim(), trigger, when: s.when, consequence: s.consequence, fallback: s.fallback ?? "pause", escalation: s.escalation, enabled: s.enabled };
  }

  #changed() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.#preview(), PREVIEW_MS);
  }

  async #preview() {
    const turn = (this.turn += 1);
    if (!this.previewEl) return;
    if (!rules.isComplete(this.state.when, this.schema) || !rules.countConditions(this.state.when)) {
      this.previewEl.textContent = t("guards.preview_empty");
      return;
    }
    try {
      const result = await send(`${URL}/preview`, "POST", { ...this.#body(), pipeline_id: this.store.pipelineId, scope_type: this.scope.type, scope_id: this.scope.id });
      if (turn !== this.turn) return;
      this.previewEl.textContent = result.running_scopes
        ? tn("guards.preview_fires", result.matching, { running: result.running_scopes })
        : t("guards.preview_none_running");
    } catch {
      if (turn === this.turn) this.previewEl.textContent = "";
    }
  }

  async #save() {
    const body = this.#body();
    if (!body.name) return this.#setError(t("guards.name_needed"));
    if (!rules.isComplete(body.when, this.schema)) return this.#setError(t("guards.condition_incomplete"));
    if (body.trigger.type === "event" && !body.trigger.events.length) return this.#setError(t("guards.event_needed"));
    this.saveButton.disabled = true;
    try {
      if (this.guard) {
        await send(`${URL}/${this.guard.id}`, "PATCH", body);
      } else if (this.template && this.store.templates.find((x) => x.key === this.template)?.has_action) {
        const made = await send(`${URL}/from-template`, "POST", { template: this.template, pipeline_id: this.store.pipelineId, scope_type: this.scope.type, scope_id: this.scope.id, name: body.name });
        await send(`${URL}/${made.id}`, "PATCH", body);
      } else {
        await send(URL, "POST", { ...body, pipeline_id: this.store.pipelineId, scope_type: this.scope.type, scope_id: this.scope.type === "pipeline" ? null : this.scope.id });
      }
      this.modal.close();
      this.hooks.onChanged();
    } catch (error) {
      const fields = Object.values(error.fieldErrors ?? {});
      this.#setError(fields.length ? fields.join("; ") : (error.detail ?? error.message ?? t("guards.could_not_save")));
    } finally {
      this.saveButton.disabled = false;
    }
  }

  /** Delete after a confirmation (the confirmation dialog opens over this window and shows a failure itself). */
  #delete() {
    if (!this.guard) return;
    const guard = this.guard;
    this.hooks.confirm(t("guards.delete_question", { name: guard.name }), async () => {
      await request(`${URL}/${guard.id}`, { method: "DELETE" });
      this.modal.close();
      this.hooks.onChanged();
    });
  }

  #setError(message) {
    this.error.textContent = message;
    this.error.hidden = !message;
  }
}
