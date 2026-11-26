/* A checkbox in the look of the catalog (`.ck`, ADR-083 addendum): a rounded square with a soft border, filled in the accent colour with a white
 * tick when checked. The native `<input type="checkbox" class="check">` stays inside the label (the look is its `input.check` rule, the one
 * look of every checkbox of the application), so the keyboard (Space), the screen readers, forms and the `change` event work as they do for a
 * native box. `Checkbox` is the base; a specialisation names its variant and gets its colours from a modifier class, the way `switch.js` has its
 * red `ge-switch--danger`:
 *
 *   const box = new Checkbox({ label: "Required", checked: true, onChange: (on) => ... });   parent.append(box.element);
 *   box.input   box.checked = false   box.labelHidden = true   (the text stays for assistive technology)
 *   class DangerCheckbox extends Checkbox { static variant = "danger"; }
 */

export class Checkbox {
  /** The modifier of a specialisation (`ck--danger`); empty for the base. */
  static variant = "";

  /**
   * @param {{label?: string, checked?: boolean, disabled?: boolean, labelHidden?: boolean, name?: string, ariaLabel?: string,
   *   className?: string, inputClass?: string, onChange?: (checked: boolean) => void}} [options]
   *   `labelHidden`: the text is there for assistive technology only (the column head says it); `className`/`inputClass`: extra classes
   *   of the label and of the native input (a stylesheet or a test finds the box by them)
   */
  constructor({ label = "", checked = false, disabled = false, labelHidden = false, name = "", ariaLabel = "", className = "", inputClass = "", onChange = null } = {}) {
    const variant = this.constructor.variant;
    this.element = document.createElement("label");
    this.element.className = ["ck", variant ? `ck--${variant}` : "", className].filter(Boolean).join(" ");
    this.input = document.createElement("input");
    this.input.type = "checkbox";
    this.input.className = ["check", "ck__input", inputClass].filter(Boolean).join(" ");
    if (name) this.input.name = name;
    if (ariaLabel) this.input.setAttribute("aria-label", ariaLabel);
    this.input.checked = Boolean(checked);
    this.input.disabled = Boolean(disabled);
    this.text = document.createElement("span");
    this.text.className = "ck__text";
    this.text.textContent = label;
    this.element.append(this.input, this.text);
    this.labelHidden = labelHidden;
    if (onChange) this.input.addEventListener("change", () => onChange(this.input.checked));
  }

  get checked() {
    return this.input.checked;
  }

  set checked(value) {
    this.input.checked = Boolean(value);
  }

  get disabled() {
    return this.input.disabled;
  }

  set disabled(value) {
    this.input.disabled = Boolean(value);
  }

  set labelHidden(value) {
    this.text.classList.toggle("visually-hidden", Boolean(value));
    this.element.classList.toggle("ck--bare", Boolean(value));
  }
}

/** The red specialisation: for a box that chooses something destructive. */
export class DangerCheckbox extends Checkbox {
  static variant = "danger";
}
