/* A panel of optional areas, each with a name, an explanation (its tooltip) and a switch. It is closed when
 * the page opens and remembers nothing: opening or closing it changes no data. What a switch means is the
 * caller's (`onChange(key, on)`); the panel only shows and reports the states. */
import { Switch, createSwitch } from "./switch.js";

let panelCount = 0;

export class OptionsPanel {
  /**
   * @param {HTMLElement} root with a [data-options-toggle] button and a [data-options-body] element
   * @param {{key: string, label: string, help?: string}[]} options
   * @param {(key: string, on: boolean) => void} onChange called when the user flips a switch
   */
  constructor(root, options, onChange) {
    this.root = root;
    this.toggle = root.querySelector("[data-options-toggle]");
    this.body = root.querySelector("[data-options-body]");
    this.switches = new Map();
    const id = `options-${(panelCount += 1)}`;
    this.body.id ||= `${id}-body`;
    this.toggle.setAttribute("aria-controls", this.body.id);
    const list = document.createElement("ul");
    list.className = "options-panel__list";
    for (const option of options) {
      const row = document.createElement("li");
      row.className = "options-panel__row";
      row.dataset.option = option.key;
      const label = document.createElement("span");
      label.className = "options-panel__label";
      label.id = `${id}-${option.key}`;
      label.textContent = option.label;
      if (option.help) label.title = option.help;
      const button = createSwitch(label.id);
      if (option.help) button.title = option.help;
      this.switches.set(option.key, new Switch(button, { onChange: (on) => onChange(option.key, on) }));
      row.append(label, button);
      list.append(row);
    }
    this.body.replaceChildren(list);
    this.toggle.addEventListener("click", () => this.setOpen(!this.isOpen));
    this.setOpen(false);
  }

  get isOpen() {
    return this.root.dataset.state === "open";
  }

  setOpen(open) {
    this.root.dataset.state = open ? "open" : "closed";
    this.toggle.setAttribute("aria-expanded", String(open));
    this.body.hidden = !open;
  }

  /** The state of an option as the data says (does not call onChange). */
  set(key, on) {
    this.switches.get(key).on = on;
  }

  get(key) {
    return this.switches.get(key).on;
  }
}
