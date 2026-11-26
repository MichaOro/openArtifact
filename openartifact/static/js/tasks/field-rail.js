/* The artifact fields in the rail of the artifact dialog (ADR-044). "Fields" is an entry with sub-entries like the
 * main navigation's (components/nav-group.js): open, the fields hang below it, indented; with the rail collapsed a
 * click opens them beside the icon, like the Lane entry opens its list. Each field shows its name, the reference
 * pipelines read it by (${card.NAME}) and below them its control (text, number, a yes/no switch, a choice list, the
 * boxes of a multi select). A change is saved at once; a refusal is shown under the field. While the artifact is
 * processed the fields are locked. */
import { effectiveValue, parseProblems, valueOf } from "../artifact-fields/model.js";
import { NavGroup } from "../components/nav-group.js";
import { t } from "../i18n.js";

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export class FieldRail {
  /**
   * @param {object} options
   * @param {HTMLElement} options.rail the rail ([data-card-nav])
   * @param {import("../components/collapsible-nav.js").CollapsibleNav} options.nav the rail's open and closed state
   * @param {(id: string, values: object) => Promise<object>} options.save sends {name: value} of one artifact
   * @param {(task: object) => void} options.onSaved the artifact as the server answered
   * @param {() => void} [options.onLayout] the rail got taller or shorter: the dialog sizes itself again
   */
  constructor({ rail, nav, save, onSaved, onLayout = () => {} }) {
    Object.assign(this, { nav, save, onSaved });
    this.root = rail.querySelector("[data-field-rail]");
    this.group = new NavGroup(this.root.querySelector("[data-nav-group=fields]"), nav, { onLayout });
    this.list = this.group.list;
    this.fields = [];
    this.task = null;
    this.locked = false;
  }

  get open() {
    return this.group.isOpen;
  }

  /** The fields every artifact has (they follow ``artifact_fields.changed``). */
  setFields(fields) {
    this.fields = fields;
    this.#render();
  }

  /** Show the fields of an artifact (null: the dialog shows none, e.g. while creating one). */
  show(task) {
    const sameTask = task && this.task?.id === task.id;
    const same = sameTask && JSON.stringify(task.fields) === JSON.stringify(this.task.fields);
    const typing = sameTask && this.list.contains(document.activeElement);
    this.task = task;
    // an update (often of our own save, arriving later) must not take away a field that is being typed in
    if (!same && !typing) this.#render();
  }

  /** While the artifact is processed its fields cannot change. */
  setLocked(locked) {
    this.locked = locked;
    for (const control of this.list.querySelectorAll("input, select, button")) control.disabled = locked;
  }

  #render() {
    this.root.hidden = !this.task || this.fields.length === 0;
    if (this.root.hidden) {
      this.group.close({ restoreFocus: false });
      this.group.fill();
      return;
    }
    this.group.fill(...this.fields.map((field) => this.#item(field)));
    this.setLocked(this.locked);
  }

  #item(field) {
    const item = element("li", "card-field");
    item.dataset.field = field.name;
    const id = `card-field-${field.name}`;
    const label = element("label", "card-field__label", field.label);
    label.htmlFor = id;
    const reference = element("code", "card-field__reference", `\${card.${field.name}}`);
    reference.title = t("tasks.field_rail.pipelines_read_field_as_card", { name: field.name });
    const error = element("p", "card-field__error");
    error.id = `${id}-error`;
    error.setAttribute("role", "alert");
    error.hidden = true;
    const value = effectiveValue(field, this.task.fields);
    const control = this.#control(field, value, (raw) => this.#change(field, raw, error));
    control.id = id;
    control.setAttribute("aria-describedby", error.id);
    item.append(label, reference, control, error);
    return item;
  }

  #control(field, value, onChange) {
    if (field.kind === "boolean") {
      const button = element("button", "card-field__switch");
      button.type = "button";
      button.setAttribute("role", "switch");
      const on = value === true;
      button.setAttribute("aria-checked", String(on));
      button.append(element("span", "card-field__switch-track"), element("span", "card-field__switch-text", on ? t("tasks.field_rail.yes") : "No"));
      button.addEventListener("click", () => {
        const next = button.getAttribute("aria-checked") !== "true";
        button.setAttribute("aria-checked", String(next)); // shown at once; a refusal draws the stored value again
        button.querySelector(".card-field__switch-text").textContent = next ? t("tasks.field_rail.yes") : "No";
        onChange(next);
      });
      return button;
    }
    if (field.kind === "choice" && field.multiple) {
      // a multi select: one box per allowed value (ADR-050)
      const group = element("div", "card-field__multi");
      group.setAttribute("role", "group");
      const chosen = new Set(Array.isArray(value) ? value : []);
      for (const option of field.options) {
        const wrap = element("label", "card-field__choice");
        const box = element("input", "check");
        box.type = "checkbox";
        box.value = option;
        box.checked = chosen.has(option);
        box.addEventListener("change", () => onChange([...group.querySelectorAll("input:checked")].map((b) => b.value)));
        wrap.append(box, document.createTextNode(` ${option}`));
        group.append(wrap);
      }
      return group;
    }
    if (field.kind === "choice") {
      const select = element("select", "field__control card-field__control");
      select.append(new Option("–", ""), ...field.options.map((option) => new Option(option, option)));
      select.value = value ?? "";
      select.addEventListener("change", () => onChange(select.value));
      return select;
    }
    const input = element("input", "field__control card-field__control");
    input.type = field.kind === "number" ? "number" : "text";
    if (field.kind === "number") input.step = field.integer_only ? "1" : "any";
    if (field.kind === "text") input.maxLength = field.max_length ?? 200;
    input.value = value ?? "";
    input.placeholder = field.kind === "number" ? t("tasks.field_rail.enter_number") : t("tasks.field_rail.enter_text");
    input.addEventListener("change", () => onChange(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") input.blur();
    });
    return input;
  }

  async #change(field, raw, error) {
    if (!this.task || this.locked) return;
    error.hidden = true;
    const id = this.task.id;
    try {
      const saved = await this.save(id, { [field.name]: valueOf(field, raw) });
      // the controls already show what was saved: no redraw, so a field being typed in keeps its text
      if (this.task?.id === id) this.task = saved;
      this.onSaved(saved);
    } catch (problem) {
      const { byField, other } = parseProblems(problem.detail);
      const message = byField.get(field.name) || other.join(" ") || t("tasks.field_rail.could_not_save_field");
      if (field.kind === "boolean" || field.multiple) {
        this.#render(); // back to what is stored
        error = this.list.querySelector(`#card-field-${field.name}-error`) ?? error;
      }
      error.textContent = message;
      error.hidden = false;
    }
  }
}
