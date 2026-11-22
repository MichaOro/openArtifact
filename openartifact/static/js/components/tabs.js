/* A tab list following the ARIA tabs pattern: role=tablist / tab / tabpanel, aria-selected, roving
 * tabindex, Left/Right/Home/End, automatic activation. The markup carries the tabs
 * ([role=tab][data-tab=name][aria-controls=panel id]); this class only switches them. */

export class Tabs {
  /**
   * @param {HTMLElement} list the element with role=tablist
   * @param {(name: string) => void} [onChange] called when the user switched tabs (not for select(..., {notify: false}))
   */
  constructor(list, onChange = () => {}) {
    this.list = list;
    this.onChange = onChange;
    this.tabs = [...list.querySelectorAll('[role="tab"]')];
    this.selected = this.tabs.find((tab) => tab.getAttribute("aria-selected") === "true")?.dataset.tab ?? this.tabs[0].dataset.tab;
    for (const tab of this.tabs) tab.addEventListener("click", () => this.select(tab.dataset.tab));
    list.addEventListener("keydown", (event) => this.#key(event));
    this.select(this.selected, { notify: false });
  }

  /** Show the tab and its panel; `focus` moves the focus to the tab. */
  select(name, { notify = true, focus = false } = {}) {
    const chosen = this.tabs.find((tab) => tab.dataset.tab === name);
    if (!chosen) return;
    for (const tab of this.tabs) {
      const on = tab === chosen;
      tab.setAttribute("aria-selected", String(on));
      tab.tabIndex = on ? 0 : -1;
      document.getElementById(tab.getAttribute("aria-controls")).hidden = !on;
    }
    if (focus) chosen.focus();
    const changed = this.selected !== name;
    this.selected = name;
    if (notify && changed) this.onChange(name);
  }

  #key(event) {
    const index = this.tabs.findIndex((tab) => tab === document.activeElement);
    if (index < 0) return;
    const last = this.tabs.length - 1;
    const next = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    this.select(this.tabs[next].dataset.tab, { focus: true });
  }
}
