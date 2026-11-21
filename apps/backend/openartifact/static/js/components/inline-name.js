/* A name that is edited in place: click it (or press Enter on it) to get a text field with a check
 * and a cross; Enter or the check saves, Escape or the cross discards. */

const ICONS = { check: "M20 6 9 17l-5-5", cross: "M18 6 6 18M6 6l12 12" };

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

export class InlineName {
  /**
   * @param {HTMLElement} element shows the name; becomes the editor while editing
   * @param {{label: string, onCommit: (name: string) => void}} options label: what the name is called, for assistive technology
   */
  constructor(element, { label, onCommit, maxLength = 255 }) {
    this.element = element;
    this.onCommit = onCommit;
    this.maxLength = maxLength;
    this.text = element.textContent;
    element.classList.add("inline-name");
    element.tabIndex = 0;
    element.setAttribute("role", "button");
    element.setAttribute("aria-label", `${label}: ${this.text}. Click to rename`);
    this.label = label;
    element.addEventListener("click", () => this.#edit());
    element.addEventListener("keydown", (event) => {
      if (event.target === element && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        this.#edit();
      }
    });
  }

  /** Show another name (after a rename that happened elsewhere). */
  setText(text) {
    this.text = text;
    if (!this.editing) this.#show();
  }

  #show() {
    this.editing = false;
    this.element.replaceChildren(document.createTextNode(this.text));
    this.element.classList.remove("inline-name--editing");
    this.element.tabIndex = 0;
    this.element.setAttribute("role", "button");
    this.element.setAttribute("aria-label", `${this.label}: ${this.text}. Click to rename`);
  }

  #edit() {
    if (this.editing) return;
    this.editing = true;
    const input = document.createElement("input");
    input.className = "inline-name__input";
    input.type = "text";
    input.maxLength = this.maxLength;
    input.value = this.text;
    input.autocomplete = "off";
    input.setAttribute("aria-label", this.label);
    const button = (name, label, onClick) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = `icon-button icon-button--sm inline-name__${name}`;
      el.setAttribute("aria-label", label);
      el.title = label;
      el.append(icon(name));
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        onClick();
      });
      return el;
    };
    const commit = () => {
      const name = input.value.trim();
      this.#show();
      if (name && name !== this.text) this.onCommit(name);
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        commit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        this.#show();
        this.element.focus();
      }
    });
    this.element.classList.add("inline-name--editing");
    this.element.removeAttribute("role");
    this.element.removeAttribute("tabindex");
    this.element.removeAttribute("aria-label");
    this.element.replaceChildren(input, button("check", "Save name", commit), button("cross", "Discard", () => this.#show()));
    input.focus();
    input.select();
  }
}
