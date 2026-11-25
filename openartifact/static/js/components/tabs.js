/* A tab list following the ARIA tabs pattern: role=tablist / tab / tabpanel, aria-selected, roving
 * tabindex, Left/Right/Home/End, automatic activation. The markup carries the tabs
 * ([role=tab][data-tab=name][aria-controls=panel id]); this class only switches them. A tab can be hidden
 * (`setVisible`): it and its panel are gone, a `disabled` tab (a place held for what is not built) cannot be chosen and the keys skip it, the keys skip it, and if it was selected the first visible tab is. */

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
    const chosen = this.tabs.find((tab) => tab.dataset.tab === name && !tab.hidden && !tab.disabled);
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

  /** Show or hide a tab with its panel (an optional area switched on or off). */
  setVisible(name, visible) {
    const tab = this.tabs.find((t) => t.dataset.tab === name);
    if (!tab) return;
    tab.hidden = !visible;
    if (!visible) {
      document.getElementById(tab.getAttribute("aria-controls")).hidden = true;
      if (this.selected === name) this.select(this.tabs.find((t) => !t.hidden).dataset.tab);
    }
  }

  isVisible(name) {
    return this.tabs.some((t) => t.dataset.tab === name && !t.hidden);
  }

  #key(event) {
    const shown = this.tabs.filter((tab) => !tab.hidden && !tab.disabled); // a greyed tab is skipped
    const index = shown.findIndex((tab) => tab === document.activeElement);
    if (index < 0) return;
    const last = shown.length - 1;
    const next = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    this.select(shown[next].dataset.tab, { focus: true });
  }
}
