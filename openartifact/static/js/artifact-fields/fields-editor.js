/* The editor of the artifact fields (ADR-044, ADR-050), after the field settings of GitHub Projects: the fields
 * as a list on the left (a grip to reorder them, a click to choose one, "Add field"), the chosen field's settings
 * on the right (name, type, what the type needs, the options of a select with their own grip, inline rename and
 * menu, the default). Nothing is saved before "Save": the whole list goes with one PUT, the options that were
 * renamed with it, so the artifacts keep their values. Unsaved changes are named in the footer; closing or
 * cancelling with them asks first. The server's refusals (`Field NAME: ...`) are shown at the field. */
import { ActionDialog } from "../components/action-dialog.js";
import { ActionMenu } from "../components/action-menu.js";
import { icon } from "../components/icons.js";
import { InlineName } from "../components/inline-name.js";
import { Sortable } from "../components/sortable.js";
import { KINDS, blankField, editable, isSelect, nameFromLabel, newOption, optionProblem, parseProblems, removedWithValues, toWrite, typeText } from "./model.js";
import { t, tn } from "../i18n.js";

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function grip(label) {
  const button = element("button", "icon-button icon-button--sm af-grip");
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.title = t("artifact_fields.fields_editor.label_drag_arrowup_arrowdown", { label });
  button.append(icon("grip"));
  return button;
}

export class FieldsEditor extends ActionDialog {
  /**
   * @param {import("../components/modal.js").Modal} modal
   * @param {(fields: object[]) => Promise<object>} save sends the whole list
   * @param {(saved: object) => void} onSaved called with the server's answer
   */
  constructor(modal, save, onSaved) {
    super(modal, t("artifact_fields.fields_editor.could_not_save_fields_please"));
    this.save = save;
    this.onSaved = onSaved;
    this.before = [];
    this.fields = [];
    this.selected = null;
    this.snapshot = "";
    this.problems = new Map();
    this.menu = new ActionMenu();
    const root = this.root;
    this.list = root.querySelector("[data-field-list]");
    this.detail = root.querySelector("[data-field-detail]");
    this.lead = root.querySelector("[data-lead]");
    this.removalNote = root.querySelector("[data-removal-note]");
    this.unsaved = root.querySelector("[data-unsaved]");
    this.discardBar = root.querySelector("[data-discard-confirm]");
    root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      this.#submit();
    });
    this.cancelButton.addEventListener("click", () => this.#requestClose());
    root.querySelector("[data-add-field]").addEventListener("click", () => this.#addField());
    root.querySelector("[data-add-first]").addEventListener("click", () => this.#addField());
    this.layout = root.querySelector(".af-layout");
    this.addButton = root.querySelector("[data-add-field]");
    this.emptyState = root.querySelector("[data-field-empty]");
    root.querySelector("[data-discard-keep]").addEventListener("click", () => this.#askDiscard(false));
    root.querySelector("[data-discard-go]").addEventListener("click", () => {
      this.snapshot = this.#body(); // nothing to keep
      this.modal.close();
    });
    new Sortable(this.list, { handle: ".af-grip", onMove: (from, to) => this.#moveField(from, to) });
    // closing (X, Escape, the overlay) with unsaved changes asks first, like Cancel
    modal.canClose = () => {
      if (this.busy) return false;
      if (!this.#dirty()) return true;
      this.#askDiscard(true);
      return false;
    };
  }

  /** @param {{name: string, label: string, artifact_count: number}[]} fields as the server has them */
  open(fields) {
    this.before = fields;
    this.fields = fields.map(editable);
    this.selected = this.fields[0] ?? null;
    this.problems.clear();
    this.snapshot = this.#body();
    // two lines, broken where the sentence does
    this.lead.replaceChildren("Every artifact has these fields; set their values in the artifact's Fields.", document.createElement("br"), "Pipelines read them as ${card.NAME}. A default pre-fills new artifacts.");
    this.setError("");
    this.#askDiscard(false);
    this.#renderList();
    this.#renderDetail();
    this.#changed();
    this.modal.open();
    (this.list.querySelector(".af-item__main") ?? this.root.querySelector("[data-add-first]")).focus();
  }

  #body() {
    return JSON.stringify(this.fields.map(toWrite));
  }

  #dirty() {
    return this.#body() !== this.snapshot;
  }

  /** After every change: the unsaved note, what a save would remove. */
  #changed() {
    this.unsaved.hidden = !this.#dirty();
    const lost = removedWithValues(this.before, this.fields.map((f) => f.name.trim()));
    this.removalNote.textContent = lost.length ? t("fields.saving_removes", { list: lost.map((l) => tn("fields.removes_values", l.count, { label: l.label })).join(", ") }) : "";
    this.removalNote.hidden = lost.length === 0;
  }

  #askDiscard(show) {
    this.discardBar.hidden = !show;
    if (show) this.discardBar.querySelector("[data-discard-keep]").focus();
  }

  #requestClose() {
    if (this.#dirty()) this.#askDiscard(true);
    else this.modal.close();
  }

  // ── the list ─────────────────────────────────────────────────────────

  #renderList() {
    this.list.replaceChildren(
      ...this.fields.map((field, i) => {
        const item = element("li", "af-item");
        item.dataset.field = field.uid;
        if (field === this.selected) item.classList.add("is-selected");
        const main = element("button", "af-item__main");
        main.type = "button";
        main.setAttribute("aria-pressed", String(field === this.selected));
        main.append(element("span", "af-item__label", field.label.trim() || `Field ${i + 1}`), element("span", "af-item__type", typeText(field)));
        if (this.problems.has(field.name.trim())) main.append(element("span", "af-item__problem", "!"));
        main.addEventListener("click", () => this.#select(field));
        item.append(grip(`Move ${field.label.trim() || "field"}`), main);
        return item;
      }),
    );
    // no fields: one invitation; with fields: the two panes and "Add field" at the top right
    const any = this.fields.length > 0;
    this.layout.hidden = !any;
    this.addButton.hidden = !any;
    this.emptyState.hidden = any;
  }

  #select(field) {
    this.selected = field;
    this.#renderList();
    this.#renderDetail();
  }

  #addField() {
    const field = blankField();
    this.fields.push(field);
    this.#select(field);
    this.#changed();
    this.detail.querySelector("[data-key=label]")?.focus();
  }

  #moveField(from, to) {
    const [field] = this.fields.splice(from, 1);
    this.fields.splice(to, 0, field);
    this.#renderList();
    this.#changed();
    this.list.children[to]?.querySelector(".af-grip")?.focus();
  }

  #removeField(field) {
    const i = this.fields.indexOf(field);
    this.fields.splice(i, 1);
    this.selected = this.fields[i] ?? this.fields[i - 1] ?? null;
    this.#renderList();
    this.#renderDetail();
    this.#changed();
    (this.list.querySelector(".is-selected .af-item__main") ?? this.root.querySelector("[data-add-first]")).focus();
  }

  // ── the chosen field ─────────────────────────────────────────────────

  #renderDetail() {
    const field = this.selected;
    if (!field) {
      this.detail.replaceChildren(element("p", "af-detail__empty", t("index.no_fields_yet_add_the_first")));
      return;
    }
    const grid = element("div", "af-detail__grid");
    grid.append(
      this.#input(field, "label", t("common.name"), { maxLength: 60 }),
      this.#nameField(field),
      this.#typeField(field),
    );
    if (field.type === "text") grid.append(this.#input(field, "max_length", "Maximum length (default 200)", { type: "number" }));
    if (field.type === "number") {
      grid.append(this.#input(field, "min_value", t("artifact_fields.fields_editor.minimum"), { type: "number" }), this.#input(field, "max_value", t("artifact_fields.fields_editor.maximum"), { type: "number" }));
      grid.append(this.#check(field, "integer_only", t("artifact_fields.fields_editor.whole_numbers_only")));
    }
    const parts = [grid];
    if (isSelect(field.type)) parts.push(this.#optionsBlock(field));
    parts.push(this.#defaultField(field));
    const problem = this.problems.get(field.name.trim());
    const error = element("p", "field__error", problem ?? "");
    error.setAttribute("role", "alert");
    error.hidden = !problem;
    error.dataset.fieldError = "";
    const remove = element("button", "button button--ghost button--sm is-danger af-remove");
    remove.type = "button";
    remove.append(icon("trash"), document.createTextNode(t("artifact_fields.fields_editor.remove_field")));
    remove.addEventListener("click", () => this.#removeField(field));
    parts.push(error, remove);
    this.detail.replaceChildren(...parts);
  }

  #labelled(key, label, control) {
    const wrap = element("div", "field");
    control.id = `af-${key}`;
    control.dataset.key = key;
    const caption = element("label", "field__label", label);
    caption.htmlFor = control.id;
    wrap.append(caption, control);
    return wrap;
  }

  #input(field, key, label, { type = "text", maxLength } = {}) {
    const input = element("input", "field__control");
    input.type = type;
    if (maxLength) input.maxLength = maxLength;
    if (type === "number") input.step = "any";
    input.value = field[key];
    input.autocomplete = "off";
    input.addEventListener("input", () => {
      field[key] = input.value;
      if (key === "label") {
        if (!field.saved && !field.nameEdited) {
          field.name = nameFromLabel(input.value);
          const name = this.detail.querySelector("[data-key=name]");
          if (name) name.value = field.name;
        }
        this.#renderList();
      }
      this.#changed();
    });
    return this.#labelled(key, label, input);
  }

  /** The name pipelines read (${card.NAME}): chosen while the field is new, fixed once it is saved. */
  #nameField(field) {
    if (field.saved) {
      const shown = element("input", "field__control");
      shown.value = field.name;
      shown.readOnly = true;
      shown.title = t("fields.reference_title", { name: field.name });
      return this.#labelled("name", t("artifact_fields.fields_editor.reference"), shown);
    }
    const input = element("input", "field__control");
    input.maxLength = 32;
    input.value = field.name;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.addEventListener("input", () => {
      field.name = input.value;
      field.nameEdited = true;
      this.#changed();
    });
    return this.#labelled("name", t("artifact_fields.fields_editor.reference"), input);
  }

  #typeField(field) {
    const select = element("select", "field__control");
    for (const kind of KINDS) select.append(new Option(kind.label, kind.value));
    select.value = field.type;
    select.addEventListener("change", () => {
      const wasMulti = field.type === "multi";
      field.type = select.value;
      if (field.type === "multi" && !wasMulti) field.default = field.default ? [field.default] : [];
      if (field.type !== "multi" && wasMulti) field.default = field.default[0] ?? "";
      this.#renderList();
      this.#renderDetail();
      this.#changed();
    });
    return this.#labelled("type", t("artifact_fields.fields_editor.field_type"), select);
  }

  #check(field, key, label) {
    const wrap = element("label", "at-check");
    const box = element("input");
    box.type = "checkbox";
    box.checked = field[key];
    box.dataset.key = key;
    box.addEventListener("change", () => {
      field[key] = box.checked;
      this.#changed();
    });
    wrap.append(box, document.createTextNode(` ${label}`));
    return wrap;
  }

  // ── the options of a select ──

  #optionsBlock(field) {
    const block = element("div", "af-options");
    const head = element("div", "af-options__head");
    head.append(element("span", "field__label", t("common.options")));
    const list = element("ol", "af-options__list");
    list.setAttribute("aria-label", t("common.options"));
    field.options.forEach((option) => list.append(this.#optionRow(field, option)));
    new Sortable(list, {
      handle: ".af-grip",
      onMove: (from, to) => {
        const [moved] = field.options.splice(from, 1);
        field.options.splice(to, 0, moved);
        this.#renderDetail();
        this.#changed();
        this.detail.querySelectorAll(".af-options__list .af-grip")[to]?.focus();
      },
    });
    const add = element("button", "button button--ghost button--sm");
    add.type = "button";
    add.dataset.addOption = "";
    add.append(icon("plus"), document.createTextNode(t("artifact_fields.fields_editor.add_option")));
    add.addEventListener("click", () => {
      const option = newOption("");
      field.options.push(option);
      const row = this.#optionRow(field, option);
      list.append(row);
      row.inline.edit(); // a new option starts as a text to type; an empty one is dropped
    });
    if (field.options.length === 0) block.append(head, element("p", "settings-card__empty", t("artifact_fields.fields_editor.no_options_yet")), list, add);
    else block.append(head, list, add);
    return block;
  }

  #optionRow(field, option) {
    const row = element("li", "af-option");
    const text = element("span", "af-option__text", option.text);
    row.inline = new InlineName(text, {
      label: t("artifact_fields.fields_editor.option"),
      maxLength: 40,
      keepOpenOnError: true,
      onCommit: async (value) => {
        const problem = optionProblem(field, value, option);
        if (problem) throw new Error(problem);
        if (field.type === "multi") field.default = field.default.map((d) => (d === option.text ? value.trim() : d));
        else if (field.default === option.text) field.default = value.trim();
        option.text = value.trim();
        this.#renderList();
        this.#changed();
        queueMicrotask(() => this.#refreshDefault(field));
      },
    });
    // an option that was added and left empty goes again, once its editing ends (Escape, or focus elsewhere)
    const dropIfEmpty = () =>
      setTimeout(() => {
        const editing = row.querySelector(".inline-name__input") && row.contains(document.activeElement);
        if (!option.text && !editing && field.options.includes(option)) this.#removeOption(field, option);
      }, 0);
    row.addEventListener("focusout", dropIfEmpty);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dropIfEmpty();
    });
    const more = element("button", "icon-button icon-button--sm");
    more.type = "button";
    more.setAttribute("aria-label", t("artifact_fields.fields_editor.option_actions") + (option.text ? `: ${option.text}` : ""));
    more.setAttribute("aria-haspopup", "menu");
    more.title = t("artifact_fields.fields_editor.option_actions");
    more.append(icon("more"));
    more.addEventListener("click", () =>
      this.menu.toggle(
        more,
        [
          { label: t("graph_list.rename"), icon: "pencil", onSelect: () => row.inline.edit() },
          { label: t("common.delete"), icon: "trash", danger: true, onSelect: () => this.#removeOption(field, option) },
        ],
        t("artifact_fields.fields_editor.option_text", { text: option.text }),
      ),
    );
    row.append(grip(`Move ${option.text || "option"}`), text, more);
    return row;
  }

  #removeOption(field, option) {
    field.options = field.options.filter((o) => o !== option);
    if (field.type === "multi") field.default = field.default.filter((d) => d !== option.text);
    else if (field.default === option.text) field.default = "";
    this.#renderList();
    this.#renderDetail();
    this.#changed();
  }

  // ── the default ──

  #refreshDefault(field) {
    const holder = this.detail.querySelector("[data-default]");
    if (holder && this.selected === field) holder.replaceWith(this.#defaultField(field));
  }

  #defaultField(field) {
    let control;
    if (field.type === "multi") {
      control = element("div", "af-default-multi");
      control.setAttribute("role", "group");
      control.setAttribute("aria-label", t("common.default"));
      for (const option of field.options.filter((o) => o.text)) {
        const wrap = element("label", "at-check");
        const box = element("input");
        box.type = "checkbox";
        box.checked = field.default.includes(option.text);
        box.addEventListener("change", () => {
          field.default = box.checked ? [...field.default, option.text] : field.default.filter((d) => d !== option.text);
          this.#changed();
        });
        wrap.append(box, document.createTextNode(` ${option.text}`));
        control.append(wrap);
      }
      if (!control.children.length) control.append(element("span", "settings-card__empty", t("artifact_fields.fields_editor.add_options_first")));
      const wrap = element("div", "field");
      wrap.dataset.default = "";
      wrap.append(element("span", "field__label", t("common.default")), control);
      return wrap;
    }
    if (field.type === "single" || field.type === "boolean") {
      control = element("select", "field__control");
      const choices = field.type === "boolean" ? [["", "No default"], ["true", "Yes"], ["false", "No"]] : [["", "No default"], ...field.options.filter((o) => o.text).map((o) => [o.text, o.text])];
      for (const [value, text] of choices) control.append(new Option(text, value));
      control.value = field.default;
      control.addEventListener("change", () => {
        field.default = control.value;
        this.#changed();
      });
    } else {
      control = element("input", "field__control");
      control.type = field.type === "number" ? "number" : "text";
      control.value = field.default;
      control.addEventListener("input", () => {
        field.default = control.value;
        this.#changed();
      });
    }
    const wrap = this.#labelled("default", t("common.default"), control);
    wrap.dataset.default = "";
    return wrap;
  }

  // ── saving ───────────────────────────────────────────────────────────

  async #submit() {
    if (this.busy) return;
    this.problems.clear();
    this.#askDiscard(false);
    let saved = null;
    if (await this.run(async () => (saved = await this.save(this.fields.map(toWrite))), { close: false })) {
      this.snapshot = this.#body();
      this.modal.close();
      this.onSaved(saved);
    }
  }

  showError(error) {
    const { byField, other } = parseProblems(error.detail);
    this.problems = byField;
    const first = this.fields.find((f) => byField.has(f.name.trim()));
    if (first) this.selected = first;
    this.#renderList();
    this.#renderDetail();
    const unplaced = [...byField.keys()].filter((name) => !this.fields.some((f) => f.name.trim() === name)).map((name) => `Field ${name}: ${byField.get(name)}`);
    const general = [...other, ...unplaced];
    if (general.length) this.setError(general.join(" "));
    else if (byField.size === 0) super.showError(error);
  }
}
