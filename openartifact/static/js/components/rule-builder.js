/* A rule builder: conditions in groups that say "all" (AND) or "any" (OR) of their items hold, groups inside groups,
 * each condition a field, an operator and a value. What the fields are is the schema's (see rule-model.js); the
 * builder knows nothing about executions or lanes, so any list that filters or deletes by rules can use it.
 *
 *   const builder = new RuleBuilder(element, schema, { onChange: (tree) => ... });
 *   builder.load(tree);  builder.read();
 */
import { icon } from "./icons.js";
import * as model from "./rule-model.js";

let count = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

function select(label, options, value, onChange) {
  const el = make("select", "field__control rb-select");
  el.setAttribute("aria-label", label);
  for (const [optionValue, text] of options) el.append(new Option(text, optionValue));
  el.value = value;
  el.addEventListener("change", () => onChange(el.value));
  return el;
}

export class RuleBuilder {
  /**
   * @param {HTMLElement} root
   * @param {{fields: object[]}} schema
   * @param {{onChange?: (tree: object) => void, maxDepth?: number, maxConditions?: number}} [options]
   */
  constructor(root, schema, { onChange = () => {}, maxDepth = 4, maxConditions = 50 } = {}) {
    this.root = root;
    this.schema = schema;
    this.onChange = onChange;
    this.maxDepth = maxDepth;
    this.maxConditions = maxConditions;
    this.id = `rb-${(count += 1)}`;
    this.tree = model.emptyGroup();
    root.classList.add("rb");
  }

  load(tree) {
    this.tree = tree ?? model.emptyGroup();
    this.#draw();
  }

  read() {
    return this.tree;
  }

  #change(tree, focus = null) {
    this.tree = tree;
    this.#draw(focus);
    this.onChange(this.tree);
  }

  /** Draw again; the control that was changed (`focus`, a data-key) gets the focus back. */
  #draw(focus = null) {
    const active = document.activeElement;
    const key = focus ?? (this.root.contains(active) ? active.dataset?.rbKey : null);
    this.root.replaceChildren(this.#group(this.tree, []));
    if (key) this.root.querySelector(`[data-rb-key="${key}"]`)?.focus();
  }

  #group(group, path) {
    const card = make("div", "rb-group");
    card.dataset.mode = group.mode;
    card.setAttribute("role", "group");
    const head = make("div", "rb-group__head");
    head.append(
      select("All or any of the conditions", [["all", "All of these (AND)"], ["any", "Any of these (OR)"]], group.mode, (mode) => this.#change(model.setMode(this.tree, path, mode), `mode-${path.join("-")}`)),
    );
    head.lastChild.dataset.rbKey = `mode-${path.join("-")}`;
    if (path.length) {
      const bin = make("button", "icon-button icon-button--sm is-danger");
      bin.type = "button";
      bin.title = "Remove this group";
      bin.setAttribute("aria-label", "Remove this group");
      bin.append(icon("trash"));
      bin.addEventListener("click", () => this.#change(model.removeItem(this.tree, path)));
      head.append(bin);
    }
    const items = make("div", "rb-items");
    group.items.forEach((item, i) => items.append(item.type === "group" ? this.#group(item, [...path, i]) : this.#row(item, [...path, i])));
    const foot = make("div", "rb-group__foot");
    const addCondition = this.#button("Add condition", "plus", () => {
      const next = model.addItem(this.tree, path, model.newCondition(this.schema));
      this.#change(next, `field-${[...path, group.items.length].join("-")}`);
    });
    addCondition.disabled = model.countConditions(this.tree) >= this.maxConditions;
    foot.append(addCondition);
    if (model.canNest(this.tree, path, this.maxDepth)) foot.append(this.#button("Add group", "layers", () => this.#change(model.addItem(this.tree, path, model.emptyGroup("any")))));
    card.append(head, items, foot);
    if (!group.items.length && !path.length) items.append(make("p", "rb-empty", "No conditions yet."));
    return card;
  }

  #button(text, glyph, onClick) {
    const button = make("button", "button button--ghost button--sm rb-add");
    button.type = "button";
    button.append(icon(glyph), document.createTextNode(text));
    button.addEventListener("click", onClick);
    return button;
  }

  #row(condition, path) {
    const where = path.join("-");
    const field = this.schema.fields.find((f) => f.key === condition.field) ?? this.schema.fields[0];
    const row = make("div", "rb-row");
    const fieldSelect = select("Field", this.schema.fields.map((f) => [f.key, f.label]), condition.field, (key) => this.#change(model.replaceItem(this.tree, path, model.withField(this.schema, condition, key)), `field-${where}`));
    fieldSelect.dataset.rbKey = `field-${where}`;
    const operator = select("Operator", field.operators.map((o) => [o.key, o.label]), condition.op, (op) => this.#change(model.replaceItem(this.tree, path, model.withOperator(condition, op)), `op-${where}`));
    operator.dataset.rbKey = `op-${where}`;
    operator.disabled = field.operators.length === 1;
    const bin = make("button", "icon-button icon-button--sm is-danger");
    bin.type = "button";
    bin.title = "Remove this condition";
    bin.setAttribute("aria-label", "Remove this condition");
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.#change(model.removeItem(this.tree, path)));
    row.append(fieldSelect, operator, this.#value(field, condition, path), bin);
    return row;
  }

  #value(field, condition, path) {
    // typing or ticking changes the tree without drawing again, so the control keeps its focus and caret
    const set = (value) => {
      this.tree = model.replaceItem(this.tree, path, model.withValue(condition, value));
      condition = model.itemAt(this.tree, path);
      this.onChange(this.tree);
    };
    if (field.kind === "choice") {
      const wrap = make("div", "rb-choices");
      wrap.setAttribute("role", "group");
      wrap.setAttribute("aria-label", field.label);
      for (const option of field.options) {
        const label = make("label", "rb-chip");
        const box = Object.assign(make("input", "rb-chip__input"), { type: "checkbox", checked: condition.value.includes(option.value) });
        box.addEventListener("change", () => {
          const chosen = new Set(condition.value);
          if (box.checked) chosen.add(option.value);
          else chosen.delete(option.value);
          set(field.options.map((o) => o.value).filter((v) => chosen.has(v)));
        });
        const tick = make("span", "rb-chip__tick");
        tick.append(icon("check"));
        label.append(box, tick, make("span", "", option.label));
        wrap.append(label);
      }
      return wrap;
    }
    if (field.kind === "duration") {
      const wrap = make("div", "rb-duration");
      const { amount, unit } = model.splitDuration(condition.value);
      const number = Object.assign(make("input", "field__control rb-number"), { type: "number", min: 1, step: 1, value: String(amount) });
      number.setAttribute("aria-label", "Amount");
      const units = select("Unit", model.durationUnits().map((u) => [u, u]), unit, () => update());
      const update = () => set(model.joinDuration(Number(number.value) || 0, units.value));
      number.addEventListener("input", update);
      wrap.append(number, units);
      return wrap;
    }
    if (field.kind === "count") {
      const number = Object.assign(make("input", "field__control rb-number"), { type: "number", min: 1, step: 1, value: String(condition.value) });
      number.setAttribute("aria-label", field.label);
      number.addEventListener("input", () => set(Math.round(Number(number.value)) || 0));
      return number;
    }
    const input = Object.assign(make("input", "field__control rb-text"), { type: "text", value: condition.value, maxLength: 120, autocomplete: "off", spellcheck: false });
    input.setAttribute("aria-label", field.label);
    input.placeholder = field.placeholder ?? "";
    input.addEventListener("input", () => set(input.value));
    return input;
  }
}
