/* The controls of the inspector for the settings of a node, one class per setting type the server
 * describes (GET /api/node-types: integer, number, switch, text, lines, code, select). A control shows the
 * value, saves it through `save(value)` (which resolves to null, or to the message of a refusal) and
 * keeps what the user typed when the save is refused. When a control saves is the policy of persist-policy.js (a text
 * on leaving the field or Enter, a choice when it changes, never on a keystroke). Add a type by subclassing
 * SettingControl and listing it in CONTROLS. */
import { CredentialDialog } from "../components/credential-dialog.js";
import { DurationInput } from "../components/duration-input.js";
import { describeDuration } from "../components/duration-model.js";
import { describeSize } from "../components/size-model.js";
import { SizeInput } from "../components/size-input.js";
import { SchemaFields } from "../components/schema-fields.js";
import { icon } from "../components/icons.js";
import { Modal } from "../components/modal.js";
import { request } from "../http.js";
import { Sortable } from "../components/sortable.js";
import { field } from "./field.js";
import { bindPersist, registerDirty, trackSave } from "./persist-policy.js";
import { addSource, listProblem, moveSource, parseNames, removeSource, setOption, specOf, unused } from "./sources-model.js";
import { suggestReferences } from "./reference-suggest.js";
import { readableReferences } from "./reference-completion.js";
import { t, tn } from "../i18n.js";

const INDENT = "  ";
/** What an added size setting starts at: the default output limit of an instance (64 KiB). */
const SIZE_START = 64 * 1024;
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
    this.source = suggest; // what the graph offers a control (its nodes, the inputs a placement maps), also for controls that take no suggestions
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
    this.suggest = suggest && setting.references && this.constructor.suggests ? suggest : null;
    if (this.suggest) suggestReferences(this.input, this.suggest, { allowSecrets: setting.references === "all" });
    this.element = this.build();
    this.refs = element("p", "field__meta ge-refs");
    this.refs.dataset.references = "";
    this.element.append(this.refs);
    this.showReferences();
    if (this.suggest) this.input.addEventListener("input", () => this.showReferences());
  }

  /** Under a field whose text names nodes by their ids (ADR-082) a line says which nodes they are now, by name: the id is for the
   * machine, the name for the reader, and a rename shows here at once. Nothing is shown while the text holds no id. */
  showReferences() {
    const text = this.suggest ? this.input.value : "";
    const readable = text.includes("${node:") ? readableReferences(text, this.suggest.nodes()) : "";
    this.refs.textContent = readable ? `${t("editor.setting_controls.refers_to")} ${readable}` : "";
    this.refs.hidden = !readable;
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

  /** The element inside a composite control the label belongs to (null: the control itself). */
  labelTarget() {
    return null;
  }

  /** Text under the control that is not the setting's own help (null: none). */
  hint() {
    return null;
  }

  build() {
    const box = element("div", "ge-setting");
    // the explanation (the setting's help and the control's own hint) is a tooltip after the label, not text under the field
    const help = [this.setting.help, this.hint()].filter(Boolean).join("\n\n");
    const labelled = field(this.setting.label, this.input, { row: this.constructor.row, help: help || null, end: this.end, labelFor: this.labelTarget() });
    const id = (this.labelTarget() ?? this.input).id;
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

/** A size in bytes (the output limit of an Execute Command node): a number and a unit (B, KiB, MiB), the value is bytes (ADR-075).
 * Saves when the number is left or Enter is pressed and when the unit changes; a value that does not fit says why in plain words
 * and is not sent. An added setting starts at the default size and is stored at once, so the row never shows what is not stored. */
class SizeControl extends SettingControl {
  static kind = "toggle"; // the control binds its own number and unit (a composite), not the wrapper

  constructor(setting, value, save, suggest = null, options = {}) {
    super(setting, value, save, suggest, options);
    if (options.unsaved) queueMicrotask(() => this.commit());
  }

  createInput(value) {
    this.size = new SizeInput({
      bytes: Number.isInteger(value) ? value : SIZE_START,
      min: 0,
      focusKey: `setting-${this.setting.key}`,
      onInput: () => this.markDirty(),
      onCommit: () => this.commit(),
    });
    for (const el of [this.size.number, this.size.unit]) registerDirty({ isDirty: () => this.isDirty(), commit: () => this.commit(), element: el });
    return this.size.element;
  }

  labelTarget() {
    return this.size.number;
  }

  read() {
    return String(this.size.bytes);
  }

  parse(raw) {
    const bytes = Number(raw);
    const { minimum, maximum } = this.setting;
    if (!Number.isFinite(bytes) || bytes < minimum || bytes > maximum) {
      throw new Error(t("editor.size.bounds", { min: describeSize(minimum), max: describeSize(maximum) }));
    }
    return bytes;
  }

  isDirty() {
    return this.read() !== this.baseline;
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

/** The words for what is wrong with a source (sources-model.js `entryProblem`). */
function problemText({ code, params }) {
  if (code === "count_bounds") return t("editor.sources.count_bounds", params);
  if (code === "names_many") return t("editor.sources.names_many", params);
  if (code === "names_long") return t("editor.sources.names_long", params);
  return t("editor.sources.names_twice", params);
}

/** The sources of a Build Context node (ADR-078): an ordered list, the order being the priority when the size limit runs out. Each row has
 * a handle to reorder it (components/sortable.js: drag, or ArrowUp / ArrowDown on the handle), the source's name, the options that source takes
 * (a number of items, title or text of related cards, the names of nodes) and a bin; the list ends with a select that adds a source not used
 * yet. One setting, one value (the list): a choice (add, remove, move, a select) saves at once, a typed number or name list when it is
 * left; a value that does not fit says why in plain words and is not sent (the rules are sources-model.js, the server's the same). */
class SourcesControl extends SettingControl {
  static kind = "toggle"; // the rows bind their own events (a composite), not the wrapper
  static row = false;

  createInput(value) {
    this.specs = this.setting.sources ?? [];
    this.max = this.setting.max_sources ?? 8;
    this.list = Array.isArray(value) ? value.map((entry) => ({ ...entry })) : [];
    const box = element("div", "ge-sources");
    box.dataset.focusKey = `setting-${this.setting.key}`;
    this.rows = element("ul", "ge-sources__list");
    this.rows.setAttribute("aria-label", this.setting.label);
    this.add = element("select", "field__control ge-sources__add");
    this.add.dataset.focusKey = `setting-${this.setting.key}-add`;
    this.add.addEventListener("change", () => this.addChosen());
    this.live = element("p", "visually-hidden");
    this.live.setAttribute("aria-live", "polite");
    box.append(this.rows, this.add, this.live);
    new Sortable(this.rows, { handle: ".ge-source__grip", onMove: (from, to, by) => this.moveRow(from, to, by) });
    this.draw();
    return box;
  }

  labelTarget() {
    return this.add;
  }

  read() {
    return JSON.stringify(this.list);
  }

  parse(raw) {
    const list = JSON.parse(raw);
    const problem = listProblem(list, this.specs);
    if (problem) throw new Error(problemText(problem));
    const saved = Array.isArray(this.saved) ? this.saved : null;
    return saved && JSON.stringify(saved) === raw ? saved : list; // the stored list itself when nothing changed
  }

  isDirty() {
    return this.read() !== this.baseline;
  }

  sourceLabel(key) {
    return t(`editor.sources.source.${key}.label`);
  }

  draw() {
    this.rows.replaceChildren(...this.list.map((entry, index) => this.row(entry, index)));
    const free = unused(this.list, this.specs);
    this.add.replaceChildren(new Option(t("editor.sources.add"), ""), ...free.map((spec) => new Option(this.sourceLabel(spec.key), spec.key)));
    this.add.disabled = !free.length || this.list.length >= this.max;
  }

  row(entry, index) {
    const spec = specOf(this.specs, entry.source) ?? { key: entry.source };
    const item = element("li", "ge-source");
    const grip = element("button", "icon-button icon-button--sm ge-source__grip");
    grip.type = "button";
    grip.setAttribute("aria-label", t("editor.sources.drag", { label: this.sourceLabel(spec.key) }));
    grip.title = t("editor.sources.drag_help");
    grip.append(icon("grip"));
    const name = element("span", "ge-source__name", this.sourceLabel(spec.key));
    name.title = t(`editor.sources.source.${spec.key}.help`);
    const options = element("span", "ge-source__options");
    if (spec.count) options.append(this.countInput(entry, index, spec));
    if (spec.detail) options.append(this.detailSelect(entry, index, spec));
    if (spec.names) options.append(this.namesInput(entry, index, spec));
    const bin = element("button", "icon-button icon-button--sm ge-source__bin");
    bin.type = "button";
    bin.title = t("editor.sources.remove", { label: this.sourceLabel(spec.key) });
    bin.setAttribute("aria-label", bin.title);
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.removeRow(index));
    item.append(grip, name, options, bin);
    return item;
  }

  /** A typed value is kept in the list as it is typed; it is saved when the field is left (the policy of persist-policy.js). */
  typed(input, kind) {
    const element = input;
    element.addEventListener("input", () => this.markDirty());
    bindPersist(element, kind, (event) => {
      if (event.type === "focusout" && !this.isDirty()) return;
      this.commit();
    });
    registerDirty({ isDirty: () => this.isDirty(), commit: () => this.commit(), element });
  }

  countInput(entry, index, spec) {
    const input = element("input", "field__control ge-source__count");
    input.type = "number";
    input.step = "1";
    input.min = String(spec.count[0]);
    input.max = String(spec.count[1]);
    input.value = String(entry.count ?? spec.count[2]);
    input.setAttribute("aria-label", t("editor.sources.count_label", { label: this.sourceLabel(spec.key) }));
    input.title = t("editor.sources.count_help");
    input.addEventListener("input", () => {
      this.list = setOption(this.list, index, "count", input.value.trim() === "" ? null : Number(input.value));
    });
    this.typed(input, "text");
    return input;
  }

  detailSelect(entry, index, spec) {
    const select = element("select", "field__control ge-source__detail");
    for (const value of spec.detail) select.append(new Option(t(`editor.sources.detail.${value}`), value));
    select.value = entry.detail ?? spec.detail[0];
    select.setAttribute("aria-label", t("editor.sources.detail_label", { label: this.sourceLabel(spec.key) }));
    select.addEventListener("change", () => {
      this.list = setOption(this.list, index, "detail", select.value);
      this.commit();
    });
    return select;
  }

  namesInput(entry, index, spec) {
    const area = element("textarea", "field__control ge-source__names");
    area.rows = 2;
    area.spellcheck = false;
    area.value = (entry.names ?? []).join("\n");
    area.placeholder = t("editor.sources.names_placeholder");
    area.setAttribute("aria-label", t("editor.sources.names_label", { label: this.sourceLabel(spec.key) }));
    area.title = t("editor.sources.names_help", { max: spec.names.max });
    area.addEventListener("input", () => {
      this.list = setOption(this.list, index, "names", parseNames(area.value));
    });
    this.typed(area, "multiline");
    return area;
  }

  addChosen() {
    const spec = specOf(this.specs, this.add.value);
    if (!spec || this.list.length >= this.max) return;
    this.list = addSource(this.list, spec);
    this.draw();
    this.live.textContent = t("editor.sources.added", { label: this.sourceLabel(spec.key), n: this.list.length });
    this.commit();
    this.rows.lastElementChild?.querySelector(".ge-source__grip")?.focus();
  }

  removeRow(index) {
    const label = this.sourceLabel(this.list[index].source);
    this.list = removeSource(this.list, index);
    this.draw();
    this.live.textContent = t("editor.sources.removed", { label });
    this.commit();
    this.add.focus();
  }

  /** A drag has moved the row in the document already, a key asks for the move; both change the list, which is drawn anew. */
  moveRow(from, to, by) {
    this.list = moveSource(this.list, from, to);
    this.draw();
    const grip = this.rows.children[to]?.querySelector(".ge-source__grip");
    if (by === "key") grip?.focus();
    this.live.textContent = t("editor.sources.moved", { label: this.sourceLabel(this.list[to].source), n: to + 1, total: this.list.length });
    this.commit();
  }
}

/** The fields of a Hand Over Tool (ADR-080): the shared list editor (components/schema-fields.js) as one setting with one value, the list.
 * A choice (add, remove, move, a type, "required") saves at once, a typed text when its field is left or confirmed; a list that does not
 * fit says why in plain words and is not sent (the rules are components/schema-fields-model.js, the server's the same). */
class FieldsControl extends SettingControl {
  static kind = "toggle"; // the rows bind their own events (a composite), not the wrapper
  static row = false;

  createInput(value) {
    const box = element("div", "ge-fields");
    box.dataset.focusKey = `setting-${this.setting.key}`;
    this.editor = new SchemaFields({
      fields: Array.isArray(value) ? value : [],
      types: this.setting.field_types ?? undefined,
      limits: this.setting.field_limits ?? undefined,
      max: this.setting.max_fields ?? undefined,
      label: this.setting.label,
      extra: this.setting.field_extra ?? null,
      showRequired: this.setting.field_required !== false,
      wide: this.setting.field_extra != null, // the Trigger, Output and Complete windows: one row per field (the Hand Over Tool has no extra and stays compact)
      // the value of an output may name nodes and inputs: the reference list helps there too
      decorate: (input, kind) => {
        if (kind === "value" && this.source) suggestReferences(input, this.source, { allowSecrets: false });
      },
      onInput: () => this.markDirty(),
      onSettle: () => this.commit(),
    });
    box.append(this.editor.element);
    return box;
  }

  labelTarget() {
    return this.editor.element.querySelector(".sf__add");
  }

  read() {
    return JSON.stringify(this.editor.value());
  }

  parse(raw) {
    const problem = this.editor.problem();
    if (problem) throw new Error(problem);
    const saved = Array.isArray(this.saved) ? this.saved : null;
    return saved && JSON.stringify(saved) === raw ? saved : JSON.parse(raw); // the stored list itself when nothing changed
  }

  isDirty() {
    return this.read() !== this.baseline;
  }
}

/** What an action or pipeline node gives to the inputs of what it runs (ADR-083): one row per declared input of its definition, each a text
 * (or a reference to a card field or to the outputs of an earlier node) with the reference list. A row left empty uses the default of the
 * input; a required one without a value fails the run, and the publish check says so. The rows come from the definition (`source.inputsOf`),
 * the stored value is `{name: text}` with only the filled rows. */
class MappingControl extends SettingControl {
  static kind = "toggle"; // the rows bind their own events (a composite), not the wrapper
  static row = false;

  createInput(value) {
    const box = element("div", "ge-mapping");
    box.dataset.focusKey = `setting-${this.setting.key}`;
    const given = value && typeof value === "object" ? value : {};
    this.rows = new Map();
    const inputs = this.source?.inputsOf?.(this.source.node) ?? [];
    for (const spec of inputs) {
      const row = element("div", "ge-mapping__row");
      const label = element("label", "ge-mapping__label");
      label.textContent = spec.name;
      if (spec.required) label.append(element("span", "ge-mapping__required", ` ${t("editor.setting_controls.mapping_required")}`));
      const input = element("input", "field__control ge-mapping__input");
      input.type = "text";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.maxLength = 2000;
      input.value = given[spec.name] ?? "";
      input.placeholder = spec.default ? `${t("editor.setting_controls.mapping_default")}: ${spec.default}` : spec.description || t(`components.schema_fields.type.${spec.type}`);
      input.id = `mapping-${this.setting.key}-${spec.name}`;
      label.htmlFor = input.id;
      input.addEventListener("input", () => this.markDirty());
      input.addEventListener("change", () => this.commit());
      if (this.source) suggestReferences(input, this.source, { allowSecrets: false });
      row.append(label, input);
      box.append(row);
      this.rows.set(spec.name, input);
    }
    return box;
  }

  labelTarget() {
    return this.rows.values().next().value ?? null;
  }

  read() {
    return JSON.stringify(this.value());
  }

  /** The filled rows as the server stores them. */
  value() {
    const out = {};
    for (const [name, input] of this.rows) if (input.value.trim() !== "") out[name] = input.value;
    return out;
  }

  parse() {
    return this.value();
  }

  isDirty() {
    return this.read() !== this.baseline;
  }
}

const CONTROLS = {
  mapping: MappingControl,
  credential: CredentialControl,
  integer: IntegerControl,
  number: NumberControl,
  switch: SwitchControl,
  text: TextControl,
  lines: LinesControl,
  code: CodeControl,
  select: SelectControl,
  retry: RetryControl,
  size: SizeControl,
  sources: SourcesControl,
  fields: FieldsControl,
};

/** The control for a setting; a type this editor does not know is shown as plain text. */
export function createControl(setting, value, save, suggest = null, options = {}) {
  return new (CONTROLS[setting.type] ?? TextControl)(setting, value, save, suggest, options);
}
