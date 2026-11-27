/* The editor of a flat list of fields (ADR-080): a schema as a list of rows, reordered by a handle, each with a name, a type, "required",
 * a description (what the model sees) and, for a choice, its values. It knows nothing of the node that holds it: it takes a list and tells
 * its owner when the list changes, so whatever lets a model answer in a shape (the Hand Over Tool today) mounts the same component.
 *
 *   const fields = new SchemaFields({ fields, types, limits, max, label, onInput, onSettle });
 *   parent.append(fields.element);    fields.list    fields.problem()
 *
 * `onInput()` is called while a text is typed (the list is already changed, nothing is decided); `onSettle()` when the owner may save: a
 * choice, an add, a removal, a move, and a text field that is left or confirmed with Enter. The rules of the list are
 * schema-fields-model.js; the server checks the same. */
import { icon } from "./icons.js";
import { Sortable } from "./sortable.js";
import { t } from "../i18n.js";
import { addField, listProblem, moveField, parseChoices, removeField, setProp, LIMITS, MAX_FIELDS, TYPES } from "./schema-fields-model.js";

function element(tag, className, text = null) {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class SchemaFields {
  /**
   * @param {{fields?: object[], types?: string[], limits?: object, max?: number, label?: string, onInput?: () => void, onSettle?: () => void}} options
   *   `label`: the accessible name of the list
   */
  constructor({ fields = [], types = TYPES, limits = LIMITS, max = MAX_FIELDS, label = "", onInput = () => {}, onSettle = () => {} } = {}) {
    this.types = types;
    this.limits = limits;
    this.max = max;
    this.onInput = onInput;
    this.onSettle = onSettle;
    this.list = fields.map((field) => ({ ...field }));
    this.element = element("div", "sf");
    this.rows = element("ul", "sf__list");
    if (label) this.rows.setAttribute("aria-label", label);
    this.add = element("button", "button button--ghost button--sm sf__add");
    this.add.type = "button";
    this.add.append(icon("plus"), element("span", "", t("components.schema_fields.add")));
    this.add.addEventListener("click", () => this.addRow());
    this.live = element("p", "visually-hidden");
    this.live.setAttribute("aria-live", "polite");
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
    const required = element("label", "sf__required");
    const box = element("input", "sf__check");
    box.type = "checkbox";
    box.checked = Boolean(field.required);
    box.addEventListener("change", () => {
      this.list = setProp(this.list, index, "required", box.checked);
      this.settle();
    });
    required.append(box, element("span", "", t("components.schema_fields.required")));
    const bin = element("button", "icon-button icon-button--sm sf__bin");
    bin.type = "button";
    bin.title = t("components.schema_fields.remove", { name });
    bin.setAttribute("aria-label", bin.title);
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.removeRow(index));
    const description = this.typed("input", "sf__description", field.description ?? "", (value) => this.change(index, "description", value));
    description.maxLength = this.limits.description_chars;
    description.placeholder = t("components.schema_fields.description_placeholder");
    description.setAttribute("aria-label", t("components.schema_fields.description_label", { name }));
    item.append(grip, nameInput, bin, type, required, description);
    if (field.type === "choice") {
      const values = this.typed("input", "sf__choices", (field.choices ?? []).join(", "), (value) => this.change(index, "choices", parseChoices(value)));
      values.placeholder = t("components.schema_fields.choices_placeholder");
      values.setAttribute("aria-label", t("components.schema_fields.choices_label", { name }));
      values.title = t("components.schema_fields.choices_help", { min: this.limits.choices[0], max: this.limits.choices[1] });
      item.append(values);
    }
    return item;
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
    this.draw();
    this.live.textContent = t("components.schema_fields.removed", { name });
    this.settle();
    (this.rows.children[Math.min(index, this.list.length - 1)]?.querySelector(".sf__name") ?? this.add).focus();
  }

  /** A drag has moved the row in the document already, a key asks for the move; both change the list, which is drawn anew. */
  moveRow(from, to, by) {
    this.list = moveField(this.list, from, to);
    this.draw();
    if (by === "key") this.rows.children[to]?.querySelector(".sf__grip")?.focus();
    this.live.textContent = t("components.schema_fields.moved", { name: this.list[to].name, n: to + 1, total: this.list.length });
    this.settle();
  }
}
