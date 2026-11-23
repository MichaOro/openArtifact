/* The editor of the artifact fields (ADR-044): a dialog with a row per field (label, name, kind, default and
 * what the kind needs), add / remove / reorder, saved as a whole with PUT. The server's
 * refusals (`Field NAME: ...`) are shown at their rows. The rows are rebuilt from their state when the
 * structure changes (kind, order); typing only updates the state. */
import { ActionDialog } from "../components/action-dialog.js";
import { icon } from "../components/icons.js";
import { KINDS, blankField, editable, nameFromLabel, parseProblems, removedWithValues, toWrite } from "./model.js";

let rowCounter = 0;

function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export class FieldsEditor extends ActionDialog {
  /**
   * @param {import("../components/modal.js").Modal} modal
   * @param {(fields: object[]) => Promise<object>} save sends the whole list
   * @param {(saved: object) => void} onSaved called with the server's answer
   */
  constructor(modal, save, onSaved) {
    super(modal, "Could not save the fields. Please try again.");
    this.save = save;
    this.onSaved = onSaved;
    /** The fields as they were when the editor opened (with artifact_count). */
    this.before = [];
    this.removalNote = this.root.querySelector("[data-removal-note]");
    /** @type {{state: object, id: number, el: HTMLElement}[]} */
    this.rows = [];
    this.list = this.root.querySelector("[data-fields]");
    this.lead = this.root.querySelector("[data-lead]");
    this.form = this.root.querySelector("form");
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.#submit();
    });
    this.cancelButton.addEventListener("click", () => this.modal.close());
    this.root.querySelector("[data-add-field]").addEventListener("click", () => {
      const row = this.#add(blankField());
      row.el.querySelector("[data-key=label]").focus();
    });
  }

  /** @param {{name: string, label: string, artifact_count: number}[]} fields */
  open(fields) {
    this.before = fields;
    this.rows = [];
    this.list.replaceChildren();
    for (const field of fields) this.#add(editable(field));
    this.titleEl.textContent = "Artifact fields";
    this.lead.textContent = "Every artifact has these fields; set their values in the artifact's Fields. Pipelines read them as ${card.NAME}. A default pre-fills new artifacts.";
    this.setError("");
    this.#noteRemovals();
    this.modal.open();
    this.root.querySelector("[data-key=label]")?.focus();
  }

  #add(state) {
    const row = { state, id: ++rowCounter, el: element("li", "at-field") };
    this.rows.push(row);
    this.list.append(row.el);
    this.#render(row);
    this.#numbering();
    return row;
  }

  #numbering() {
    this.rows.forEach((row, i) => {
      const title = row.el.querySelector(".at-field__title");
      title.textContent = row.state.label.trim() || `Field ${i + 1}`;
      row.el.querySelector("[data-move=up]").disabled = i === 0;
      row.el.querySelector("[data-move=down]").disabled = i === this.rows.length - 1;
    });
  }

  /** A labelled control; `key` names it for the tests and for the error placement. */
  #field(row, key, label, control, { wide = false } = {}) {
    const wrapper = element("div", `field at-field__item${wide ? " at-field__item--wide" : ""}`);
    const id = `at-${row.id}-${key}`;
    control.id = id;
    control.dataset.key = key;
    control.setAttribute("aria-describedby", `at-${row.id}-error`);
    const caption = element("label", "field__label", label);
    caption.htmlFor = id;
    wrapper.append(caption, control);
    return wrapper;
  }

  #input(row, key, label, { type = "text", maxLength, wide, value = row.state[key] } = {}) {
    const input = element("input", "field__control");
    input.type = type;
    if (maxLength) input.maxLength = maxLength;
    if (type === "number") input.step = "any";
    input.value = value;
    input.autocomplete = "off";
    input.addEventListener("input", () => {
      row.state[key] = input.value;
      this.#clear(row);
      if (key === "label") {
        if (!row.state.nameEdited) {
          row.state.name = nameFromLabel(input.value);
          const name = row.el.querySelector("[data-key=name]");
          if (name) name.value = row.state.name;
        }
        this.#numbering();
      }
      if (key === "name") row.state.nameEdited = true;
    });
    return this.#field(row, key, label, input, { wide });
  }

  #select(row, key, label, options, current, { wide, onChange } = {}) {
    const select = element("select", "field__control");
    for (const [value, text] of options) {
      const option = element("option", "", text);
      option.value = value;
      select.append(option);
    }
    select.value = current;
    select.addEventListener("change", () => {
      row.state[key] = select.value;
      this.#clear(row);
      onChange?.();
    });
    return this.#field(row, key, label, select, { wide });
  }

  #defaultControl(row) {
    const { state } = row;
    if (state.kind === "choice") {
      const options = state.options.split("\n").map((o) => o.trim()).filter(Boolean);
      const known = options.includes(state.default) ? state.default : "";
      if (known !== state.default) state.default = known;
      return this.#select(row, "default", "Default", [["", "No default"], ...options.map((o) => [o, o])], known);
    }
    if (state.kind === "boolean") return this.#select(row, "default", "Default", [["", "No default"], ["true", "Yes"], ["false", "No"]], state.default);
    return this.#input(row, "default", "Default", { type: state.kind === "number" ? "number" : "text" });
  }

  #render(row) {
    const { state } = row;
    row.el.replaceChildren();
    const head = element("div", "at-field__head");
    head.append(element("span", "at-field__title"));
    const tools = element("span", "at-field__tools");
    const tool = (name, label, symbol, action, extraClass = "") => {
      const button = element("button", `icon-button icon-button--sm ${extraClass}`.trim());
      button.type = "button";
      button.dataset.move = name;
      button.setAttribute("aria-label", label);
      button.title = label;
      button.append(icon(symbol));
      button.addEventListener("click", action);
      return button;
    };
    tools.append(
      tool("up", "Move field up", "arrow-up", () => this.#move(row, -1)),
      tool("down", "Move field down", "arrow-down", () => this.#move(row, 1)),
      tool("remove", "Remove field", "trash", () => this.#remove(row), "is-danger"),
    );
    head.append(tools);

    const grid = element("div", "at-field__grid");
    grid.append(
      this.#input(row, "label", "Label", { maxLength: 60 }),
      this.#input(row, "name", "Name", { maxLength: 32 }),
      this.#select(row, "kind", "Kind", KINDS.map((k) => [k.value, k.label]), state.kind, { onChange: () => this.#render(row) }),
    );
    if (state.kind === "choice") {
      const lines = element("textarea", "field__control field__control--lines");
      lines.rows = 3;
      lines.value = state.options;
      lines.addEventListener("input", () => {
        state.options = lines.value;
        this.#clear(row);
        const holder = row.el.querySelector("[data-key=default]")?.closest(".at-field__item");
        if (holder) holder.replaceWith(this.#defaultControl(row)); // the default is one of the values
      });
      grid.append(this.#field(row, "options", "Allowed values (one per line, 2 to 20)", lines, { wide: true }));
    }
    if (state.kind === "text") grid.append(this.#input(row, "max_length", "Maximum length (default 200)", { type: "number" }));
    if (state.kind === "number") {
      grid.append(this.#input(row, "min_value", "Minimum", { type: "number" }), this.#input(row, "max_value", "Maximum", { type: "number" }));
      const whole = element("label", "at-check");
      const box = element("input");
      box.type = "checkbox";
      box.checked = state.integer_only;
      box.dataset.key = "integer_only";
      box.addEventListener("change", () => (state.integer_only = box.checked));
      whole.append(box, document.createTextNode(" Whole numbers only"));
      grid.append(whole);
    }
    grid.append(this.#defaultControl(row));

    const error = element("p", "field__error");
    error.id = `at-${row.id}-error`;
    error.setAttribute("role", "alert");
    error.hidden = true;
    error.dataset.rowError = "";
    row.el.append(head, grid, error);
    this.#numbering();
  }

  #move(row, direction) {
    const i = this.rows.indexOf(row);
    const j = i + direction;
    if (j < 0 || j >= this.rows.length) return;
    [this.rows[i], this.rows[j]] = [this.rows[j], this.rows[i]];
    this.list.replaceChildren(...this.rows.map((r) => r.el));
    this.#numbering();
    const button = row.el.querySelector(`[data-move=${direction < 0 ? "up" : "down"}]`);
    (button.disabled ? row.el.querySelector(`[data-move=${direction < 0 ? "down" : "up"}]`) : button).focus();
  }

  #remove(row) {
    const i = this.rows.indexOf(row);
    this.rows.splice(i, 1);
    row.el.remove();
    this.#numbering();
    this.#noteRemovals();
    (this.rows[i] ?? this.rows[i - 1])?.el.querySelector("[data-key=label]").focus() ?? this.root.querySelector("[data-add-field]").focus();
  }

  #clear(row) {
    const error = row.el.querySelector("[data-row-error]");
    error.textContent = "";
    error.hidden = true;
    this.setError("");
  }

  async #submit() {
    if (this.busy) return;
    for (const row of this.rows) this.#clear(row);
    let saved = null;
    const fields = this.rows.map((row) => toWrite(row.state));
    if (await this.run(async () => (saved = await this.save(fields)), { close: true })) this.onSaved(saved);
  }

  /** Removing a field drops its values: say so, with how many artifacts have one. */
  #noteRemovals() {
    if (!this.removalNote) return;
    const lost = removedWithValues(this.before, this.rows.map((row) => row.state.name.trim()));
    this.removalNote.textContent = lost.length ? `Saving removes the values of ${lost.map((l) => `"${l.label}" (${l.count} artifact${l.count === 1 ? "" : "s"})`).join(", ")}.` : "";
    this.removalNote.hidden = lost.length === 0;
  }

  showError(error) {
    const { byField, other } = parseProblems(error.detail);
    const unplaced = [];
    for (const [name, message] of byField) {
      const row = this.rows.find((r) => r.state.name.trim() === name);
      if (!row) {
        unplaced.push(`Field ${name}: ${message}`);
        continue;
      }
      const target = row.el.querySelector("[data-row-error]");
      target.textContent = message;
      target.hidden = false;
    }
    const first = this.list.querySelector("[data-row-error]:not([hidden])");
    first?.closest(".at-field").scrollIntoView({ block: "nearest" });
    const general = [...other, ...unplaced];
    if (general.length) this.setError(general.join(" "));
    else if (byField.size === 0) super.showError(error);
  }
}
