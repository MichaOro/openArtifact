/* The frame of a management page (ADR-069): the list of definitions (pipelines, actions, agents, guards) as cards or as rows with a
 * toolbar, and a detail panel with tabs on its right. ONE component for the four pages, so that they behave alike:
 *
 *   - a click selects an entry and shows its details; a double click opens it in its editor; the pencil opens it too; the bin deletes
 *     it (the page asks first); the keys: arrows select, Home and End, Enter opens, Delete deletes;
 *   - the toolbar: row one: search, the order, a filter by tag (optional; with tabs it moves to row two), "Per page" and cards or list; row two
 *     (only with tabs): the tabs and the filter, so that search and order do not move when the tabs are clicked through; below it the page buttons;
 *   - on a narrow screen the panel is a sheet that rises from the bottom.
 *
 *   const page = new ManagementPage(document.querySelector("[data-management]"), {
 *     name: "actions", label: "Actions", items, itemKey: (item) => item.id,
 *     tabs: [{key: "pipeline", label, icon, match: (item) => item.purpose === "pipeline"}],      // optional
 *     search: (item) => `${item.name} ${item.description}`, tagsOf: (item) => item.tags,        // both optional
 *     sorts: [{key: "name", label: "Name (A-Z)", compare: (a, b) => a.name.localeCompare(b.name)}],
 *     card: (item, view) => element,                    // the content of a card ("cards") or a row ("list")
 *     panel: { icon: (item) => "action", title: (item) => item.name, chips: (item) => [element],
 *              tabs: (item) => [{key, label, disabled, render: (body, item) => void}] },
 *     onOpen, onEdit, onDelete,                         // each gets the item
 *     deleteBlocked: (item) => "why it cannot be deleted" | null,   // optional: the bin is then disabled and says why
 *     readOnly: true,                                   // optional: no pencil and no bin on the entries (the archive only reads)
 *     onBlocked: (item, reason) => void,                // optional: called instead of onDelete when the bin of such an entry is clicked
 *   });
 *   page.setItems(items);  page.select(key);  page.refreshPanel();
 *
 * What the entries are and what the panel says is the page's; how they are laid out, selected and moved through is this component's. */
import { ActionMenu } from "./action-menu.js";
import { icon } from "./icons.js";
import { MINIMUM, baseOf, choices, firstOf, fit, pageOf, sizeOf, stepOf, usableStep } from "./page-size.js";
import { Tabs } from "./tabs.js";
import { readJson, writeJson } from "../storage.js";
import { t } from "../i18n.js";

const menu = new ActionMenu();
let uid = 0;

export function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

/** A chip: a small label with an optional icon (`tone`: "guard" for the chip of a guard action). */
/**
 * The content of a card, the same on all four pages (a fixed size, ADR-069 addendum): the title on top (up to two lines, then "…",
 * and never under the pencil and the bin), a short text in the middle (up to two lines, only when there is one), and at the bottom the
 * chips (one row), one line of additional facts and the date on the last line, flush to the bottom edge. In rows ("list") the same parts stand in one line.
 * @param {{title: string, text?: string|null, textTitle?: string, chips?: HTMLElement[], facts?: (HTMLElement|string)[], date?: HTMLElement|string|null}} parts
 */
export function cardBody({ title, text = null, textTitle = "", chips = [], facts = [], date = null }) {
  const box = make("div", "mg-card__body");
  const name = make("h3", "mg-card__name", title);
  name.title = title;
  box.append(name);
  if (text) {
    const middle = make("p", "mg-card__text", text);
    if (textTitle) middle.title = textTitle;
    box.append(middle);
  }
  const foot = make("div", "mg-card__foot");
  const row = make("div", "mg-card__chips");
  row.append(...chips);
  const line = make("p", "mg-card__facts");
  line.append(...facts);
  foot.append(row, line);
  if (date) {
    const when = make("p", "mg-card__date"); // the day of the change, alone on the last line
    when.append(date);
    foot.append(when);
  }
  box.append(foot);
  return box;
}

export function chip(text, { glyph = null, tone = null } = {}) {
  const el = make("span", `ge-chip mg-chip${tone ? ` ge-chip--${tone}` : ""}`);
  if (glyph) el.append(icon(glyph));
  el.append(document.createTextNode(text));
  return el;
}

function iconButton(glyph, label, className = "") {
  const button = make("button", `icon-button icon-button--sm ${className}`.trim());
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(icon(glyph));
  return button;
}

/** The nearest ancestor that scrolls (the area of the page), or the document. */
function scrollParent(el) {
  for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY;
    if (overflow === "auto" || overflow === "scroll") return node;
  }
  return document.scrollingElement ?? document.documentElement;
}

export class ManagementPage {
  constructor(root, config) {
    this.config = { ...config };
    this.root = root;
    this.items = [];
    this.selectedKey = null;
    const stored = readJson(`oa-management-${config.name}`) ?? {};
    // what the browser remembers is the STEP of the page size (1, 2 or 4 times the base, page-size.js), never a number of entries: an old
    // stored `size` is not a step and falls back to the first
    this.prefs = { view: stored.view ?? "cards", sort: stored.sort ?? this.config.sorts[0].key, step: stepOf(stored.step) };
    this.base = MINIMUM; // the entries that fit the room of the list (measured, #fit); never fewer than 12
    this.fitted = null; // the view the base was measured for
    this.resizeTimer = null;
    this.tab = config.tabs?.[0]?.key ?? null;
    this.search = "";
    this.tag = null;
    this.page = 0;
    this.#build();
    // the base follows the room: the width of the page (also a turned tablet) and the height of the window; measured again after a short pause
    const later = () => this.#later();
    if (typeof ResizeObserver === "function") new ResizeObserver(later).observe(this.root);
    window.addEventListener("resize", later);
  }

  // ── structure ───────────────────────────────────────────────────────

  #build() {
    const c = this.config;
    this.root.classList.add("mg");
    this.root.dataset.page = c.name; // a page may style its own rows (the archive: ADR-069 addendum 13)
    const main = make("div", "mg__main");
    // the toolbar: row one is search, order and "Per page [12] [cards][list]" and never changes; a page with tabs puts the tabs and the filter in a
    // row of their own below it, so search and order stay where they are while the tabs are clicked through
    const bar = make("div", "mg__toolbar");
    const row = make("div", "mg__row");
    const tabsRow = make("div", "mg__row mg__row--tabs");
    if (c.tabs) {
      this.tabBar = make("div", "mg-segment");
      this.tabBar.setAttribute("role", "tablist");
      this.tabBar.setAttribute("aria-label", c.label);
      this.tabButtons = c.tabs.map((tab) => {
        const button = make("button", "mg-segment__tab");
        button.type = "button";
        button.setAttribute("role", "tab");
        button.dataset.tab = tab.key;
        button.append(icon(tab.icon), make("span", "", tab.label), make("span", "mg-segment__count"));
        button.addEventListener("click", () => this.#setTab(tab.key));
        return button;
      });
      this.tabBar.append(...this.tabButtons);
      this.tabBar.addEventListener("keydown", (event) => this.#tabKey(event));
      tabsRow.append(this.tabBar);
    }
    const searchBox = make("label", "mg-search");
    this.searchInput = make("input", "field__control");
    Object.assign(this.searchInput, { type: "search", placeholder: c.placeholder ?? t("components.management.search"), autocomplete: "off" });
    this.searchInput.setAttribute("aria-label", c.placeholder ?? t("components.management.search"));
    this.searchInput.addEventListener("input", () => {
      this.search = this.searchInput.value;
      this.page = 0;
      this.render();
    });
    searchBox.append(icon("search"), this.searchInput);
    row.append(searchBox);
    this.sortSelect = make("select", "field__control mg-sort");
    this.sortSelect.setAttribute("aria-label", t("components.management.sort"));
    for (const sort of c.sorts) this.sortSelect.append(new Option(sort.label, sort.key));
    this.sortSelect.value = this.prefs.sort;
    this.sortSelect.addEventListener("change", () => {
      this.prefs.sort = this.sortSelect.value;
      this.#save();
      this.render();
    });
    row.append(this.sortSelect);
    if (c.tagsOf) {
      this.filterButton = make("button", "button button--ghost button--sm mg-filter");
      this.filterButton.type = "button";
      this.filterButton.setAttribute("aria-haspopup", "menu");
      this.filterButton.append(icon("filter"), make("span", "", t("components.management.filter")));
      this.filterButton.addEventListener("click", () => this.#filterMenu());
      // with tabs the filter sits next to them (row two); without, it follows the order in row one
      (c.tabs ? tabsRow : row).append(this.filterButton);
    }
    this.viewToggle = make("div", "mg-view");
    this.viewToggle.setAttribute("role", "group");
    this.viewToggle.setAttribute("aria-label", t("components.management.view"));
    this.viewButtons = Object.fromEntries(
      [["cards", "grid", t("components.management.cards")], ["list", "list", t("components.management.list")]].map(([key, glyph, label]) => {
        const button = iconButton(glyph, label, "mg-view__button");
        button.addEventListener("click", () => {
          this.prefs.view = key;
          this.#save();
          this.render();
        });
        return [key, button];
      }),
    );
    this.viewToggle.append(...Object.values(this.viewButtons));
    // the page size sits in the toolbar next to the switch between cards and list (the pager below keeps the range and the pages); its choices
    // are the base and twice and four times the base (drawn by #pager, because the base follows the room)
    const sizeLabel = make("label", "mg__size");
    this.sizeSelect = make("select", "field__control");
    this.sizeSelect.addEventListener("change", () => {
      const before = this.#size();
      this.prefs.step = stepOf(this.sizeSelect.value);
      this.page = pageOf(firstOf(this.page, before), this.#size()); // the first entry on the screen stays on the page
      this.#save();
      this.render();
    });
    sizeLabel.append(document.createTextNode(t("components.management.per_page")), this.sizeSelect);
    // "Per page [12]  [cards][list]": one group at the right end of the toolbar, which wraps as a whole
    const tools = make("div", "mg__tools");
    tools.append(sizeLabel, this.viewToggle);
    row.append(tools);
    bar.append(row);
    if (c.tabs) bar.append(tabsRow);
    this.list = make("ul", "mg__list");
    this.list.setAttribute("aria-label", c.label);
    this.empty = make("p", "ge-empty glass mg__empty", c.emptyText ?? "");
    this.empty.hidden = true;
    this.pager = make("div", "mg__pager");
    main.append(bar, this.list, this.empty, this.pager);
    this.panel = make("aside", "mg__panel");
    this.panel.hidden = false;
    this.scrim = make("div", "mg__scrim");
    this.scrim.hidden = true;
    this.scrim.addEventListener("click", () => this.select(null));
    this.root.replaceChildren(main, this.scrim, this.panel);
    this.list.addEventListener("keydown", (event) => this.#key(event));
  }

  #save() {
    writeJson(`oa-management-${this.config.name}`, { view: this.prefs.view, sort: this.prefs.sort, step: this.prefs.step });
  }

  // ── the page size follows the room ──────────────────────────────────

  /** The entries of one page: the base times the chosen step (a step the base no longer has a choice for moves to the largest there is). */
  #size() {
    return sizeOf(this.base, usableStep(this.base, this.prefs.step));
  }

  /** The visible height of the list from its top down to the bottom of the area that scrolls, less the pager and the padding below. */
  #roomBelow() {
    const scroller = scrollParent(this.list);
    const own = scroller === document.scrollingElement;
    const box = own ? { top: 0, bottom: window.innerHeight } : scroller.getBoundingClientRect();
    const topInside = this.list.getBoundingClientRect().top - box.top + (scroller.scrollTop || 0);
    const pager = this.pager.offsetHeight || 32;
    const gap = parseFloat(getComputedStyle(this.list.parentElement).rowGap) || 0;
    const padding = own ? 0 : parseFloat(getComputedStyle(scroller).paddingBottom) || 0;
    return box.bottom - box.top - topInside - pager - gap - padding;
  }

  /** The base for the room the list has now: the cards are 19 rem by 11 rem (read from the page, not guessed), so columns and rows are exact;
   *  in the list view a row is as high as the first row (56 px until there is one). Nothing to measure (hidden, no size): the minimum. */
  #measure() {
    const width = this.list.clientWidth;
    if (!(width > 0)) return MINIMUM;
    const style = getComputedStyle(this.list);
    const gapX = parseFloat(style.columnGap) || 0;
    const gapY = parseFloat(style.rowGap) || 0;
    const room = this.#roomBelow();
    if (this.prefs.view === "list") {
      const row = this.list.firstElementChild?.offsetHeight || 56;
      return baseOf(1, fit(room, row, gapY));
    }
    const probe = make("div");
    probe.style.cssText = "position:absolute;visibility:hidden;pointer-events:none;width:var(--mg-card-w);height:var(--mg-card-h)";
    this.root.append(probe);
    const card = probe.getBoundingClientRect();
    probe.remove();
    return baseOf(fit(width, card.width, gapX), fit(room, card.height, gapY));
  }

  /** Takes a new base: the first entry on the screen stays on the page. Returns whether the size of a page changed. */
  #take(base) {
    if (base === this.base) return false;
    const before = this.#size();
    const first = firstOf(this.page, before);
    this.base = base;
    this.page = pageOf(first, this.#size());
    return this.#size() !== before;
  }

  /** Before a drawing: measure once per view (the cards and the rows are measured differently). */
  #fit() {
    if (this.fitted === this.prefs.view) return;
    this.fitted = this.prefs.view;
    this.#take(this.#measure());
  }

  /** The room changed (window, turned screen): measure again after a short pause, and draw again only when the size of a page changed. */
  #later() {
    clearTimeout(this.resizeTimer);
    this.resizeTimer = setTimeout(() => {
      if (this.#take(this.#measure())) this.render();
    }, 150);
  }

  // ── data ────────────────────────────────────────────────────────────

  setItems(items) {
    this.items = items;
    if (this.selectedKey !== null && !items.some((i) => this.config.itemKey(i) === this.selectedKey)) this.selectedKey = null;
    this.render();
  }

  get selected() {
    return this.items.find((i) => this.config.itemKey(i) === this.selectedKey) ?? null;
  }

  /** The entries the toolbar lets through, in the chosen order (the whole list: pages are cut from it). */
  visible() {
    const c = this.config;
    const needle = this.search.trim().toLowerCase();
    const sort = c.sorts.find((s) => s.key === this.prefs.sort) ?? c.sorts[0];
    return this.items
      .filter((i) => !this.tab || c.tabs.find((x) => x.key === this.tab).match(i))
      .filter((i) => !needle || (c.search?.(i) ?? "").toLowerCase().includes(needle))
      .filter((i) => !this.tag || (c.tagsOf?.(i) ?? []).some((x) => x.toLowerCase() === this.tag.toLowerCase()))
      .sort(sort.compare);
  }

  // ── drawing ─────────────────────────────────────────────────────────

  render() {
    const c = this.config;
    this.#fit();
    const all = this.visible();
    const size = this.#size();
    this.root.dataset.base = String(this.base);
    this.root.dataset.size = String(size);
    const pages = Math.max(1, Math.ceil(all.length / size));
    this.page = Math.min(this.page, pages - 1);
    const shown = all.slice(this.page * size, (this.page + 1) * size);
    if (this.tabBar) {
      this.tabButtons.forEach((button, i) => {
        const on = button.dataset.tab === this.tab;
        button.setAttribute("aria-selected", String(on));
        button.tabIndex = on ? 0 : -1;
        button.querySelector(".mg-segment__count").textContent = `(${this.items.filter((x) => c.tabs[i].match(x)).length})`;
      });
    }
    for (const [key, button] of Object.entries(this.viewButtons)) {
      button.classList.toggle("is-on", this.prefs.view === key);
      button.setAttribute("aria-pressed", String(this.prefs.view === key));
    }
    if (this.filterButton) this.filterButton.classList.toggle("is-on", Boolean(this.tag));
    this.list.dataset.view = this.prefs.view;
    const first = shown.find((i) => c.itemKey(i) === this.selectedKey) ?? shown[0];
    this.list.replaceChildren(...shown.map((item) => this.#entry(item, item === first)));
    this.empty.hidden = all.length > 0;
    this.#pager(all.length, pages);
    this.refreshPanel();
    // in the list view the row height is known only now: measure once more when the rows are there (and the size of a page changes)
    if (this.prefs.view === "list" && this.list.firstElementChild && this.listMeasured !== this.list.firstElementChild.offsetHeight) {
      this.listMeasured = this.list.firstElementChild.offsetHeight;
      this.#later();
    }
  }

  #entry(item, focusable) {
    const c = this.config;
    const key = c.itemKey(item);
    const li = make("li", "mg-card glass");
    li.dataset.key = key;
    li.tabIndex = focusable ? 0 : -1;
    if (key === this.selectedKey) li.setAttribute("aria-current", "true");
    li.append(c.card(item, this.prefs.view));
    if (c.readOnly) {
      // a read-only list (the archive): no pencil, no bin, and a double click opens nothing
      li.addEventListener("click", () => this.select(key));
      return li;
    }
    const actions = make("div", "mg-card__actions");
    const edit = iconButton("pencil", c.editLabel?.(item) ?? t("components.management.edit"), "mg-card__edit");
    edit.dataset.edit = "";
    edit.addEventListener("click", (event) => {
      event.stopPropagation();
      c.onEdit?.(item);
    });
    const blocked = c.deleteBlocked?.(item) ?? null;
    const del = iconButton("trash", blocked ?? c.deleteLabel?.(item) ?? t("common.delete"), "is-danger");
    del.dataset.delete = "";
    if (blocked) del.setAttribute("aria-disabled", "true"); // disabled, not removed: it keeps its tooltip
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      if (blocked) c.onBlocked?.(item, blocked); // optional: the page may explain on a click (a banner)
      else c.onDelete?.(item);
    });
    actions.append(edit, del);
    li.append(actions);
    li.addEventListener("click", () => this.select(key));
    li.addEventListener("dblclick", () => c.onOpen?.(item));
    return li;
  }

  #pager(total, pages) {
    const size = this.#size();
    const from = total ? this.page * size + 1 : 0;
    const to = Math.min(total, (this.page + 1) * size);
    const info = make("span", "mg__count", t("components.management.range", { from, to, total }));
    const prev = iconButton("chevron-left", t("components.management.previous"));
    const next = iconButton("chevron-right", t("components.management.next"));
    prev.disabled = this.page === 0;
    next.disabled = this.page >= pages - 1;
    prev.addEventListener("click", () => this.#go(this.page - 1));
    next.addEventListener("click", () => this.#go(this.page + 1));
    this.sizeSelect.replaceChildren(...choices(this.base).map((c) => new Option(String(c.size), String(c.step))));
    this.sizeSelect.value = String(usableStep(this.base, this.prefs.step));
    this.pager.replaceChildren(info, ...(pages > 1 ? [prev, make("span", "mg__page", `${this.page + 1} / ${pages}`), next] : []));
  }

  #go(page) {
    this.page = page;
    this.render();
  }

  // ── tabs, filter ────────────────────────────────────────────────────

  #setTab(key) {
    this.tab = key;
    this.page = 0;
    this.render();
    this.config.onTab?.(key);
  }

  #tabKey(event) {
    const keys = this.config.tabs.map((x) => x.key);
    const at = keys.indexOf(this.tab);
    const next = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: keys.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    this.#setTab(keys[(next + keys.length) % keys.length]);
    this.tabBar.querySelector('[aria-selected="true"]').focus();
  }

  #filterMenu() {
    const tags = [...new Set(this.items.flatMap((i) => this.config.tagsOf(i)).map((x) => x))].sort((a, b) => a.localeCompare(b));
    const entries = [{ label: t("components.management.all_tags"), icon: this.tag ? "tag" : "check", onSelect: () => ((this.tag = null), this.render()) }];
    for (const tag of tags) entries.push({ label: tag, icon: this.tag?.toLowerCase() === tag.toLowerCase() ? "check" : "tag", onSelect: () => ((this.tag = tag), (this.page = 0), this.render()) });
    menu.toggle(this.filterButton, entries, t("components.management.filter"));
  }

  // ── selection, keys ─────────────────────────────────────────────────

  select(key) {
    this.selectedKey = key;
    for (const li of this.list.children) {
      const on = li.dataset.key === key;
      li.toggleAttribute("aria-current", on);
      if (on) li.setAttribute("aria-current", "true");
      li.tabIndex = on ? 0 : li.tabIndex === 0 && key === null ? 0 : -1;
    }
    this.refreshPanel();
  }

  #key(event) {
    const li = event.target.closest(".mg-card");
    if (!li || event.target !== li) return;
    const cards = [...this.list.children];
    const at = cards.indexOf(li);
    const item = this.items.find((i) => this.config.itemKey(i) === li.dataset.key);
    const move = { ArrowDown: at + 1, ArrowRight: at + 1, ArrowUp: at - 1, ArrowLeft: at - 1, Home: 0, End: cards.length - 1 }[event.key];
    if (move !== undefined) {
      event.preventDefault();
      const target = cards[Math.min(Math.max(move, 0), cards.length - 1)];
      for (const card of cards) card.tabIndex = card === target ? 0 : -1;
      target.focus();
      this.select(target.dataset.key);
    } else if (event.key === "Enter") {
      event.preventDefault();
      this.config.onOpen?.(item);
    } else if (event.key === "Delete") {
      event.preventDefault();
      if (!this.config.deleteBlocked?.(item)) this.config.onDelete?.(item);
    }
  }

  // ── the panel ───────────────────────────────────────────────────────

  /** Draws the panel again for the selected entry (after the entry changed), keeping the tab that is open. */
  refreshPanel() {
    const item = this.selected;
    const open = this.panelTab;
    // the room for the panel is always reserved (two thirds list, one third panel): without a selection it holds a quiet line
    this.panel.hidden = false;
    this.panel.dataset.empty = String(!item);
    this.scrim.hidden = !item;
    this.root.dataset.hasPanel = String(Boolean(item));
    if (!item) {
      const note = make("p", "mg-panel__placeholder", this.config.panel?.placeholder ?? t("components.management.select_one"));
      this.panel.replaceChildren(note);
      return;
    }
    const p = this.config.panel;
    const head = make("header", "mg-panel__head");
    const mark = make("span", "mg-panel__icon");
    mark.append(icon(p.icon(item)));
    const text = make("div", "mg-panel__title");
    text.append(make("h2", "", p.title(item)), make("div", "mg-panel__chips"));
    text.lastChild.append(...p.chips(item));
    const close = iconButton("x", t("common.close_dialog"), "mg-panel__close");
    close.addEventListener("click", () => this.select(null));
    head.append(mark, text, close);
    const id = `mg-${(uid += 1)}`;
    const tabs = p.tabs(item);
    const list = make("div", "mg-tabs");
    list.setAttribute("role", "tablist");
    const bodies = [];
    for (const tab of tabs) {
      const button = make("button", "mg-tabs__tab", tab.label);
      button.type = "button";
      button.id = `${id}-tab-${tab.key}`;
      button.dataset.tab = tab.key;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", `${id}-panel-${tab.key}`);
      button.setAttribute("aria-selected", "false");
      if (tab.disabled) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
      }
      list.append(button);
      const body = make("div", "mg-panel__body");
      body.id = `${id}-panel-${tab.key}`;
      body.setAttribute("role", "tabpanel");
      body.setAttribute("aria-labelledby", button.id);
      body.hidden = true;
      bodies.push(body);
    }
    this.panel.replaceChildren(head, list, ...bodies);
    const drawn = new Set();
    const show = (key) => {
      this.panelTab = key;
      if (drawn.has(key)) return;
      drawn.add(key);
      tabs.find((x) => x.key === key).render(bodies[tabs.findIndex((x) => x.key === key)], item);
    };
    const first = tabs.find((x) => x.key === open && !x.disabled) ?? tabs.find((x) => !x.disabled);
    const strip = new Tabs(list, (key) => show(key));
    strip.select(first.key, { notify: false });
    show(first.key);
  }
}
