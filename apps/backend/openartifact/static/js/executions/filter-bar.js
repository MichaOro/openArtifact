/* The filter form: status and origin toggles, the pipeline and search fields, the time range, "Reset".
 * It reads and writes a Filters value; the page decides what a change means. Text fields are applied
 * after a short pause, the toggles at once. On a phone the form is a disclosure that starts closed. */
import { Filters } from "./filters.js";

const TYPING_MS = 300;
const WIDE = "(min-width: 48rem)";

export class FilterBar {
  /**
   * @param {HTMLFormElement} form
   * @param {(filters: Filters) => void} onChange
   */
  constructor(form, onChange) {
    this.form = form;
    this.onChange = onChange;
    this.filters = new Filters();
    this.timer = null;
    this.pipeline = form.elements.pipeline;
    this.q = form.elements.q;
    this.disclosure = form.querySelector("[data-filters-disclosure]");
    this.activeBadge = form.querySelector("[data-filters-active]");
    this.custom = form.querySelector("[data-custom]");
    this.resets = [...document.querySelectorAll("[data-reset]")];

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.#flush();
    });
    form.addEventListener("change", (event) => {
      if (event.target.type === "checkbox" || event.target.type === "radio") this.#emit(this.#read());
    });
    for (const input of [this.pipeline, this.q]) {
      input.addEventListener("input", () => {
        window.clearTimeout(this.timer);
        this.timer = window.setTimeout(() => this.#flush(), TYPING_MS);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") this.#flush();
      });
    }
    form.querySelector("[data-custom-clear]").addEventListener("click", () => this.#emit(this.filters.with({ since: "", until: "" })));
    for (const button of this.resets) button.addEventListener("click", () => this.#emit(new Filters({ pageSize: this.filters.pageSize })));

    // wide screens always show the filters; a phone starts with them closed
    const wide = window.matchMedia(WIDE);
    this.disclosure.open = wide.matches;
    wide.addEventListener("change", () => (this.disclosure.open = wide.matches || this.disclosure.open));
  }

  /** Show these filters in the controls (they came from the URL or from a counter). */
  setFilters(filters) {
    window.clearTimeout(this.timer);
    this.filters = filters;
    for (const box of this.form.querySelectorAll("input[name=status]")) box.checked = filters.status.includes(box.value);
    for (const box of this.form.querySelectorAll("input[name=started_by]")) box.checked = filters.startedBy.includes(box.value);
    if (document.activeElement !== this.pipeline) this.pipeline.value = filters.pipeline;
    if (document.activeElement !== this.q) this.q.value = filters.q;
    for (const radio of this.form.querySelectorAll("input[name=range]")) radio.checked = !filters.custom && (radio.value === "all" ? filters.range === "" : radio.value === filters.range);
    this.custom.hidden = !filters.custom;
    if (filters.custom) {
      const parts = [filters.since && `since ${new Date(filters.since).toLocaleString()}`, filters.until && `until ${new Date(filters.until).toLocaleString()}`];
      this.custom.querySelector("[data-custom-text]").textContent = `Custom range: ${parts.filter(Boolean).join(" ")}`;
    }
    const count = filters.activeCount;
    this.activeBadge.textContent = count ? `${count} active` : "";
    for (const button of this.resets) if (!button.closest("[data-empty-match]")) button.hidden = !filters.active;
  }

  #read() {
    const checked = (name) => [...this.form.querySelectorAll(`input[name=${name}]:checked`)].map((box) => box.value);
    const picked = this.form.querySelector("input[name=range]:checked")?.value; // "all" is no preset
    const range = picked === "all" ? "" : (picked ?? "");
    const keepsCustom = this.filters.custom && picked === undefined;
    return this.filters.with({
      status: checked("status"),
      startedBy: checked("started_by"),
      pipeline: this.pipeline.value,
      q: this.q.value,
      range,
      since: keepsCustom ? this.filters.since : "",
      until: keepsCustom ? this.filters.until : "",
    });
  }

  #flush() {
    window.clearTimeout(this.timer);
    this.#emit(this.#read());
  }

  #emit(filters) {
    if (filters.toSearch() === this.filters.toSearch()) return;
    this.setFilters(filters);
    this.onChange(filters);
  }
}
