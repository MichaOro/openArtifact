/* The small popup of a scope's guards in the pipeline editor (ADR-060). Two ways in:
 *   "add"  (the Guard entry of the pipeline's "+" menu, a stage's "+", an action's menu and settings): "Add a guard" with
 *          two buttons, "New guard" (the primary one) and "Attach guard" (which opens the attach dialog with a combobox
 *          of the guards not attached here yet), and below them the guards attached here;
 *   "list" (the shield of the pipeline, a stage or an action): the guards attached here.
 * An attached guard is listed by its name (muted and struck through while it is off) with its on/off switch and Detach;
 * its name opens the definition in the guard editor. The card of an action in a pipeline also lists the guards that sit
 * INSIDE the action (on the whole action definition or on one of its nodes) under "In the action", by name with what
 * they watch (no switch, no Detach: they belong to the action) and a link that opens the action.
 * Variant `stack` (the popup opened from a stage header or a card, which it would cover side by side): the two buttons
 * sit one above the other; everywhere else they sit side by side. A non-modal dialog next to its trigger: arrow keys move between its
 * controls, Escape closes it and gives the focus back to the trigger, a click elsewhere closes it. What is listed comes
 * from model.js. */
import { icon } from "../components/icons.js";
import { placePopover } from "../components/popover.js";
import { createSwitch, Switch } from "../components/switch.js";
import { t } from "../i18n.js";
import { innerNote } from "./inner-note.js";
import * as model from "./model.js";

let nextId = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

const FOCUSABLE = "button:not([disabled])";

export class GuardPopover {
  /**
   * @param {{chooseAttach: () => void, toggle: (attachment: object, on: boolean) => Promise<void>,
   *   detach: (attachment: object) => Promise<void>, open: (guard: object) => void, create: () => void}} actions
   */
  constructor(actions) {
    this.actions = actions;
    this.el = make("div", "popover gd-popover");
    this.el.setAttribute("role", "dialog");
    this.el.hidden = true;
    this.el.dataset.guardPopover = "";
    this.trigger = null;
    this.el.addEventListener("keydown", (event) => this.#onKeydown(event));
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.isOpen && !this.el.contains(event.target) && !this.trigger?.contains(event.target)) this.close({ restoreFocus: false });
      },
      true,
    );
    window.addEventListener("resize", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return !this.el.hidden;
  }

  /**
   * Open next to `trigger` (or close it if it is open for that trigger).
   * @param {HTMLElement} trigger
   * @param {{mode: "add"|"list", scope: {type: string, id: string, name: string, inner?: object[], actionHref?: string},
   *   guards: object[], schema: object|null, stack?: boolean}} what
   */
  toggle(trigger, what) {
    if (this.isOpen && this.trigger === trigger) return this.close();
    this.close({ restoreFocus: false });
    this.trigger = trigger;
    this.what = what;
    const host = trigger.closest("dialog[open]") ?? document.body; // a dialog is in the top layer: the popup goes in it
    if (this.el.parentElement !== host) host.append(this.el);
    this.el.classList.toggle("gd-popover--stack", Boolean(what.stack));
    this.el.setAttribute("aria-label", what.mode === "add" ? t("guards.add_a_guard") : t("guards.guards_of", { name: what.scope.name }));
    this.#render();
    this.el.hidden = false;
    this.#place();
    trigger.setAttribute("aria-expanded", "true");
    const first = what.mode === "list" ? this.el.querySelector(".gd-attached__name") : this.el.querySelector(FOCUSABLE);
    (first ?? this.el).focus({ preventScroll: true });
  }

  /** The guards changed (attached, switched, detached, edited): draw again and keep the focus where it was. */
  refresh(guards, schema = this.what?.schema) {
    if (!this.isOpen) return;
    const key = document.activeElement?.closest?.("[data-focus-key]")?.dataset.focusKey;
    this.what = { ...this.what, guards, schema };
    const scope = this.what.scope;
    if (scope.definitionId) scope.inner = model.innerOf(guards, scope.definitionId);
    if (this.what.mode === "list" && !model.attachedTo(guards, scope.type, scope.id).length && !scope.inner?.length) {
      this.close(); // the last guard was detached: the shield is gone, so is its popup
      return;
    }
    this.#render();
    this.#place();
    const again = key && this.el.querySelector(`[data-focus-key="${CSS.escape(key)}"]`);
    (again || this.el.querySelector(FOCUSABLE) || this.el).focus({ preventScroll: true });
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.trigger?.setAttribute("aria-expanded", "false");
    if (restoreFocus && this.trigger?.isConnected) this.trigger.focus({ preventScroll: true });
  }

  #place() {
    const rect = this.trigger.getBoundingClientRect();
    placePopover(this.el, (size) => ({ left: rect.right - size.width, top: rect.bottom + 6, flipTop: rect.top - size.height - 6 }));
  }

  #render() {
    const { mode, scope, guards, schema } = this.what;
    const parts = [];
    if (mode === "add") {
      parts.push(make("p", "popover__caption", t("guards.add_a_guard")));
      const create = make("button", "button button--primary button--sm gd-popover__new");
      create.type = "button";
      create.dataset.focusKey = "new";
      create.dataset.newGuard = "";
      create.append(icon("plus"), document.createTextNode(t("guards.new_menu")));
      create.addEventListener("click", () => {
        this.close({ restoreFocus: false });
        this.actions.create();
      });
      const offered = model.attachable(guards, scope.type, scope.id);
      const attach = make("button", "button button--ghost button--sm gd-popover__attach");
      attach.type = "button";
      attach.dataset.focusKey = "attach";
      attach.dataset.attachGuard = "";
      attach.append(icon("shield"), document.createTextNode(t("guards.attach_guard")));
      attach.setAttribute("aria-disabled", String(!offered.length));
      attach.addEventListener("click", () => {
        if (!offered.length) return;
        this.actions.chooseAttach();
      });
      const row = make("div", "gd-popover__actions");
      row.append(attach, create); // Attach first, the primary New guard on the right
      parts.push(row);
      if (!offered.length) parts.push(make("p", "field__help gd-popover__empty", t("guards.nothing_to_attach")));
    }
    const attached = model.attachedTo(guards, scope.type, scope.id);
    if (attached.length) {
      parts.push(make("p", "popover__caption", mode === "add" ? t("guards.attached_here") : t("guards.guards_of", { name: scope.name })));
      const rows = make("ul", "gd-popover__list gd-popover__attached");
      rows.setAttribute("aria-label", t("guards.attached_here"));
      for (const { attachment, guard } of attached) rows.append(this.#attachedRow(attachment, guard));
      parts.push(rows);
    }
    const inner = scope.inner ?? [];
    if (inner.length) {
      parts.push(make("p", "popover__caption", t("guards.in_the_action")));
      const rows = make("ul", "gd-popover__list gd-popover__inner");
      rows.setAttribute("aria-label", t("guards.in_the_action"));
      for (const { attachment, guard } of inner) rows.append(this.#innerRow(attachment, guard));
      parts.push(rows);
      parts.push(...innerNote(inner, scope.actionHref));
    }
    this.el.replaceChildren(...parts);
  }

  /** A guard inside the action: its name (it opens the guard), what it watches and whether it is off. No switch, no
   * Detach: it is attached to the action, not to this card. */
  #innerRow(attachment, guard) {
    const row = make("li", "gd-attached gd-attached--inner");
    row.dataset.attachmentId = attachment.id;
    row.classList.toggle("is-off", !attachment.enabled);
    const name = make("button", "popover__option gd-attached__name", guard.name);
    name.type = "button";
    name.dataset.focusKey = `inner:${attachment.id}`;
    const label = attachment.enabled ? t("guards.open_guard", { name: guard.name }) : t("guards.open_guard_off", { name: guard.name });
    name.title = label;
    name.setAttribute("aria-label", `${label}: ${model.innerScopeText(attachment)}`);
    name.addEventListener("click", () => {
      this.close({ restoreFocus: false });
      this.actions.open(guard);
    });
    const watches = make("span", "gd-attached__scope field__help", model.innerScopeText(attachment));
    row.append(name, watches);
    return row;
  }

  #attachedRow(attachment, guard) {
    const row = make("li", "gd-attached");
    row.dataset.attachmentId = attachment.id;
    row.classList.toggle("is-off", !attachment.enabled);
    row.classList.toggle("is-unpublished", model.isInactive(attachment));
    const name = make("button", "popover__option gd-attached__name", guard.name);
    name.type = "button";
    name.id = `gd-attached-${(nextId += 1)}`;
    name.dataset.focusKey = `open:${attachment.id}`;
    const opens = attachment.enabled ? t("guards.open_guard", { name: guard.name }) : t("guards.open_guard_off", { name: guard.name });
    const label = model.isInactive(attachment) ? `${opens} (${t("guards.not_published_hint")})` : opens; // a guard nobody published watches nothing
    name.title = label;
    name.setAttribute("aria-label", label);
    name.addEventListener("click", () => {
      this.close({ restoreFocus: false });
      this.actions.open(guard);
    });
    const button = createSwitch();
    button.setAttribute("aria-label", t("guards.switch_name", { name: guard.name }));
    button.setAttribute("aria-checked", String(attachment.enabled));
    button.dataset.focusKey = `switch:${attachment.id}`;
    const toggle = new Switch(button, { onChange: (on) => this.actions.toggle(attachment, on) });
    toggle.on = attachment.enabled; // writes its state into it
    const detach = make("button", "icon-button icon-button--sm is-danger");
    detach.type = "button";
    detach.dataset.focusKey = `detach:${attachment.id}`;
    detach.dataset.detach = "";
    detach.setAttribute("aria-label", t("guards.detach_name", { name: guard.name }));
    detach.title = t("guards.detach_name", { name: guard.name });
    detach.append(icon("x"));
    detach.addEventListener("click", () => this.actions.detach(attachment));
    row.append(button, name, detach);
    return row;
  }

  #onKeydown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // the dialog the popup may sit in stays open
      this.close();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = [...this.el.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest("[hidden]"));
    if (!items.length) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement);
    const next = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[event.key];
    items[(next + items.length) % items.length].focus();
  }
}
