/* An on/off switch with its state written in it (`.ge-switch`, role=switch). One implementation for every
 * page: the agent editor, the options panel, the inspector can use it the same way. */

/** The markup of a switch; `labelledBy` is the id of its visible label. */
export function createSwitch(labelledBy) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ge-switch";
  button.setAttribute("role", "switch");
  button.setAttribute("aria-checked", "false");
  if (labelledBy) button.setAttribute("aria-labelledby", labelledBy);
  const state = document.createElement("span");
  state.className = "ge-switch__state";
  const thumb = document.createElement("span");
  thumb.className = "ge-switch__thumb";
  button.append(state, thumb);
  return button;
}

export class Switch {
  /**
   * @param {HTMLButtonElement} button a `.ge-switch`
   * @param {{onChange?: (on: boolean) => void}} [options] called when the user flips it (not for `on = ...`)
   */
  constructor(button, { onChange } = {}) {
    this.button = button;
    this.on = button.getAttribute("aria-checked") === "true";
    button.addEventListener("click", () => {
      this.on = !this.on;
      onChange?.(this.on);
    });
  }

  get on() {
    return this.button.getAttribute("aria-checked") === "true";
  }

  set on(value) {
    this.button.setAttribute("aria-checked", String(Boolean(value)));
    const state = this.button.querySelector(".ge-switch__state");
    if (state) state.textContent = value ? "On" : "Off";
  }
}
