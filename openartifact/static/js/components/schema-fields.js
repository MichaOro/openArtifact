/* The editor of a flat list of fields (ADR-080): a schema as a list of rows, reordered by a handle, each with a name, a type, "required",
 * a description (what the model sees) and, for a choice, its values. It knows nothing of the node that holds it: it takes a list and tells
 * its owner when the list changes, so whatever lets a model answer in a shape (the Hand Over Tool today) mounts the same component.
 *
 *   const fields = new SchemaFields({ fields, types, limits, max, label, onInput, onSettle });
 *   parent.append(fields.element);    fields.list    fields.problem()
 *
 * `onInput()` is called while a text is typed (the list is already changed, nothing is decided); `onSettle()` when the owner may save: a
 * choice, an add, a removal, a move, and a text field that is left or confirmed with Enter. The rules of the list are
 * schema-fields-model.js; the server checks the same.
 *
 * The wide variant (the Trigger, Output and Complete windows, ADR-083 addendum 2) is compact: one row per field with a handle, the name, the
 * type, the "required" box and a three-dot menu. A description, and for an input a default value, are not always there: the menu adds them
 * to the row (and takes them away again), and a field that has them shows them. Deleting a field is in that menu too. */
import { ActionMenu } from "./action-menu.js";
import { Checkbox } from "./checkbox.js";
import { icon } from "./icons.js";
import { Sortable } from "./sortable.js";
import { t } from "../i18n.js";
import { addField, listProblem, menuPlan, moveField, parseChoices, removeField, rowPlan, setProp, shownOf, LIMITS, MAX_FIELDS, TYPES } from "./schema-fields-model.js";

function element(tag, className, text = null) {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

let rowMenu = null; // one menu for every list of the page (made when it is first needed: it lives in the body)

export class SchemaFields {
  /**
   * @param {{fields?: object[], types?: string[], limits?: object, max?: number, label?: string, extra?: "default"|"value"|null,
   *   showRequired?: boolean, wide?: boolean, decorate?: (input: HTMLInputElement, kind: string) => void, onInput?: () => void, onSettle?: () => void}} options
   *   `label`: the accessible name of the list; `extra`: one more text each field carries, the default of an input or the value of an
   *   output (ADR-083); `showRequired`: whether a field has the "required" box (an output has not); `decorate`: called with each extra
   *   text field (the editor adds the reference suggestions to the value of an output); `wide`: the compact one-row-per-field layout with
   *   the column heads above and the row menu (the Trigger, Output and Complete windows; rowPlan in the model), the text for a model
   *   dropped, and the stacked layout when the window is narrow; without it the compact layout of a narrow node window (the Hand Over Tool:
   *   its description is what the model reads, so it stays on its row, and its bin stays at the row)
   */
  constructor({ fields = [], types = TYPES, limits = LIMITS, max = MAX_FIELDS, label = "", extra = null, showRequired = true, wide = false, decorate = null, onInput = () => {}, onSettle = () => {} } = {}) {
    this.extra = extra;
    this.showRequired = showRequired;
    this.wide = wide;
    this.decorate = decorate;
    this.types = types;
    this.limits = limits;
    this.max = max;
    this.onInput = onInput;
    this.onSettle = onSettle;
    this.list = fields.map((field) => ({ ...field }));
    this.shown = this.list.map((field) => shownOf(field, extra)); // what each row shows besides the compact row: kept apart from the data
    this.element = element("div", wide ? "sf sf--wide" : "sf");
    if (wide) {
      const plan = rowPlan({ showRequired, extra });
      this.element.style.setProperty("--sf-cols", plan.template);
      this.element.style.setProperty("--sf-row", plan.row);
      this.element.style.setProperty("--sf-row-d", plan.description);
      this.element.style.setProperty("--sf-row-e", plan.extra);
      this.element.style.setProperty("--sf-row-c", plan.choices);
      this.head = element("div", "sf__head");
      this.head.setAttribute("aria-hidden", "true"); // the inputs name themselves; the heads only tell a seeing user what each column is
      for (const column of plan.columns) {
        if (column === "grip" || column === "more") continue;
        const label = element("span", `sf__h sf__h--${column}`, t(`components.schema_fields.head.${column === "extra" ? extra : column}`));
        label.style.gridArea = column;
        this.head.append(label);
      }
    }
    this.rows = element("ul", "sf__list");
    if (label) this.rows.setAttribute("aria-label", label);
    this.add = element("button", "button button--ghost button--sm sf__add");
    this.add.type = "button";
    this.add.append(icon("plus"), element("span", "", t("components.schema_fields.add")));
    this.add.addEventListener("click", () => this.addRow());
    this.live = element("p", "visually-hidden");
    this.live.setAttribute("aria-live", "polite");
    if (this.head) this.element.append(this.head);
    this.element.append(this.rows, this.add, this.live);
    new Sortable(this.rows, { handle: ".sf__grip", onMove: (from, to, by) => this.moveRow(from, to, by) });
    this.draw();
  }

  /** The list as it stands. */
  value() {
    return this.list.map((field) => ({ ...field }));
  }

  /** What is wrong with the list in words, or null (the same rules as the server's). */
  problem() {
    const found = listProblem(this.list, this.limits, this.max);
    return found ? t(`components.schema_fields.problem.${found.code}`, found.params) : null;
  }

  draw() {
    this.rows.replaceChildren(...this.list.map((field, index) => this.row(field, index)));
    this.add.disabled = this.list.length >= this.max;
  }

  row(field, index) {
    const item = element("li", "sf__row");
    const name = field.name || String(index + 1);
    const grip = element("button", "icon-button icon-button--sm sf__grip");
    grip.type = "button";
    grip.setAttribute("aria-label", t("components.schema_fields.drag", { name }));
    grip.title = t("components.schema_fields.drag_help");
    grip.append(icon("grip"));
    const nameInput = this.typed("input", "sf__name", field.name, (value) => this.change(index, "name", value));
    nameInput.maxLength = this.limits.name_chars;
    nameInput.spellcheck = false;
    nameInput.setAttribute("aria-label", t("components.schema_fields.name", { n: index + 1 }));
    nameInput.placeholder = t("components.schema_fields.name_placeholder");
    const type = element("select", "field__control sf__type");
    for (const value of this.types) type.append(new Option(t(`components.schema_fields.type.${value}`), value));
    type.value = field.type;
    type.setAttribute("aria-label", t("components.schema_fields.type_label", { name }));
    type.addEventListener("change", () => {
      this.list = setProp(this.list, index, "type", type.value);
      this.draw();
      this.settle();
    });
    const required = new Checkbox({
      label: t("components.schema_fields.required"),
      checked: Boolean(field.required),
      labelHidden: false, // in the one-row layout the column head says it (the stylesheet hides the text there), stacked the text stays
      className: "sf__required",
      inputClass: "sf__check",
      onChange: (on) => {
        this.list = setProp(this.list, index, "required", on);
        this.settle();
      },
    }).element;
    required.hidden = !this.showRequired;
    if (this.wide) return this.wideRow(item, { field, index, name, grip, nameInput, type, required });
    const bin = element("button", "icon-button icon-button--sm sf__bin");
    bin.type = "button";
    bin.title = t("components.schema_fields.remove", { name });
    bin.setAttribute("aria-label", bin.title);
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.removeRow(index));
    const description = this.describer(field, index, name);
    description.placeholder = t("components.schema_fields.description_placeholder"); // what a model puts there: said where a model answers
    item.append(grip, nameInput, bin, type, required, description);
    if (this.extra) item.append(this.extraInput(field, index, name));
    this.appendChoices(item, field, index, name);
    return item;
  }

  /** The row of the wide variant: the compact row, the menu, then what the row shows besides (a description, a default, a choice's values). */
  wideRow(item, { field, index, name, grip, nameInput, type, required }) {
    const shown = this.shown[index] ?? shownOf(field, this.extra);
    const more = element("button", "icon-button icon-button--sm sf__more");
    more.type = "button";
    more.title = t("components.schema_fields.more", { name });
    more.setAttribute("aria-label", more.title);
    more.setAttribute("aria-haspopup", "menu");
    more.append(icon("more"));
    more.addEventListener("click", () => this.openMenu(more, index, name));
    item.append(grip, nameInput, type, required); // the order of the keyboard is the order of the columns, the menu last
    if (this.extra === "value") item.append(this.extraInput(field, index, name)); // an output always has its value: a column of its own
    item.append(more);
    if (shown.description) item.append(this.line(this.describer(field, index, name)));
    if (this.extra === "default" && shown.extra) item.append(this.line(this.extraInput(field, index, name)));
    this.appendChoices(item, field, index, name);
    return item;
  }

  /** What a row shows below the compact row sits on a line of its own, set off a little from the row above. */
  line(control) {
    control.classList.add("sf__line");
    return control;
  }

  describer(field, index, name) {
    const description = this.typed("input", "sf__description", field.description ?? "", (value) => this.change(index, "description", value));
    description.maxLength = this.limits.description_chars;
    description.setAttribute("aria-label", t("components.schema_fields.description_label", { name }));
    if (this.wide) description.placeholder = t("components.schema_fields.description_wide_placeholder");
    return description;
  }

  extraInput(field, index, name) {
    const extra = this.typed("input", "sf__extra", field[this.extra] ?? "", (value) => this.change(index, this.extra, value));
    extra.maxLength = 2000;
    extra.spellcheck = false;
    if (!this.wide) extra.placeholder = t(`components.schema_fields.${this.extra}_placeholder`);
    extra.setAttribute("aria-label", t(`components.schema_fields.${this.extra}_label`, { name }));
    this.decorate?.(extra, this.extra);
    return extra;
  }

  appendChoices(item, field, index, name) {
    if (field.type !== "choice") return;
    const values = this.typed("input", "sf__choices", (field.choices ?? []).join(", "), (value) => this.change(index, "choices", parseChoices(value)));
    values.placeholder = t("components.schema_fields.choices_placeholder");
    values.setAttribute("aria-label", t("components.schema_fields.choices_label", { name }));
    values.title = t("components.schema_fields.choices_help", { min: this.limits.choices[0], max: this.limits.choices[1] });
    item.append(this.wide ? this.line(values) : values);
  }

  /** The three-dot menu of a row: add or remove its description (and its default), delete the field. */
  openMenu(trigger, index, name) {
    rowMenu ??= new ActionMenu();
    const shown = this.shown[index];
    const items = menuPlan({ extra: this.extra, shown }).map((entry) => {
      if (entry.key === "delete") return { label: t("components.schema_fields.menu.delete"), icon: "trash", danger: true, onSelect: () => this.removeRow(index) };
      const which = entry.key === "description" ? "description" : "default";
      return {
        label: t(`components.schema_fields.menu.${entry.on ? "remove" : "add"}_${which}`),
        icon: entry.on ? "x" : "plus",
        onSelect: () => (entry.on ? this.dropExtra(index, entry.key) : this.showExtra(index, entry.key)),
      };
    });
    rowMenu.toggle(trigger, items, t("components.schema_fields.more", { name }));
  }

  /** Show the description (or the default) on the row and put the caret in it. */
  showExtra(index, key) {
    this.shown[index] = { ...this.shown[index], [key]: true };
    this.draw();
    this.rows.children[index]?.querySelector(key === "description" ? ".sf__description" : ".sf__extra")?.focus();
  }

  /** Take it away again: the text goes with it. */
  dropExtra(index, key) {
    this.shown[index] = { ...this.shown[index], [key]: false };
    this.list = setProp(this.list, index, key === "description" ? "description" : this.extra, "");
    this.draw();
    this.settle();
    this.rows.children[index]?.querySelector(".sf__more")?.focus();
  }

  /** A text field: the list follows every keystroke, the owner is asked to save when the field is left or confirmed. */
  typed(tag, className, value, apply) {
    const input = element(tag, `field__control ${className}`);
    input.type = "text";
    input.value = value;
    input.addEventListener("input", () => {
      apply(input.value);
      this.onInput();
    });
    input.addEventListener("change", () => this.settle());
    return input;
  }

  change(index, key, value) {
    this.list = setProp(this.list, index, key, value);
  }

  settle() {
    this.onSettle();
  }

  addRow() {
    if (this.list.length >= this.max) return;
    this.list = addField(this.list);
    this.shown.push(shownOf(this.list[this.list.length - 1], this.extra));
    this.draw();
    this.live.textContent = t("components.schema_fields.added", { n: this.list.length });
    this.settle();
    const last = this.rows.lastElementChild?.querySelector(".sf__name");
    last?.focus();
    last?.select();
  }

  removeRow(index) {
    const name = this.list[index].name;
    this.list = removeField(this.list, index);
    this.shown.splice(index, 1);
    this.draw();
    this.live.textContent = t("components.schema_fields.removed", { name });
    this.settle();
    (this.rows.children[Math.min(index, this.list.length - 1)]?.querySelector(".sf__name") ?? this.add).focus();
  }

  /** A drag has moved the row in the document already, a key asks for the move; both change the list, which is drawn anew. */
  moveRow(from, to, by) {
    this.list = moveField(this.list, from, to);
    const [moved] = this.shown.splice(from, 1);
    this.shown.splice(to, 0, moved);
    this.draw();
    if (by === "key") this.rows.children[to]?.querySelector(".sf__grip")?.focus();
    this.live.textContent = t("components.schema_fields.moved", { name: this.list[to].name, n: to + 1, total: this.list.length });
    this.settle();
  }
}
