/* A card of settings that override defaults (ADR-046): a default always applies; a setting is a field only once
 * it is added ("Add setting", a menu of the ones not added yet, each with its default) and goes again with its
 * bin, which brings the default back. Removing is "not set": the group reads a missing setting as null. The settings are declared (key, label, how its control is made, read
 * and written); the group knows nothing about what they mean.
 *
 * Markup: the root holds [data-settings-add] (the button), [data-settings-fields] (where the fields go) and an
 * optional [data-settings-empty] (shown while nothing is added). */
import { ActionMenu } from "./action-menu.js";
import { icon } from "./icons.js";
import { t } from "../i18n.js";

let groupCount = 0;

/** A number field with its bounds; `fallback` is its default, shown grey while the field is empty (read: a
 * number, null when empty, NaN when it is none). */
export function numberSetting(key, label, { min, max, step = 1, hint = "", fallback = "", unit = "" } = {}) {
  return {
    key,
    label,
    hint,
    fallback: fallback === "" ? "" : `${fallback}${unit}`,
    create() {
      const input = document.createElement("input");
      input.className = "field__control";
      input.type = "number";
      Object.assign(input, { min, max, step, placeholder: String(fallback) });
      return input;
    },
    read: (input) => (input.value.trim() === "" ? null : Number(input.value)),
    write: (input, value) => (input.value = value ?? ""),
  };
}

export class SettingsGroup {
  /**
   * @param {HTMLElement} root
   * @param {{key: string, label: string, hint?: string, fallback?: string, create: () => HTMLElement, read: (el: HTMLElement) => any, write: (el: HTMLElement, value: any) => void}[]} settings
   *   `fallback` is the default in words ("600 s", "the default provider"): in the menu and on the bin
   * @param {{onChange?: () => void, onAdd?: (key: string, el: HTMLElement) => void}} [hooks] onChange: added or removed;
   *   onAdd: a control was just made (fill a select, wire it)
   */
  constructor(root, settings, { onChange = () => {}, onAdd = () => {} } = {}) {
    this.root = root;
    this.settings = settings;
    this.onChange = onChange;
    this.onAdd = onAdd;
    this.id = `settings-${(groupCount += 1)}`;
    this.fields = root.querySelector("[data-settings-fields]");
    this.empty = root.querySelector("[data-settings-empty]");
    this.addButton = root.querySelector("[data-settings-add]");
    /** @type {Map<string, {row: HTMLElement, control: HTMLElement}>} */
    this.shown = new Map();
    this.menu = new ActionMenu();
    this.addButton.addEventListener("click", () => this.#openMenu());
    this.#update();
  }

  /** Show the settings that have a value (not null) and write them; the others are not added. */
  load(values) {
    for (const key of [...this.shown.keys()]) this.#drop(key);
    for (const setting of this.settings) {
      const value = values?.[setting.key];
      if (value !== null && value !== undefined) this.setting(setting.key).write(this.#show(setting).control, value);
    }
    this.#update();
  }

  /** Every setting of the group: its value, or null when it is not added (not set). */
  read() {
    return Object.fromEntries(this.settings.map((s) => [s.key, this.shown.has(s.key) ? s.read(this.shown.get(s.key).control) : null]));
  }

  has(key) {
    return this.shown.has(key);
  }

  control(key) {
    return this.shown.get(key)?.control ?? null;
  }

  setting(key) {
    return this.settings.find((s) => s.key === key);
  }

  /** Add a setting the user chose: shown, focused, a change of the caller's data. */
  add(key) {
    if (this.shown.has(key)) return;
    const { control } = this.#show(this.setting(key));
    this.#update();
    control.focus();
    this.onChange();
  }

  remove(key) {
    if (!this.shown.has(key)) return;
    this.#drop(key);
    this.#update();
    this.addButton.focus();
    this.onChange();
  }

  #openMenu() {
    const items = this.settings
      .filter((s) => !this.shown.has(s.key))
      .map((s) => ({ label: s.fallback ? t("components.settings_group.label_default_fallback", { label: s.label, fallback: s.fallback }) : s.label, icon: "plus", onSelect: () => this.add(s.key) }));
    if (items.length) this.menu.toggle(this.addButton, items, "Add setting");
  }

  #show(setting) {
    const row = document.createElement("div");
    row.className = "setting";
    row.dataset.setting = setting.key;
    const control = setting.create();
    control.id = `${this.id}-${setting.key}`;
    control.dataset.field = setting.key;
    const label = document.createElement("label");
    label.className = "setting__label";
    label.htmlFor = control.id;
    label.textContent = setting.label;
    if (setting.hint) {
      label.title = setting.hint;
      control.title = setting.hint;
    }
    const bin = document.createElement("button");
    bin.type = "button";
    bin.className = "icon-button icon-button--sm is-danger setting__remove";
    bin.setAttribute("aria-label", t("components.settings_group.remove_label", { label: setting.label }));
    bin.title = setting.fallback ? t("components.settings_group.use_default_again_fallback", { fallback: setting.fallback }) : t("components.settings_group.remove_label", { label: setting.label });
    bin.append(icon("trash"));
    bin.addEventListener("click", () => this.remove(setting.key));
    row.append(label, control, bin);
    // keep the declared order, whatever order they are added in
    const after = this.settings.slice(this.settings.indexOf(setting) + 1).map((s) => this.shown.get(s.key)?.row).find(Boolean);
    this.fields.insertBefore(row, after ?? null);
    this.shown.set(setting.key, { row, control });
    this.onAdd(setting.key, control);
    return { row, control };
  }

  #drop(key) {
    this.shown.get(key).row.remove();
    this.shown.delete(key);
  }

  #update() {
    const left = this.settings.length - this.shown.size;
    this.addButton.disabled = left === 0;
    this.addButton.title = left === 0 ? t("components.settings_group.all_settings_added") : t("components.settings_group.add_setting");
    if (this.empty) this.empty.hidden = this.shown.size > 0;
  }
}
