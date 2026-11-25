/* The widgets of the form renderer (components/form-view.js, ADR-062). A form manifest names a widget; this registry
 * holds what draws it. The built-in ones are here; an application or a third party adds its own with
 * `registerWidget(name, factory)` (and `register_widget(name)` on the server so manifests may name it).
 *
 * A factory is called with a context and returns the element of the widget:
 *   ctx.field    the manifest's field (key, label, options, min, max, placeholder, config ...)
 *   ctx.value    the current value (a copy to edit, not the form's own object)
 *   ctx.options  the choices of a select, a choice or chips: the manifest's, or the ones the window gives for this key
 *   ctx.context  what the window handed to the form (its own data: the schema of a rule tree, the actions to pick from)
 *   ctx.get(key) the value of another field; ctx.set(value[, key]) a changed value (of this field, or another one)
 *   ctx.id       a unique id for the control
 * and returns {el, control?}: `control` is the element the label belongs to (an input, a select); without it the
 * widget is a group the label names (role="group", aria-labelledby). */
import { icon } from "./icons.js";
import { createSwitch, Switch } from "./switch.js";

const registry = new Map();

/** Add a widget. A later registration of the same name replaces the earlier one. */
export function registerWidget(name, factory) {
  registry.set(name, factory);
}

export function widgetFor(name) {
  return registry.get(name) ?? null;
}

export function widgetNames() {
  return [...registry.keys()].sort();
}

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

function controlOf(ctx, el) {
  el.id = ctx.id;
  el.dataset.fieldKey = ctx.field.key;
  return { el, control: el };
}

registerWidget("text", (ctx) => {
  const secret = Boolean(ctx.field.config?.secret); // a value that is not shown as it is typed (a token)
  const input = Object.assign(make("input", "field__control"), { type: secret ? "password" : "text", value: ctx.value ?? "" });
  if (secret) Object.assign(input, { autocomplete: "new-password", spellcheck: false });
  if (ctx.field.config?.readonly) input.readOnly = true; // shown as a field, not changed (a window may decide that for a field at run time)
  if (ctx.field.placeholder) input.placeholder = ctx.field.placeholder;
  if (ctx.field.config?.max_length) input.maxLength = ctx.field.config.max_length;
  input.addEventListener("input", () => ctx.set(input.value));
  return controlOf(ctx, input);
});

registerWidget("textarea", (ctx) => {
  const area = Object.assign(make("textarea", "field__control"), { value: ctx.value ?? "", rows: ctx.field.config?.rows ?? 3 });
  if (ctx.field.placeholder) area.placeholder = ctx.field.placeholder;
  area.addEventListener("input", () => ctx.set(area.value));
  return controlOf(ctx, area);
});

/** Short labels: typed as one line separated by commas, kept as a list (a definition's tags); empty ones and repeats are dropped. */
registerWidget("tags", (ctx) => {
  const input = Object.assign(make("input", "field__control"), { type: "text", value: Array.isArray(ctx.value) ? ctx.value.join(", ") : "" });
  if (ctx.field.placeholder) input.placeholder = ctx.field.placeholder;
  input.addEventListener("input", () => ctx.set(input.value.split(",").map((x) => x.trim()).filter(Boolean)));
  return controlOf(ctx, input);
});

registerWidget("number", (ctx) => {
  const input = Object.assign(make("input", "field__control fv-number"), { type: "number", step: ctx.field.step ?? 1 });
  if (ctx.field.min !== undefined) input.min = String(ctx.field.min);
  if (ctx.field.max !== undefined) input.max = String(ctx.field.max);
  input.value = ctx.value === undefined || ctx.value === null ? "" : String(ctx.value);
  input.addEventListener("input", () => ctx.set(input.value === "" ? null : Math.round(Number(input.value) * 1e6) / 1e6));
  return controlOf(ctx, input);
});

registerWidget("select", (ctx) => {
  const select = make("select", "field__control");
  for (const option of ctx.options) {
    const el = new Option(option.label, option.value);
    el.disabled = Boolean(option.disabled);
    select.append(el);
  }
  select.value = ctx.value ?? ctx.options[0]?.value ?? "";
  select.addEventListener("change", () => ctx.set(select.value));
  return controlOf(ctx, select);
});

/** One of a few, as chips (the trigger: on an event / every few seconds). */
registerWidget("choice", (ctx) => {
  const group = make("div", "fv-chips");
  for (const option of ctx.options) {
    const chip = make("button", "chip-button", option.label);
    chip.type = "button";
    chip.dataset.fieldKey = ctx.field.key;
    chip.dataset.focusKey = `${ctx.field.key}:${option.value}`;
    chip.dataset.choice = option.value;
    chip.setAttribute("aria-pressed", String(ctx.value === option.value));
    chip.addEventListener("click", () => {
      // the marking follows the click itself: a form draws again only when a change decides what is there (visible_when), and
      // a choice nothing else depends on would keep showing the old one
      for (const other of group.querySelectorAll("[data-choice]")) other.setAttribute("aria-pressed", String(other === chip));
      ctx.set(option.value);
    });
    group.append(chip);
  }
  return { el: group, control: null };
});

/** Several of a few, as ticked chips (the events of a guard). The rule builder's chip is the look. */
registerWidget("chips", (ctx) => {
  const chosen = new Set(ctx.value ?? []);
  const group = make("div", "rb-choices");
  for (const option of ctx.options) {
    const wrap = make("label", "rb-chip");
    const box = Object.assign(make("input", "rb-chip__input"), { type: "checkbox", checked: chosen.has(option.value) });
    box.dataset.choice = option.value;
    box.dataset.fieldKey = ctx.field.key;
    box.dataset.focusKey = `${ctx.field.key}:${option.value}`;
    box.addEventListener("change", () => {
      if (box.checked) chosen.add(option.value);
      else chosen.delete(option.value);
      ctx.set(ctx.options.map((o) => o.value).filter((v) => chosen.has(v)));
    });
    const tick = make("span", "rb-chip__tick");
    tick.append(icon("check"));
    wrap.append(box, tick, make("span", "", option.label));
    group.append(wrap);
  }
  return { el: group, control: null };
});

registerWidget("switch", (ctx) => {
  const button = createSwitch();
  button.id = ctx.id;
  button.dataset.fieldKey = ctx.field.key;
  const toggle = new Switch(button, { onChange: (on) => ctx.set(on) });
  toggle.on = Boolean(ctx.value);
  return { el: button, control: button };
});

registerWidget("readonly", (ctx) => ({ el: make("p", "fv-readonly", ctx.value === undefined || ctx.value === null ? "" : String(ctx.value)), control: null }));
