/* The renderer of a form manifest (ADR-062): ONE component that draws the form of a configuration window from its YAML
 * description (`GET /api/forms/<name>`): sections as fieldsets in a two-column grid on a wide window and one column on a
 * narrow one, the fields of each section with their label, a tooltip for the help, a widget from the registry
 * (form-widgets.js) and a line for an error, and the fields a section marks `advanced` folded behind "More options".
 * It edits the `values` object it is given (nested keys by dotted path), tells the window what changed and draws again
 * when a change decides what is there (a `visible_when` looks at it, or a field names it in `config.depends_on`),
 * keeping the focus where it was. Which fields are there and where they sit is form-plan.js (unit-tested).
 *
 *   const form = new FormView(host, {manifest, values, context, overrides, normalize, onChange});
 *   form.validate()  // marks what breaks a limit, true when nothing does
 *   form.setErrors({key: "text"})  form.set(key, value)  form.render()
 *
 * The window around the form (title, tabs, Save and Cancel) is not part of it. */
import { infoTip } from "./info-tip.js";
import { t } from "../i18n.js";
import { dependencies, drawn, getPath, isEnabled, planForm, problems, setPath } from "./form-plan.js";
import { widgetFor } from "./form-widgets.js";

let count = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class FormView {
  /**
   * @param {HTMLElement} host where the form is drawn
   * @param {{manifest: object, values: object, context?: object, overrides?: Record<string, object>,
   *   normalize?: (values: object, key: string) => void, onChange?: (values: object, key: string) => void}} config
   *   context: the window's own data for its custom widgets; overrides: what the window decides for a field at run time,
   *   by key (`{options: [...]}` for a field whose manifest says `config.options_from_code`, or a `help`);
   *   normalize: called after a change so the window can keep `values` consistent (give a trigger its defaults when its
   *   kind changes)
   */
  constructor(host, { manifest, values, context = {}, overrides = {}, normalize = null, onChange = () => {} }) {
    this.host = host;
    this.manifest = manifest;
    this.values = values;
    this.context = context;
    this.overrides = overrides;
    this.normalize = normalize;
    this.onChange = onChange;
    this.expanded = new Set();
    this.errors = {};
    this.deps = dependencies(manifest);
    this.render();
  }

  render() {
    const focus = this.#focus();
    const plan = planForm(this.manifest, this.values, { expanded: this.expanded });
    const root = make("div", "fv");
    root.dataset.form = this.manifest.name;
    if (this.manifest.width) root.style.setProperty("--fv-width", `${this.manifest.width}rem`);
    for (const block of plan.blocks) {
      if (block.full) {
        root.append(this.#section(block.full));
        continue;
      }
      const grid = make("div", "fv-grid");
      grid.dataset.columns = String(this.manifest.columns ?? 2);
      for (const lane of block.columns) {
        const column = make("div", "fv-col");
        for (const section of lane) column.append(this.#section(section));
        grid.append(column);
      }
      root.append(grid);
    }
    this.host.replaceChildren(root);
    this.#showErrors();
    this.#restore(focus);
  }

  /** Change a value from the outside (a window's button) as if the user had. */
  set(key, value) {
    this.#change(key, value);
  }

  /** Show messages under fields: `{key: "text"}`; an empty object clears them. */
  setErrors(errors) {
    this.errors = { ...errors };
    this.#showErrors();
  }

  /** Check the limits of the fields that are there (required, min, max), show what breaks them; true when all is fine. */
  validate() {
    const found = problems(this.manifest, this.values);
    const messages = {};
    for (const [key, problem] of Object.entries(found)) {
      messages[key] =
        problem.code === "required" ? t("components.form_view.required") : t(`components.form_view.${problem.code}`, { [problem.code]: problem.limit });
    }
    this.setErrors(messages);
    return !Object.keys(messages).length;
  }

  focus(key) {
    this.host.querySelector(`[data-focus-key="${CSS.escape(key)}"], [data-field-key="${CSS.escape(key)}"]`)?.focus();
  }

  #change(key, value) {
    setPath(this.values, key, value);
    this.normalize?.(this.values, key);
    delete this.errors[key];
    this.onChange(this.values, key);
    if (this.deps.has(key)) this.render();
    else this.#showErrors();
  }

  #section(plan) {
    const box = make("fieldset", "fv-section");
    box.dataset.section = plan.key;
    const legend = make("legend", "fv-section__title", plan.title);
    box.append(legend);
    for (const field of drawn(plan)) {
      const wrap = this.#field(field);
      box.append(wrap);
      // a field whose label is hidden (the title says it) has its help as the (i) after the section's title
      if (wrap._tip) legend.append(wrap._tip);
    }
    if (plan.advanced.length) {
      const open = this.expanded.has(plan.key);
      const toggle = make("button", "chip-button fv-more", open ? t("components.form_view.fewer") : t("components.form_view.more"));
      toggle.type = "button";
      toggle.dataset.focusKey = `advanced:${plan.key}`;
      toggle.dataset.advancedToggle = plan.key;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.addEventListener("click", () => {
        if (open) this.expanded.delete(plan.key);
        else this.expanded.add(plan.key);
        this.render();
      });
      box.append(toggle);
    }
    return box;
  }

  #field(declared) {
    const field = { ...declared, ...(this.overrides[declared.key] ?? {}) };
    const factory = widgetFor(field.widget);
    const wrap = make("div", "field fv-field");
    wrap.dataset.field = field.key;
    if (!factory) {
      wrap.append(make("p", "field__error", `${field.label}: ${t("components.form_view.unknown_widget", { widget: field.widget })}`));
      return wrap;
    }
    count += 1;
    const id = `fv-${count}`;
    const own = getPath(this.values, field.key);
    const ctx = {
      field,
      value: own !== null && typeof own === "object" ? structuredClone(own) : own,
      options: field.options ?? [],
      context: this.context,
      id,
      form: this,
      get: (key) => getPath(this.values, key),
      set: (value, key = field.key) => this.#change(key, value),
    };
    const built = factory(ctx);
    const head = make("div", `field__head${field.hide_label ? " visually-hidden" : ""}`);
    const label = make(built.control ? "label" : "span", `field__label${field.hide_label ? " visually-hidden" : ""}`, field.label);
    if (built.control) label.htmlFor = id;
    else {
      label.id = `${id}-label`;
      built.el.setAttribute("role", built.el.getAttribute("role") ?? "group");
      built.el.setAttribute("aria-labelledby", label.id);
    }
    head.append(label);
    if (field.help) {
      const tip = infoTip(field.help, { label: field.label });
      if (field.hide_label) wrap._tip = tip.button;
      else head.append(tip.button);
      (built.control ?? built.el).setAttribute("aria-describedby", tip.id);
    }
    let reason = null;
    if (!isEnabled(field, this.values)) {
      // it stays drawn so the setting can be found, but cannot be changed now; the reason is under it (enabled_when, disabled_help)
      wrap.classList.add("is-disabled");
      const target = built.control ?? built.el;
      if (built.control) built.control.disabled = true;
      else built.el.inert = true;
      if (field.disabled_help) {
        reason = make("p", "field__hint fv-disabled-reason", field.disabled_help);
        reason.id = `${id}-reason`;
        target.setAttribute("aria-describedby", [target.getAttribute("aria-describedby"), reason.id].filter(Boolean).join(" "));
      }
    }
    const error = make("p", "field__error fv-error");
    error.id = `${id}-error`;
    error.dataset.errorFor = field.key;
    error.setAttribute("role", "alert");
    error.hidden = true;
    wrap.append(head, built.el, ...(reason ? [reason] : []), error);
    return wrap;
  }

  #showErrors() {
    for (const el of this.host.querySelectorAll("[data-error-for]")) {
      const message = this.errors[el.dataset.errorFor] ?? "";
      el.textContent = message;
      el.hidden = !message;
      const control = el.parentElement.querySelector("[data-field-key]");
      if (control) control.setAttribute("aria-invalid", String(Boolean(message)));
    }
  }

  #focus() {
    const el = document.activeElement;
    if (!el || !this.host.contains(el)) return null;
    const key = el.dataset?.focusKey ?? el.dataset?.fieldKey;
    if (!key) return null;
    const text = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
    return { key, start: text ? el.selectionStart : null, end: text ? el.selectionEnd : null };
  }

  #restore(focus) {
    if (!focus) return;
    const el = this.host.querySelector(`[data-focus-key="${CSS.escape(focus.key)}"], [data-field-key="${CSS.escape(focus.key)}"]`);
    if (!el) return;
    el.focus({ preventScroll: true });
    if (focus.start !== null && el.setSelectionRange) {
      try {
        el.setSelectionRange(focus.start, focus.end);
      } catch {
        /* a number field has no selection */
      }
    }
  }
}
