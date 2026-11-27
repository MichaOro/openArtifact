/* A size: a number and a unit (B, KiB, MiB), kept as bytes (size-model.js). The twin of the duration input (duration-input.js): one
 * component for every size the interface asks for, so nobody converts by hand. The markup is `.size-input` (styled like
 * `.duration-input`: the number grows, the unit has the width of its longest text).
 *
 * It reports a decision, not a keystroke: `onCommit()` when the number is left or Enter is pressed and when the unit is changed (the
 * persistence rule of the catalog); reading `bytes` never throws (`NaN` while the number is empty or not a number). */
import { bindPersist } from "../editor/persist-policy.js";
import { SIZE_UNITS, splitSize, toBytes } from "./size-model.js";

export class SizeInput {
  /**
   * @param {{bytes?: number, min?: number, focusKey?: string, onCommit?: () => void, onInput?: () => void}} [options]
   *   `focusKey` names the number and, with `-unit`, the unit for the focus memory
   */
  constructor({ bytes = 0, min = 0, focusKey = "", onCommit = () => {}, onInput = () => {} } = {}) {
    this.element = document.createElement("div");
    this.element.className = "size-input";
    this.number = document.createElement("input");
    this.number.type = "number";
    this.number.className = "field__control";
    this.number.min = String(min);
    this.number.step = "any";
    this.unit = document.createElement("select");
    this.unit.className = "field__control size-input__unit";
    for (const { unit } of SIZE_UNITS) this.unit.append(new Option(unit, unit));
    if (focusKey) {
      this.number.dataset.focusKey = focusKey;
      this.unit.dataset.focusKey = `${focusKey}-unit`;
    }
    this.set(bytes);
    bindPersist(this.number, "text", (event) => {
      if (event.type === "focusout" && !this.#typed) return; // leaving a number nobody changed decides nothing
      this.#typed = false;
      onCommit();
    });
    this.number.addEventListener("input", () => {
      this.#typed = true;
      onInput();
    });
    bindPersist(this.unit, "choice", () => onCommit());
    this.unit.addEventListener("change", onInput);
    this.element.append(this.number, this.unit);
  }

  #typed = false;

  /** The value in bytes; `NaN` while the number is empty or no number. */
  get bytes() {
    return toBytes(this.number.value, this.unit.value);
  }

  /** Show bytes as the largest unit that divides them evenly. */
  set(bytes) {
    const { value, unit } = splitSize(bytes);
    this.number.value = String(value);
    this.unit.value = unit;
    this.#typed = false;
  }
}
