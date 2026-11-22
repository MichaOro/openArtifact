/* The type and parameters part of the artifact dialog: the Type select, the typed controls of the chosen
 * type (text input, number input, switch, select) with required markers and defaults, the read-only list
 * for the view, field errors, and the inline confirmation when a change of type would drop values.
 * What a control means and what a change drops is in parameters.js. */
import { displayValue, droppedBy, initialValue, parameterOf } from "./parameters.js";

function element(tag, className = "", text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export class ParameterForm {
  /** @param {HTMLElement} root the artifact dialog */
  constructor(root) {
    this.typeField = root.querySelector("[data-type-field]");
    this.select = this.typeField.querySelector("select");
    this.formParams = root.querySelector("[data-form-params]");
    this.viewParams = root.querySelector("[data-view-params]");
    this.confirmBox = root.querySelector("[data-type-confirm]");
    this.confirmText = root.querySelector("[data-type-confirm-text]");
    this.lockedNote = root.querySelector("[data-params-locked]");
    /** @type {Map<string, {id: string, name: string, fields: object[]}>} */
    this.types = new Map();
    this.typeId = null;
    this.controls = new Map();
    this.locked = false;
    this.baseline = "";
    this.stored = {};
    /** The type asked for while the confirmation is open. */
    this.pending = null;
    this.select.addEventListener("change", () => this.#chosen(this.select.value || null));
    root.querySelector("[data-type-keep]").addEventListener("click", () => this.#closeConfirm(true));
    root.querySelector("[data-type-switch]").addEventListener("click", () => {
      const next = this.pending;
      this.#closeConfirm(false);
      this.#switchTo(next);
    });
  }

  /** The types the artifact may have; without any, neither the select nor any parameter shows. */
  setTypes(list) {
    this.types = new Map(list.map((type) => [type.id, type]));
    this.#fillSelect();
    this.typeField.hidden = this.types.size === 0 && this.typeId === null;
    if (this.typeId && this.type && this.controls.size === 0) this.show(this.typeId, this.stored); // the types came late
  }

  #fillSelect() {
    const options = [["", "No type"], ...[...this.types.values()].map((t) => [t.id, t.name])];
    if (this.typeId && !this.types.has(this.typeId)) options.push([this.typeId, "Unknown type"]);
    this.select.replaceChildren(
      ...options.map(([value, text]) => {
        const option = element("option", "", text);
        option.value = value;
        return option;
      }),
    );
    this.select.value = this.typeId ?? "";
  }

  get type() {
    return this.types.get(this.typeId) ?? null;
  }

  /** Show the form for an artifact's type with its stored values (none: a new artifact, the defaults). */
  show(typeId, stored = {}) {
    this.#closeConfirm(false);
    this.typeId = typeId;
    this.stored = stored;
    this.#fillSelect();
    this.typeField.hidden = this.types.size === 0 && typeId === null;
    this.#renderControls(stored);
    this.baseline = JSON.stringify(this.collect());
  }

  /** No type, no values (the create form after a save). */
  reset() {
    this.show(null);
  }

  /** What the form holds: the type and every parameter of it (null where nothing is set). */
  collect() {
    const parameters = {};
    for (const [name, { field, control }] of this.controls) {
      parameters[name] = parameterOf(field, field.kind === "boolean" ? control.checked : control.value);
    }
    return { type_id: this.typeId, parameters };
  }

  /** Whether the type or a value differs from what the form was shown with. */
  changed() {
    return JSON.stringify(this.collect()) !== this.baseline;
  }

  /** Whether the type differs from `typeId`. */
  typeChanged(typeId) {
    return (this.typeId ?? null) !== (typeId ?? null);
  }

  snapshot() {
    return this.collect();
  }

  restore(snapshot) {
    this.show(snapshot.type_id, snapshot.parameters);
  }

  setLocked(locked) {
    this.locked = locked;
    this.select.disabled = locked;
    for (const { control } of this.controls.values()) control.disabled = locked;
    this.lockedNote.hidden = !locked || !this.type;
  }

  /** The read-only list under the body. */
  renderView(typeId, parameters = {}) {
    const type = this.types.get(typeId);
    this.viewParams.replaceChildren();
    this.viewParams.hidden = !type;
    if (!type) return;
    const row = (label, value) => {
      const item = element("div", "param");
      item.append(element("span", "field__label", label));
      const shown = element("div", `param__value${value ? "" : " param__value--empty"}`, value || "Not set");
      item.append(shown);
      return item;
    };
    this.viewParams.append(row("Type", type.name));
    for (const field of type.fields) {
      const value = parameters[field.name];
      this.viewParams.append(row(field.label, displayValue(field, value)));
    }
  }

  /** Show the server's messages at their parameters; returns the names that have no control here. */
  showErrors(byField) {
    this.clearErrors();
    const missing = [];
    let first = null;
    for (const [name, message] of byField) {
      const entry = this.controls.get(name);
      if (!entry) {
        missing.push(name);
        continue;
      }
      entry.error.textContent = message;
      entry.error.hidden = false;
      entry.control.setAttribute("aria-invalid", "true");
      first ??= entry.control;
    }
    first?.focus();
    return missing;
  }

  clearErrors() {
    for (const { control, error } of this.controls.values()) {
      error.textContent = "";
      error.hidden = true;
      control.removeAttribute("aria-invalid");
    }
  }

  // ── the controls ───────────────────────────────────────────────────

  #renderControls(stored) {
    this.controls = new Map();
    const type = this.type;
    this.formParams.replaceChildren();
    this.formParams.hidden = !type;
    this.lockedNote.hidden = !this.locked || !type;
    for (const field of type?.fields ?? []) {
      const { wrapper, control, error } = this.#control(field, initialValue(field, stored[field.name]));
      control.disabled = this.locked;
      this.controls.set(field.name, { field, control, error });
      this.formParams.append(wrapper);
    }
    this.select.disabled = this.locked;
  }

  #control(field, value) {
    const id = `param-${field.name}`;
    const wrapper = element("div", "field param");
    const label = element("label", "field__label", field.label);
    label.htmlFor = id;
    if (field.required) {
      label.append(" ", element("span", "field__required", "*"));
      label.lastChild.setAttribute("aria-hidden", "true");
    }
    const error = element("p", "field__error");
    error.id = `${id}-error`;
    error.setAttribute("role", "alert");
    error.hidden = true;
    let control;
    if (field.kind === "choice") {
      control = element("select", "field__control");
      const empty = element("option", "", field.required ? "Choose…" : "Not set");
      empty.value = "";
      control.append(empty);
      for (const option of field.options) {
        const item = element("option", "", option);
        item.value = option;
        control.append(item);
      }
      control.value = field.options.includes(value) ? value : "";
    } else if (field.kind === "boolean") {
      control = element("input");
      control.type = "checkbox";
      control.setAttribute("role", "switch");
      control.checked = value === true;
    } else if (field.kind === "number") {
      control = element("input", "field__control");
      control.type = "number";
      control.step = field.integer_only ? "1" : "any";
      if (field.min_value !== null && field.min_value !== undefined) control.min = String(field.min_value);
      if (field.max_value !== null && field.max_value !== undefined) control.max = String(field.max_value);
      control.value = value === "" ? "" : String(value);
    } else {
      control = element("input", "field__control");
      control.type = "text";
      control.maxLength = field.max_length ?? 200;
      control.autocomplete = "off";
      control.value = String(value);
    }
    control.id = id;
    control.name = `param:${field.name}`;
    control.setAttribute("aria-describedby", error.id);
    if (field.required) control.setAttribute("aria-required", "true");
    const clear = () => {
      error.textContent = "";
      error.hidden = true;
      control.removeAttribute("aria-invalid");
    };
    control.addEventListener("input", clear);
    control.addEventListener("change", clear);
    if (field.kind === "boolean") {
      const state = element("label", "param-switch");
      const text = element("span", "", control.checked ? "Yes" : "No");
      text.setAttribute("aria-hidden", "true");
      control.addEventListener("change", () => (text.textContent = control.checked ? "Yes" : "No"));
      state.append(control, text);
      wrapper.append(label, state, error);
    } else {
      wrapper.append(label, control, error);
    }
    return { wrapper, control, error };
  }

  // ── changing the type ───────────────────────────────────────────────

  #chosen(next) {
    const current = this.collect().parameters;
    const dropped = droppedBy(this.type, this.types.get(next) ?? null, current);
    if (dropped.length === 0) {
      this.#switchTo(next);
      return;
    }
    this.select.value = this.typeId ?? ""; // not yet: the user decides below
    this.pending = next;
    this.confirmText.textContent = `Changing the type drops the values of ${dropped.join(", ")}.`;
    this.confirmBox.hidden = false;
    this.confirmBox.querySelector("[data-type-switch]").focus();
  }

  #closeConfirm(refocus) {
    this.confirmBox.hidden = true;
    this.pending = null;
    if (refocus) this.select.focus();
  }

  /** Switch the type; values of parameters the new type has too are carried over. */
  #switchTo(next) {
    const carried = this.collect().parameters;
    this.typeId = next;
    this.select.value = next ?? "";
    const old = this.baseline;
    this.#renderControls(carried);
    this.baseline = old; // a type change is a change
  }
}
