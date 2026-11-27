/* A length of time: a number and a unit (ms, sec, min), kept as milliseconds (duration-model.js). One component for every duration
 * the interface asks for, so nobody converts by hand (ADR-074). The markup is `.duration-input`: the number grows, the unit has the
 * width of its longest text.
 *
 * It reports a decision, not a keystroke: `onCommit()` when the number is left or Enter is pressed and when the unit is changed
 * (the persistence rule of the catalog); reading `milliseconds` never throws (`NaN` while the number is empty or not a number). */
import { bindPersist } from "../editor/persist-policy.js";
import { t } from "../i18n.js";
import { DURATION_UNITS, splitDuration, toMilliseconds } from "./duration-model.js";

const UNIT_TEXT = {
  ms: () => t("components.duration_input.ms"),
  sec: () => t("components.duration_input.sec"),
  min: () => t("components.duration_input.min"),
};

export class DurationInput {
  /**
   * @param {{milliseconds?: number, min?: number, focusKey?: string, onCommit?: () => void, onInput?: () => void}} [options]
   *   `min`: the lowest number (in the unit shown); `focusKey` names the number and, with `-unit`, the unit for the focus memory
   */
  constructor({ milliseconds = 0, min = 0, focusKey = "", onCommit = () => {}, onInput = () => {} } = {}) {
    this.element = document.createElement("div");
    this.element.className = "duration-input";
    this.number = document.createElement("input");
    this.number.type = "number";
    this.number.className = "field__control";
    this.number.min = String(min);
    this.number.step = "any";
    this.unit = document.createElement("select");
    this.unit.className = "field__control duration-input__unit";
    for (const { unit } of DURATION_UNITS) this.unit.append(new Option(UNIT_TEXT[unit](), unit));
    if (focusKey) {
      this.number.dataset.focusKey = focusKey;
      this.unit.dataset.focusKey = `${focusKey}-unit`;
    }
    this.set(milliseconds);
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

  /** The value in milliseconds; `NaN` while the number is empty or no number. */
  get milliseconds() {
    return toMilliseconds(this.number.value, this.unit.value);
  }

  /** Show milliseconds as the largest unit that divides them evenly. */
  set(milliseconds) {
    const { value, unit } = splitDuration(milliseconds);
    this.number.value = String(value);
    this.unit.value = unit;
    this.#typed = false;
  }

  /** Shown text of the number and the unit, for a message. */
  get text() {
    return `${this.number.value} ${this.unit.value}`;
  }
}
