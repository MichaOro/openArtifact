/* The controls of the inspector for the settings of a node, one class per setting type the server
 * describes (GET /api/node-types: integer, number, switch, text, lines, code, select). A control shows the
 * value, saves it through `save(value)` (which resolves to null, or to the message of a refusal) and
 * keeps what the user typed when the save is refused. When a control saves is the policy of persist-policy.js (a text
 * on leaving the field or Enter, a choice when it changes, never on a keystroke). Add a type by subclassing
 * SettingControl and listing it in CONTROLS. */
import { CredentialDialog } from "../components/credential-dialog.js";
import { DurationInput } from "../components/duration-input.js";
import { describeDuration } from "../components/duration-model.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { field } from "./field.js";
import { bindPersist, registerDirty, trackSave } from "./persist-policy.js";
import { suggestReferences } from "./reference-suggest.js";
import { t, tn } from "../i18n.js";

const INDENT = "  ";
const LEAVE_HINT = t("editor.setting_controls.tab_indents_press_escape_then");

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

/** What `saved` holds while a control has nothing stored: no value is equal to it. */
const NOT_SAVED = Symbol("not saved");

class SettingControl {
  /**
   * @param {object} setting the server's description of the setting
   * @param {*} value what is stored now
   * @param {(value: *) => Promise<string|null>} save resolves to null, or to why the value was refused
   * @param {{nodes: () => object[], exceptId?: string}|null} suggest the graph's nodes, for the suggestions
   *   of a text that takes references (null: none)
   * @param {{unsaved?: boolean, end?: HTMLElement|null}} [options] `unsaved`: nothing is stored yet (an override being made, an
   *   optional setting just added): `value` is only what the field starts with, and committing it saves it even when it is
   *   the same (Enter on a field is a decision). `end`: what closes the row of the control (the bin of a removable setting),
   *   in a column of its own so it never lies over the control
   */
  constructor(setting, value, save, suggest = null, { unsaved = false, end = null } = {}) {
    this.setting = setting;
    this.end = end;
    this.saved = unsaved ? NOT_SAVED : value;
    this.save = save;
    this.busy = false;
    this.again = false;
    this.input = this.createInput(value);
    this.input.dataset.focusKey = `setting-${setting.key}`;
    if (this.constructor.kind !== "toggle")
      bindPersist(this.input, this.constructor.kind, (event) => {
        if (event.type === "focusout" && !this.isDirty()) return; // leaving a field nothing was typed in decides nothing
        this.commit();
      });
    this.baseline = this.read();
    this.input.addEventListener("input", () => this.markDirty());
    registerDirty({ isDirty: () => this.isDirty(), commit: () => this.commit(), element: this.input });
    if (suggest && setting.references && this.constructor.suggests) {
      suggestReferences(this.input, suggest, { allowSecrets: setting.references === "all" });
    }
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

  /** How the control saves (persist-policy.js): "text", "multiline", "choice" or "toggle". */
  static kind = "choice";

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
    // the explanation (the setting's help and the control's own hint) is a tooltip after the label, not text under the field
    const help = [this.setting.help, this.hint()].filter(Boolean).join("\n\n");
    const labelled = field(this.setting.label, this.input, { row: this.constructor.row, help: help || null, end: this.end });
    const id = this.input.id;
    this.status = element("span", "field__status");
    this.status.id = `${id}-status`;
    this.status.setAttribute("aria-live", "polite");
    this.error = element("p", "field__error");
    this.error.id = `${id}-error`;
    this.error.setAttribute("role", "alert");
    this.error.hidden = true;
    this.input.setAttribute("aria-describedby", [this.input.getAttribute("aria-describedby"), this.status.id, this.error.id].filter(Boolean).join(" "));
    box.append(labelled, this.error, this.status);
    return box;
  }

  /** Text typed and not saved yet. */
  isDirty() {
    return (this.constructor.kind === "text" || this.constructor.kind === "multiline") && this.read() !== this.baseline;
  }

  /** The "not saved" marker while text is typed that no request carries yet. */
  markDirty() {
    const dirty = this.isDirty();
    this.element?.classList.toggle("is-dirty", dirty);
    if (this.status) this.status.textContent = dirty ? t("agents.editor_page.not_saved") : "";
  }

  /** The user is done with a value: save it (one request at a time, the latest value wins). */
  commit() {
    return trackSave(this.#drain());
  }

  async #drain() {
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
      this.baseline = this.read();
      this.fail(null);
      this.markDirty();
      return;
    }
    this.status.textContent = t("editor.setting_controls.saving");
    const message = await this.save(value);
    if (message) {
      this.fail(message);
      return;
    }
    this.saved = value;
    this.baseline = this.read();
    this.fail(null);
    this.element.classList.remove("is-dirty");
    this.status.textContent = t("agents.editor_page.saved");
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
  static kind = "text";

  createInput(value) {
    const input = element("input", "field__control");
    input.type = "number";
    input.step = "1";
    if (this.setting.minimum != null) input.min = String(this.setting.minimum);
    if (this.setting.maximum != null) input.max = String(this.setting.maximum);
    input.value = String(value ?? "");
    return input;
  }

  parse(raw) {
    const number = Number(raw);
    if (raw.trim() === "" || !Number.isInteger(number)) throw new Error(t("editor.setting_controls.enter_whole_number"));
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
    if (raw.trim() === "" || Number.isNaN(number)) throw new Error(t("editor.setting_controls.enter_number"));
    return number;
  }
}

class SwitchControl extends SettingControl {
  static kind = "toggle";
  static row = true;

  createInput(value) {
    const toggle = element("button", "ge-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    const state = element("span", "ge-switch__state");
    toggle.append(state, element("span", "ge-switch__thumb"));
    this.show = (on) => {
      toggle.setAttribute("aria-checked", String(on));
      state.textContent = on ? "On" : t("components.switch.off");
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
    const before = this.read();
    const wanted = !before;
    this.show(wanted);
    this.busy = true;
    const message = await this.save(wanted);
    this.busy = false;
    if (message) {
      this.show(before);
      this.fail(message);
      return;
    }
    this.saved = wanted;
    this.fail(null);
  }
}

/** *Retry on fail* (ADR-073): the switch on the line of the label, and while it is on the number of tries and the wait between
 * them (a number and a unit, ADR-074). One setting, one value `{enabled, max_tries, wait_ms}` (milliseconds): the switch saves when it
 * flips, the numbers when they are left, a unit when it changes; a value that does not fit says why in plain words and is not sent.
 * Off keeps the numbers; taking the setting away (the bin) is "no retry". An added setting starts on, with the defaults, and is
 * stored at once: a row that shows On and holds nothing would lie. */
class RetryControl extends SettingControl {
  static kind = "toggle";
  static row = true;

  constructor(setting, value, save, suggest = null, options = {}) {
    super(setting, value, save, suggest, options);
    if (options.unsaved) queueMicrotask(() => this.commit());
  }

  createInput(value) {
    const [, , defaultTries] = this.setting.limits.max_tries;
    const [, , defaultWait] = this.setting.limits.wait_ms;
    const stored = value && typeof value === "object" ? value : {};
    this.tries = element("input", "field__control");
    this.tries.type = "number";
    this.tries.step = "1";
    this.tries.min = String(this.setting.limits.max_tries[0]);
    this.tries.max = String(this.setting.limits.max_tries[1]);
    this.tries.value = String(stored.max_tries ?? defaultTries);
    this.tries.dataset.focusKey = `setting-${this.setting.key}-tries`;
    this.tries.addEventListener("input", () => this.markDirty());
    bindPersist(this.tries, "text", (event) => {
      if (event.type === "focusout" && !this.isDirty()) return;
      this.commit();
    });
    this.wait = new DurationInput({
      milliseconds: stored.wait_ms ?? defaultWait,
      focusKey: `setting-${this.setting.key}-wait`,
      onInput: () => this.markDirty(),
      onCommit: () => this.commit(),
    });
    for (const el of [this.tries, this.wait.number, this.wait.unit]) registerDirty({ isDirty: () => this.isDirty(), commit: () => this.commit(), element: el });
    const toggle = element("button", "ge-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    const state = element("span", "ge-switch__state");
    toggle.append(state, element("span", "ge-switch__thumb"));
    this.show = (on) => {
      toggle.setAttribute("aria-checked", String(on));
      state.textContent = on ? "On" : t("components.switch.off");
      if (this.details) this.details.hidden = !on;
    };
    this.show(stored.enabled ?? true);
    toggle.addEventListener("click", () => this.#flip());
    return toggle;
  }

  build() {
    const box = super.build();
    this.details = element("div", "ge-retry");
    this.details.hidden = !this.enabled;
    const limits = this.setting.limits;
    this.details.append(
      field(t("editor.retry.max_tries"), this.tries, { help: t("editor.retry.max_tries_help", { min: limits.max_tries[0], max: limits.max_tries[1] }) }),
      field(t("editor.retry.wait"), this.wait.element, { labelFor: this.wait.number, help: t("editor.retry.wait_help", { max: describeDuration(limits.wait_ms[1]) }) }),
    );
    box.querySelector(".field").after(this.details);
    return box;
  }

  get enabled() {
    return this.input.getAttribute("aria-checked") === "true";
  }

  /** The numbers as typed, canonical, so that "nothing changed" is a text comparison. */
  read() {
    return JSON.stringify({ enabled: this.enabled, max_tries: this.tries.value.trim(), wait_ms: this.wait.milliseconds });
  }

  parse(raw) {
    const typed = JSON.parse(raw);
    const [minTries, maxTries] = this.setting.limits.max_tries;
    const [minWait, maxWait] = this.setting.limits.wait_ms;
    const tries = Number(typed.max_tries);
    if (typed.max_tries === "" || !Number.isInteger(tries) || tries < minTries || tries > maxTries) {
      throw new Error(t("editor.retry.tries_bounds", { min: minTries, max: maxTries }));
    }
    const wait = typed.wait_ms;
    if (!Number.isFinite(wait) || wait < minWait || wait > maxWait) throw new Error(t("editor.retry.wait_bounds", { max: describeDuration(maxWait) }));
    const total = (tries - 1) * wait;
    if (total > this.setting.limits.total_wait_ms) {
      throw new Error(t("editor.retry.total_bounds", { tries, wait: describeDuration(wait), total: describeDuration(total), max: describeDuration(this.setting.limits.total_wait_ms) }));
    }
    const value = { enabled: typed.enabled, max_tries: tries, wait_ms: wait };
    const saved = this.saved && typeof this.saved === "object" ? this.saved : null;
    return saved && JSON.stringify(saved) === JSON.stringify(value) ? saved : value; // the stored object itself when nothing changed
  }

  isDirty() {
    return this.read() !== this.baseline;
  }

  markDirty() {
    const dirty = this.isDirty();
    this.element?.classList.toggle("is-dirty", dirty);
    if (this.status) this.status.textContent = dirty ? t("agents.editor_page.not_saved") : "";
  }

  async #flip() {
    const before = this.enabled;
    this.show(!before);
    await this.commit();
    if (!this.error.hidden) this.show(before); // refused: the switch goes back
  }
}

class TextControl extends SettingControl {
  static kind = "text";
  static suggests = true;

  createInput(value) {
    const input = element("input", "field__control");
    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (this.setting.max_length) input.maxLength = this.setting.max_length;
    if (this.setting.placeholder) input.placeholder = this.setting.placeholder;
    input.value = value ?? "";
    return input;
  }
}

/** Several lines: saved when the field is left (and on Ctrl+Enter), never while typing; a counter shows the length. */
class LinesControl extends SettingControl {
  static kind = "multiline";
  static suggests = true;

  createInput(value) {
    const area = element("textarea", `field__control ${this.constructor.inputClass}`.trim());
    area.spellcheck = false;
    area.rows = this.constructor.rows;
    if (this.setting.placeholder) area.placeholder = this.setting.placeholder;
    area.value = value ?? "";
    area.addEventListener("input", () => this.updateCount());
    return area;
  }

  static inputClass = "field__control--lines";
  static rows = 5;

  build() {
    const box = super.build();
    this.count = element("span", "field__meta");
    box.querySelector(".field__head").append(this.count); // the count sits on the label's line, to the right
    this.updateCount();
    return box;
  }

  updateCount() {
    const text = this.input.value;
    const lines = text === "" ? 0 : text.split("\n").length;
    const max = this.setting.max_length;
    const over = max != null && text.length > max;
    this.count.textContent = `${tn("count.line", lines)}${max != null ? ` · ${text.length} / ${max}${over ? t("editor.setting_controls.too_long") : ""}` : ""}`;
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
        // the first Escape only lets the next Tab leave the field; the settings dialog around it stays open.
        // A second one (nothing typed in between) closes the dialog as everywhere else.
        if (!leaving) {
          event.preventDefault();
          event.stopPropagation();
        }
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
  /** The choices as `[value, text]`: the setting's `options`, or `choices` a page adds to it (a provider is stored by
   * id and shown by name); `emptyLabel` adds a first entry that stands for no choice. */
  createInput(value) {
    const select = element("select", "field__control");
    const choices = this.setting.choices ?? (this.setting.options ?? []).map((o) => [o, this.setting.option_labels?.[o] ?? o]);
    if (this.setting.emptyLabel) select.append(new Option(this.setting.emptyLabel, ""));
    const off = this.setting.disabled_options ?? [];
    for (const [id, text] of choices) {
      const option = new Option(text, id);
      option.disabled = off.includes(id); // a reminder of what is not built yet: shown, not selectable
      select.append(option);
    }
    if (value && !choices.some(([id]) => id === value)) select.append(new Option(t("editor.setting_controls.value_not_available", { value }), value));
    select.value = value ?? this.setting.default ?? ""; // an added setting nobody chose yet shows what applies: its default
    return select;
  }

  parse(raw) {
    if (raw === "" && this.setting.emptyLabel) throw new Error(t("editor.setting_controls.choose_one"));
    return raw;
  }
}

/** The one window that edits credentials, made when first needed (its markup is on the editor page). */
let credentialWindow = null;
let credentialTypes = [];
function credentialDialog() {
  credentialWindow ??= new CredentialDialog(new Modal(document.getElementById("credential-modal")), { types: () => credentialTypes });
  return credentialWindow;
}

const CREATE = "\u0000create"; // the entry that makes a new credential (no credential can have this name)

/** A credential of the credential store: a list of the ones the node accepts, a pencil to change the chosen one and an entry
 * that makes a new one. The window is the one of the Credentials page: both work on the same data. */
class CredentialControl extends SelectControl {
  createInput(value) {
    const select = element("select", "field__control");
    select.append(new Option(t("editor.setting_controls.no_credential"), ""));
    this.last = value ?? ""; // the choice before "create new" was picked
    this.fill(select, value ?? "");
    return select;
  }

  /** The credentials that fit (enabled, of an accepted type), and the stored one even when it is not among them. */
  async fill(select, value) {
    let found = [];
    try {
      [credentialTypes, found] = await Promise.all([credentialTypes.length ? credentialTypes : request("/api/credentials/types"), request("/api/credentials?category=external")]);
    } catch {
      /* the list stays empty: the stored name is still shown */
    }
    const accepted = this.setting.credential_types ?? [];
    const names = found.filter((c) => c.status === "active" && (!accepted.length || accepted.includes(c.type))).map((c) => c.name);
    select.replaceChildren(new Option(t("editor.setting_controls.no_credential"), ""));
    for (const name of names) select.append(new Option(name, name));
    if (value && !names.includes(value)) select.append(new Option(t("editor.setting_controls.value_not_available", { value }), value));
    select.append(new Option(`+ ${t("editor.setting_controls.create_credential")}`, CREATE));
    select.value = value;
    if (this.edit) this.edit.hidden = !value;
  }

  build() {
    const box = super.build();
    this.edit = element("button", "icon-button icon-button--sm ge-credential__edit");
    this.edit.type = "button";
    this.edit.title = t("editor.setting_controls.edit_credential");
    this.edit.setAttribute("aria-label", this.edit.title);
    this.edit.append(icon("pencil"));
    this.edit.hidden = !this.input.value;
    this.edit.addEventListener("click", () => this.change());
    this.input.addEventListener("change", () => {
      if (this.input.value === CREATE) this.make();
      else {
        this.last = this.input.value;
        this.edit.hidden = !this.input.value;
      }
    });
    const wrap = element("div", "ge-credential");
    this.input.replaceWith(wrap);
    wrap.append(this.input, this.edit);
    return box;
  }

  /** Choosing "create new" saves nothing: the window opens and the new credential is chosen once it is stored. */
  commit() {
    return this.input.value === CREATE ? Promise.resolve() : super.commit();
  }

  /** A new credential of an accepted type; it is chosen once it is saved. */
  make() {
    const back = this.last;
    const dialog = credentialDialog();
    dialog.modal.dialog.addEventListener("close", () => { if (this.input.value === CREATE) this.input.value = back; }, { once: true });
    dialog.open("external", null, {
      only: this.setting.credential_types ?? null,
      onSaved: async (name) => {
        await this.fill(this.input, name);
        this.last = name;
        this.commit();
      },
    });
  }

  async change() {
    const found = await request(`/api/credentials/${encodeURIComponent(this.input.value)}`).catch(() => null);
    if (found) credentialDialog().open("external", found, { onSaved: () => this.fill(this.input, this.input.value) });
  }
}

const CONTROLS = {
  credential: CredentialControl,
  integer: IntegerControl,
  number: NumberControl,
  switch: SwitchControl,
  text: TextControl,
  lines: LinesControl,
  code: CodeControl,
  select: SelectControl,
  retry: RetryControl,
};

/** The control for a setting; a type this editor does not know is shown as plain text. */
export function createControl(setting, value, save, suggest = null, options = {}) {
  return new (CONTROLS[setting.type] ?? TextControl)(setting, value, save, suggest, options);
}
