/* A set of selected ids, for any list that offers a bulk action (the execution list; later the board or the lanes).
 * It only holds the ids and tells its owner when they change; drawing checkboxes and the bulk bar is the owner's. */

export class Selection {
  /** @param {(ids: Set<string>) => void} [onChange] called after every change (not when nothing changed) */
  constructor(onChange = () => {}) {
    this.ids = new Set();
    this.onChange = onChange;
  }

  get size() {
    return this.ids.size;
  }

  has(id) {
    return this.ids.has(id);
  }

  /** Add (`on` true), remove (`on` false) or flip an id. */
  toggle(id, on = !this.ids.has(id)) {
    if (on === this.ids.has(id)) return;
    if (on) this.ids.add(id);
    else this.ids.delete(id);
    this.onChange(this.ids);
  }

  /** Replace the selection. */
  set(ids) {
    const next = new Set(ids);
    if (next.size === this.ids.size && [...next].every((id) => this.ids.has(id))) return;
    this.ids = next;
    this.onChange(this.ids);
  }

  clear() {
    this.set([]);
  }

  /** Drop the ids that are not in `present` (rows that are gone). */
  keepOnly(present) {
    this.set([...this.ids].filter((id) => present.has(id)));
  }

  /** The state of a "select all shown" checkbox for the ids that are shown. */
  stateOf(shown) {
    const count = shown.filter((id) => this.ids.has(id)).length;
    return { checked: shown.length > 0 && count === shown.length, indeterminate: count > 0 && count < shown.length };
  }
}
