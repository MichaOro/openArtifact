/* The controls of the inspector for the settings of a node, one class per setting type the server
 * describes (GET /api/node-types: integer, number, switch, text, lines, code, select). A control shows the
 * value, saves it through `save(value)` (which resolves to null, or to the message of a refusal) and
 * keeps what the user typed when the save is refused. Add a type by subclassing SettingControl and
 * listing it in CONTROLS. */
import { field } from "./field.js";
import { suggestReferences } from "./reference-suggest.js";

const AUTOSAVE_MS = 800; // multi-line fields save this long after the last keystroke
const INDENT = "  ";
const LEAVE_HINT = "Tab indents. Press Escape, then Tab to leave the field.";

function element(tag, className, text = null) {
  const el = document.createElement(tag);
  el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

/** Where a setting's value is kept on the node: its own property, or the node's `config` object. */
export function settingValue(node, setting) {
  const stored = setting.stored_in === "config" ? node.config?.[setting.key] : node[setting.key];
  return stored ?? setting.default ?? null;
}

class SettingControl {
  /**
   * @param {object} setting the server's description of the setting
   * @param {*} value what is stored now
   * @param {(value: *) => Promise<string|null>} save resolves to null, or to why the value was refused
   * @param {{nodes: () => object[], exceptId?: string}|null} suggest the graph's nodes, for the suggestions
   *   of a text that takes references (null: none)
   */
  constructor(setting, value, save, suggest = null) {
    this.setting = setting;
    this.saved = value;
    this.save = save;
    this.busy = false;
    this.again = false;
    this.input = this.createInput(value);
    this.input.dataset.focusKey = `setting-${setting.key}`;
    this.input.addEventListener("change", () => this.commit());
    if (suggest && setting.references && this.constructor.suggests) suggestReferences(this.input, suggest, { allowSecrets: setting.references === "all" });
    this.element = this.build();
  }

  /** The editable element (an input, a textarea, a select ...). */
  createInput(value) {
    throw new Error("A control makes its input");
  }

  read() {
    return this.input.value;
  }

  /** The value as the server wants it, or throws a message for the user (not yet worth a request). */
  parse(raw) {
    return raw;
  }

  /** Whether the layout puts label and control on one line. */
  static row = false;

  /** Whether the control offers suggestions for ${...} references (text and lines, not code). */
  static suggests = false;

  /** Text under the control that is not the setting's own help (null: none). */
  hint() {
    return null;
  }

  build() {
    const box = element("div", "ge-setting");
    const labelled = field(this.setting.label, this.input, { row: this.constructor.row });
    const id = this.input.id;
    this.status = element("span", "field__status");
    this.status.id = `${id}-status`;
    this.status.setAttribute("aria-live", "polite");
    this.error = element("p", "field__error");
    this.error.id = `${id}-error`;
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    const notes = [this.setting.help, this.hint()].filter(Boolean).map((text, index) => {
      const note = element("p", "field__help", text);
      note.id = `${id}-help-${index}`;
      return note;
    });
    this.input.setAttribute("aria-describedby", [...notes.map((n) => n.id), this.status.id, this.error.id].join(" "));
    box.append(labelled, this.error, this.status, ...notes);
    return box;
  }

  /** The user is done with a value: save it (one request at a time, the latest value wins). */
  async commit() {
    if (this.busy) {
      this.again = true;
      return;
    }
    this.busy = true;
    try {
      do {
        this.again = false;
        await this.#saveCurrent();
      } while (this.again);
    } finally {
      this.busy = false;
    }
  }

  async #saveCurrent() {
    let value;
    try {
      value = this.parse(this.read());
    } catch (error) {
      this.fail(error.message);
      return;
    }
    if (value === this.saved) {
      this.fail(null);
      return;
    }
    this.status.textContent = "Saving…";
    const message = await this.save(value);
    if (message) {
      this.fail(message);
      return;
    }
    this.saved = value;
    this.fail(null);
    this.status.textContent = "Saved";
  }

  /** Show why a value was not saved (null: clear it). The typed text stays as it is. */
  fail(message) {
    this.error.textContent = message ?? "";
    this.error.hidden = !message;
    if (message) this.input.setAttribute("aria-invalid", "true");
    else this.input.removeAttribute("aria-invalid");
    if (message) this.status.textContent = "";
  }
}

class IntegerControl extends SettingControl {
  createInput(value) {
    const input = element("input", "field__control");
    input.type = "number";
    input.step = "1";
    if (this.setting.minimum != null) input.min = String(this.setting.minimum);
    if (this.setting.maximum != null) input.max = String(this.setting.maximum);
    input.value = String(value ?? "");
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.commit(); // the focus stays where it is
    });
    return input;
  }

  parse(raw) {
    const number = Number(raw);
    if (raw.trim() === "" || !Number.isInteger(number)) throw new Error("Enter a whole number.");
    return number;
  }
}

/** A whole or decimal number (the bounds are the setting's). */
class NumberControl extends IntegerControl {
  createInput(value) {
    const input = super.createInput(value);
    input.step = "any";
    return input;
  }

  parse(raw) {
    const number = Number(raw);
    if (raw.trim() === "" || Number.isNaN(number)) throw new Error("Enter a number.");
    return number;
  }
}

class SwitchControl extends SettingControl {
  static row = true;

  createInput(value) {
    const toggle = element("button", "ge-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    const state = element("span", "ge-switch__state");
    toggle.append(state, element("span", "ge-switch__thumb"));
    this.show = (on) => {
      toggle.setAttribute("aria-checked", String(on));
      state.textContent = on ? "On" : "Off";
    };
    this.show(Boolean(value));
    toggle.addEventListener("click", () => this.#flip());
    return toggle;
  }

  read() {
    return this.input.getAttribute("aria-checked") === "true";
  }

  async #flip() {
    if (this.busy) return;
    const wanted = !this.saved;
    this.show(wanted);
    this.busy = true;
    const message = await this.save(wanted);
    this.busy = false;
    if (message) {
      this.show(this.saved);
      this.fail(message);
      return;
    }
    this.saved = wanted;
    this.fail(null);
  }
}

class TextControl extends SettingControl {
  static suggests = true;

  createInput(value) {
    const input = element("input", "field__control");
    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (this.setting.max_length) input.maxLength = this.setting.max_length;
    if (this.setting.placeholder) input.placeholder = this.setting.placeholder;
    input.value = value ?? "";
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.commit();
    });
    return input;
  }
}

/** Several lines: saved a moment after typing stops and when the field is left; a counter shows the length. */
class LinesControl extends SettingControl {
  static suggests = true;

  createInput(value) {
    const area = element("textarea", `field__control ${this.constructor.inputClass}`.trim());
    area.spellcheck = false;
    area.rows = this.constructor.rows;
    if (this.setting.placeholder) area.placeholder = this.setting.placeholder;
    area.value = value ?? "";
    let timer = null;
    area.addEventListener("input", () => {
      this.updateCount();
      this.status.textContent = "";
      clearTimeout(timer);
      timer = setTimeout(() => this.commit(), AUTOSAVE_MS);
    });
    area.addEventListener("change", () => clearTimeout(timer));
    return area;
  }

  static inputClass = "field__control--lines";
  static rows = 5;

  build() {
    const box = super.build();
    this.count = element("span", "field__meta");
    this.input.after(this.count);
    this.updateCount();
    return box;
  }

  updateCount() {
    const text = this.input.value;
    const lines = text === "" ? 0 : text.split("\n").length;
    const max = this.setting.max_length;
    const over = max != null && text.length > max;
    this.count.textContent = `${lines} ${lines === 1 ? "line" : "lines"}${max != null ? ` · ${text.length} / ${max}${over ? " (too long)" : ""}` : ""}`;
    this.count.classList.toggle("is-over", over);
  }
}

/** Source code: monospace, Tab indents; Escape then Tab leaves the field (so the keyboard is never trapped). */
class CodeControl extends LinesControl {
  static suggests = false; // the code text is never interpolated, so a reference in it means nothing
  static inputClass = "field__control--code";
  static rows = 10;

  createInput(value) {
    const area = super.createInput(value);
    area.wrap = "off";
    let leaving = false;
    area.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        leaving = true;
      } else if (event.key === "Tab" && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey) {
        if (!leaving) {
          event.preventDefault();
          area.setRangeText(INDENT, area.selectionStart, area.selectionEnd, "end");
          area.dispatchEvent(new Event("input", { bubbles: true }));
        }
        leaving = false;
      } else if (event.key !== "Shift") {
        leaving = false;
      }
    });
    area.addEventListener("blur", () => {
      leaving = false;
    });
    return area;
  }

  hint() {
    return LEAVE_HINT;
  }
}

class SelectControl extends SettingControl {
  createInput(value) {
    const select = element("select", "field__control");
    for (const option of this.setting.options ?? []) select.append(new Option(option, option));
    select.value = value ?? "";
    return select;
  }
}

const CONTROLS = {
  integer: IntegerControl,
  number: NumberControl,
  switch: SwitchControl,
  text: TextControl,
  lines: LinesControl,
  code: CodeControl,
  select: SelectControl,
};

/** The control for a setting; a type this editor does not know is shown as plain text. */
export function createControl(setting, value, save, suggest = null) {
  return new (CONTROLS[setting.type] ?? TextControl)(setting, value, save, suggest);
}
