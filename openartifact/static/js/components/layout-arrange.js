/* The arrange view of a manifest window (ADR-063): the window's structure drawn as sections (dashed outlines, a grip each) with
 * their fields as bars (a grip each) in the same grid the window has, so a section or a field can be dragged where it should
 * sit. Drag the grip with the pointer (a line shows where it will land, the window scrolls while the pointer is at its edge,
 * Escape cancels the drag), or focus it and press the arrow keys (Up/Down in a list and on into the next area, Left/Right to
 * the neighbouring area; Alt is the same): the move is announced. A field or setting may be dropped into ANY area, an empty
 * one shows "Drop settings here". "Add area" appends an area of the user's own (a plain title, renamed in place, deleted while
 * it is empty). The pure rules are layout-model.js; this draws and listens.
 *
 *   const view = new ArrangeView(host, {structure, width, onChange});  view.structure  view.setStructure(s)
 */
import { icon } from "./icons.js";
import { InlineName } from "./inline-name.js";
import { MAX_CUSTOM, TITLE_MAX, addArea, blocksOf, customCount, deleteArea, fieldPlace, moveFieldBy, moveSectionBy, movedText, placeField, placeSection, renameArea, sectionOfField, sectionPlace, slotAmong } from "./layout-model.js";
import { t } from "../i18n.js";

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

const LABELS = {
  column: (v) => t("components.layout.moved_column", v),
  row: (v) => t("components.layout.moved_row", v),
  side: (v) => t("components.layout.moved_side", v),
  field: (v) => t("components.layout.moved_field", v),
  folded: (v) => t("components.layout.moved_folded", v),
  fieldArea: (v) => t("components.layout.moved_field_area", v),
};

/** The nearest ancestor that scrolls (the dialog), else the document's scroller. */
function scroller(el) {
  for (let at = el.parentElement; at; at = at.parentElement) {
    const { overflowY } = getComputedStyle(at);
    if ((overflowY === "auto" || overflowY === "scroll") && at.scrollHeight > at.clientHeight) return at;
  }
  return document.scrollingElement;
}

/** How many of `items` lie above the pointer (their middle is above `y`): the index a drop there takes. */
function indexAt(items, y) {
  return items.filter((item) => {
    const box = item.getBoundingClientRect();
    return box.top + box.height / 2 < y;
  }).length;
}


export class ArrangeView {
  /**
   * @param {HTMLElement} host where the view is drawn
   * @param {{structure: object, width?: number|null, onChange?: (structure: object) => void}} config
   *   width: the window's width in rem, so the sections sit as in the window
   */
  constructor(host, { structure, width = null, onChange = () => {} }) {
    this.host = host;
    this.width = width;
    this.onChange = onChange;
    this.current = structure;
    this.drag = null;
    this.names = new Map(); // custom area key -> its InlineName
    this.live = make("div", "visually-hidden");
    this.live.setAttribute("role", "status");
    host.addEventListener("pointerdown", (event) => this.#start(event));
    host.addEventListener("keydown", (event) => this.#key(event));
    this.render();
  }

  get structure() {
    return this.current;
  }

  setStructure(structure) {
    this.current = structure;
    this.render();
  }

  render(focusKey = null) {
    this.names.clear();
    const root = make("div", "lw-arrange");
    root.dataset.mode = this.current.mode;
    if (this.width) root.style.setProperty("--lw-width", `${this.width}rem`);
    if (this.current.mode === "node") {
      const grid = make("div", "lw-grid");
      grid.dataset.columns = String(this.current.sections.length);
      this.current.sections.forEach((section, side) => {
        const lane = make("div", "lw-lane");
        lane.dataset.lane = String(side);
        lane.dataset.block = "0";
        lane.append(this.#section(section));
        grid.append(lane);
      });
      root.append(grid);
    } else {
      blocksOf(this.current).forEach((block, at) => {
        if (block.full) {
          const row = make("div", "lw-row");
          row.dataset.block = String(at);
          row.append(this.#section(block.full));
          root.append(row);
          return;
        }
        const grid = make("div", "lw-grid");
        grid.dataset.columns = "2";
        grid.dataset.block = String(at);
        block.lanes.forEach((sections, side) => {
          const lane = make("div", "lw-lane");
          lane.dataset.lane = String(side);
          lane.dataset.block = String(at);
          for (const section of sections) lane.append(this.#section(section));
          grid.append(lane);
        });
        root.append(grid);
      });
    }
    root.append(this.#addTile(), this.live);
    this.host.replaceChildren(root);
    if (focusKey) this.host.querySelector(`[data-grip-key="${CSS.escape(focusKey)}"]`)?.focus({ preventScroll: true });
  }

  // ── drawing ─────────────────────────────────────────────────────────

  #grip(label, key, kind) {
    const grip = make("button", "lw-grip");
    grip.type = "button";
    grip.dataset.gripKey = key;
    grip.dataset.grip = kind;
    grip.setAttribute("aria-label", label);
    grip.title = label;
    grip.append(icon("grip"));
    return grip;
  }

  #section(section) {
    const box = make("fieldset", "lw-section");
    box.dataset.section = section.key;
    box.dataset.custom = section.custom ? "true" : "false";
    const head = make("legend", "lw-section__head");
    head.append(this.#grip(t("components.layout.move_section", { title: section.title }), `s:${section.key}`, "section"));
    const title = make("span", "lw-section__title", section.title);
    head.append(title);
    if (section.custom) {
      // an area of one's own: its title is renamed in place and the area deleted while it is empty
      title.dataset.areaTitle = section.key;
      this.names.set(section.key, new InlineName(title, { label: t("components.layout.area_title"), maxLength: TITLE_MAX, onCommit: (value) => this.#rename(section.key, value) }));
      head.append(this.#remove(section));
    }
    if (section.column === "full") head.append(make("span", "tag", t("components.layout.full_width")));
    box.append(head);
    if (this.current.mode === "node" && section.key === "definition") {
      for (const name of this.current.fixed ?? []) {
        const fixed = make("p", "lw-fixed");
        fixed.append(make("span", "lw-fixed__name", name), make("span", "tag", t("components.layout.fixed")));
        box.append(fixed);
      }
    }
    const shown = section.fields.filter((f) => !f.advanced);
    const folded = section.fields.filter((f) => f.advanced);
    box.append(this.#list(section, shown, false));
    if (this.current.mode === "form") {
      const divider = make("p", "lw-folded", t("components.layout.more_options"));
      divider.dataset.folded = "";
      box.append(divider, this.#list(section, folded, true));
    }
    return box;
  }

  #list(section, fields, advanced) {
    const list = make("ol", "lw-fields");
    list.dataset.list = advanced ? "folded" : "shown";
    for (const field of fields) {
      const item = make("li", "lw-field");
      item.dataset.field = field.key;
      const label = make("span", "lw-field__label", field.label);
      item.append(this.#grip(t("components.layout.move_field", { title: field.label }), `f:${section.key}:${field.key}`, "field"), label);
      if (field.tag) item.append(make("span", "lw-field__tag", field.tag === "group" && field.count > 1 ? t("components.layout.group_of", { count: field.count }) : field.tag));
      if (field.condition) item.append(make("span", "lw-field__tag lw-field__tag--when", t("components.layout.conditional")));
      if (field.required) item.append(make("span", "lw-field__tag", t("components.layout.required")));
      list.append(item);
    }
    if (!fields.length && !advanced) list.append(make("li", "lw-hint", t("components.layout.drop_here")));
    return list;
  }

  /** The delete button of an area of one's own: only an empty one can go, the others say what to do first. */
  #remove(section) {
    const button = make("button", "icon-button icon-button--sm is-danger lw-section__delete");
    button.type = "button";
    button.dataset.deleteArea = section.key;
    const blocked = section.fields.length > 0;
    button.setAttribute("aria-label", t("components.layout.delete_area", { title: section.title }));
    button.title = blocked ? t("components.layout.delete_area_blocked") : t("components.layout.delete_area", { title: section.title });
    if (blocked) button.setAttribute("aria-disabled", "true");
    button.append(icon("trash"));
    button.addEventListener("click", () => {
      if (blocked) {
        this.#announce(t("components.layout.delete_area_blocked"));
        return;
      }
      const next = deleteArea(this.current, section.key);
      if (!next) return;
      this.current = next;
      this.render();
      this.#announce(t("components.layout.area_deleted", { title: section.title }));
      this.onChange(next);
    });
    return button;
  }

  /** The tile that adds an area of one's own; at the limit it says so. */
  #addTile() {
    const button = make("button", "button button--ghost button--sm lw-add");
    button.type = "button";
    button.dataset.addArea = "";
    button.append(icon("plus"), document.createTextNode(t("components.layout.add_area")));
    if (customCount(this.current) >= MAX_CUSTOM) {
      button.setAttribute("aria-disabled", "true");
      button.title = t("components.layout.max_areas", { count: MAX_CUSTOM });
    }
    button.addEventListener("click", () => {
      if (button.getAttribute("aria-disabled") === "true") return;
      const next = addArea(this.current, t("components.layout.new_area"));
      if (!next) return;
      const key = next.sections.at(-1).key;
      this.current = next;
      this.render();
      this.#announce(t("components.layout.area_added", { title: next.sections.at(-1).title }));
      this.onChange(next);
      this.names.get(key)?.edit(); // its title is the first thing to give it
    });
    return button;
  }

  #rename(key, value) {
    const next = renameArea(this.current, key, value);
    if (!next) return;
    this.current = next;
    this.render(`s:${key}`);
    this.onChange(next);
  }

  #announce(text) {
    this.live.textContent = "";
    window.setTimeout(() => (this.live.textContent = text), 0);
  }

  // ── moving ──────────────────────────────────────────────────────────

  #apply(next, kind, keys, focusKey) {
    if (!next) return false;
    this.current = next;
    this.render(focusKey);
    this.live.textContent = "";
    // a changed text is read again by a live region; clear first
    window.setTimeout(() => (this.live.textContent = movedText(next, kind, keys, LABELS)), 0);
    this.onChange(next);
    return true;
  }

  #key(event) {
    const grip = event.target.closest?.(".lw-grip");
    const directions = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
    const direction = directions[event.key];
    if (!grip || !direction || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    if (grip.dataset.grip === "section") {
      const key = grip.dataset.gripKey.slice(2);
      this.#apply(moveSectionBy(this.current, key, direction), "section", { section: key }, grip.dataset.gripKey);
      return;
    }
    const [, section, ...rest] = grip.dataset.gripKey.split(":");
    const field = rest.join(":");
    const next = moveFieldBy(this.current, section, field, direction);
    if (!next) return;
    const now = sectionOfField(next, field); // a field may have gone into another area
    this.#apply(next, "field", { section: now, field, from: section }, `f:${now}:${field}`);
  }

  #start(event) {
    const grip = event.target.closest?.(".lw-grip");
    if (!grip || event.button !== 0 || this.drag) return;
    event.preventDefault();
    const kind = grip.dataset.grip;
    const [, a, ...b] = grip.dataset.gripKey.split(":");
    const keys = kind === "section" ? { section: grip.dataset.gripKey.slice(2) } : { section: a, field: b.join(":") };
    const element = kind === "section" ? grip.closest(".lw-section") : grip.closest(".lw-field");
    const box = element.getBoundingClientRect();
    const ghost = element.cloneNode(true);
    ghost.classList.add("lw-ghost");
    ghost.style.width = `${box.width}px`;
    ghost.removeAttribute("data-section");
    ghost.removeAttribute("data-field");
    document.body.append(ghost);
    const indicator = make("div", "lw-drop");
    element.classList.add("is-dragging");
    const offset = { x: event.clientX - box.left, y: event.clientY - box.top };
    this.drag = { kind, keys, element, ghost, indicator, target: null, pointer: event, offset, timer: null, scroller: scroller(this.host) };
    const move = (e) => this.#move(e);
    const end = (e) => this.#end(e, move, end, cancel);
    const cancel = (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      this.#end(null, move, end, cancel);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    window.addEventListener("keydown", cancel, true);
    this.drag.timer = window.setInterval(() => this.#autoscroll(), 30);
    this.#move(event);
  }

  #autoscroll() {
    const { scroller: box, pointer } = this.drag;
    if (!box) return;
    const rect = box === document.scrollingElement ? { top: 0, bottom: window.innerHeight } : box.getBoundingClientRect();
    if (pointer.clientY < rect.top + 40) box.scrollTop -= 12;
    else if (pointer.clientY > rect.bottom - 40) box.scrollTop += 12;
    else return;
    this.#target(pointer);
  }

  #move(event) {
    if (!this.drag) return;
    this.drag.pointer = event;
    const { ghost, offset } = this.drag;
    ghost.style.left = `${event.clientX - offset.x}px`;
    ghost.style.top = `${event.clientY - offset.y}px`;
    this.#target(event);
  }

  /** Where a drop at the pointer would land: `{list, index, place}` or null; the line shows it. */
  #target(event) {
    const { kind, keys, element, indicator } = this.drag;
    const x = event.clientX;
    const y = event.clientY;
    let target = null;
    if (kind === "field") {
      // the area nearest to the pointer (within a margin), whichever it is: a field may sit in any of them
      let best = null;
      let nearest = 28;
      for (const candidate of this.host.querySelectorAll(".lw-section")) {
        const box = candidate.getBoundingClientRect();
        const distance = Math.hypot(Math.max(box.left - x, 0, x - box.right), Math.max(box.top - y, 0, y - box.bottom));
        if (distance < nearest) {
          best = candidate;
          nearest = distance;
        }
      }
      if (best) {
        const folded = best.querySelector("[data-folded]");
        const useFolded = Boolean(folded) && y >= folded.getBoundingClientRect().top;
        const list = best.querySelector(`[data-list="${useFolded ? "folded" : "shown"}"]`);
        const items = [...list.children].filter((c) => c !== element && c.classList.contains("lw-field"));
        target = { list, anchor: items, index: indexAt(items, y), place: { section: best.dataset.section, advanced: useFolded } };
      }
    } else if (this.current.mode === "node") {
      // the areas flow side by side or one under the other: the slot is read in reading order
      const lanes = [...this.host.querySelectorAll(".lw-lane")].filter((l) => !l.contains(element));
      const index = slotAmong(lanes.map((l) => l.getBoundingClientRect()), x, y);
      target = { list: null, anchor: lanes, index, place: { lane: index }, marks: true };
    } else if (sectionPlace(this.current, keys.section)?.full) {
      const rows = [...this.host.querySelectorAll("[data-block]")].filter((b) => b.classList.contains("lw-row") || b.classList.contains("lw-grid"));
      const index = indexAt(
        rows.filter((r) => !r.contains(element)),
        y,
      );
      target = { list: this.host.querySelector(".lw-arrange"), anchor: rows, index, place: { block: index }, rows: true };
    } else {
      const lanes = [...this.host.querySelectorAll(".lw-lane")];
      const lane = lanes.find((l) => {
        const box = l.getBoundingClientRect();
        const grid = l.parentElement.getBoundingClientRect();
        return x >= box.left && x <= box.right && y >= grid.top - 16 && y <= grid.bottom + 16;
      });
      if (lane) {
        const items = [...lane.children].filter((c) => c !== element && c.classList.contains("lw-section"));
        target = { list: lane, anchor: items, index: indexAt(items, y), place: { block: Number(lane.dataset.block), lane: Number(lane.dataset.lane) } };
      }
    }
    this.drag.target = target;
    indicator.remove();
    this.#clearMarks();
    if (!target) return;
    if (target.marks) {
      const lane = target.anchor[target.index];
      if (lane) lane.classList.add("is-drop-before");
      else target.anchor.at(-1)?.classList.add("is-drop-after");
      return;
    }
    if (target.rows) {
      const rows = target.anchor.filter((r) => !r.contains(element));
      if (rows[target.index]) rows[target.index].before(indicator);
      else rows.at(-1)?.after(indicator);
      return;
    }
    const before = target.anchor[target.index];
    if (before) before.before(indicator);
    else target.list.append(indicator);
  }

  #clearMarks() {
    for (const lane of this.host.querySelectorAll(".is-drop-before, .is-drop-after")) lane.classList.remove("is-drop-before", "is-drop-after");
  }

  #end(event, move, end, cancel) {
    const drag = this.drag;
    if (!drag) return;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
    window.removeEventListener("pointercancel", end);
    window.removeEventListener("keydown", cancel, true);
    window.clearInterval(drag.timer);
    drag.ghost.remove();
    drag.indicator.remove();
    this.#clearMarks();
    drag.element.classList.remove("is-dragging");
    this.drag = null;
    if (!event || event.type === "pointercancel" || !drag.target) return;
    const { kind, keys, target } = drag;
    if (kind === "field") {
      const into = target.place.section;
      const next = placeField(this.current, keys.section, keys.field, { advanced: target.place.advanced, index: target.index, toSection: into });
      const at = fieldPlace(this.current, keys.section, keys.field);
      if (next && (into !== keys.section || at.advanced !== target.place.advanced || at.index !== target.index)) {
        this.#apply(next, "field", { section: into, field: keys.field, from: keys.section }, `f:${into}:${keys.field}`);
      }
      return;
    }
    const next = placeSection(this.current, keys.section, { block: target.place.block ?? 0, lane: target.place.lane ?? 0, index: target.index });
    if (next && JSON.stringify(next.sections.map((s) => [s.key, s.column])) !== JSON.stringify(this.current.sections.map((s) => [s.key, s.column]))) {
      this.#apply(next, "section", keys, `s:${keys.section}`);
    }
  }
}
