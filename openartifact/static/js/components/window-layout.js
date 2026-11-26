/* The layout handle of a manifest window (ADR-063): on every window whose form comes from a YAML manifest, a round button with
 * a grid of nine dots sits on the top edge of the panel, in the middle. Its menu (a variant of the menu component in the
 * layout colour, so it cannot be mistaken for a "..." menu) offers *Edit layout*, *Reset to default* and *Export as YAML*;
 * while the layout is being arranged it offers *Save layout* and *Discard changes*. Editing swaps the window's content for
 * the arrange view (layout-arrange.js); saving puts the order into the instance's layout layer (`PUT /api/ui-layouts/...`)
 * and asks the window to draw itself again from the merged manifest.
 *
 *   const layout = new WindowLayout({panel, content, window: "forms/guard", structure: () => ..., customised: () => bool,
 *     width: 50, reload: async () => {...}, confirm: ({message, confirmLabel, onConfirm}) => ...});
 *   layout.setWindow(...)  layout.dirty  layout.cancel()  layout.guardClose()
 */
import { ActionMenu } from "./action-menu.js";
import { ArrangeView } from "./layout-arrange.js";
import { sameLayout, toLayout } from "./layout-model.js";
import { icon } from "./icons.js";
import { request } from "../http.js";
import { t } from "../i18n.js";

const menu = new ActionMenu();
menu.el.classList.add("menu--layout");

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class WindowLayout {
  /**
   * @param {object} options
   * @param {HTMLElement} options.panel the window's panel: the handle sits on its top edge
   * @param {HTMLElement} options.content what the arrange view replaces while arranging
   * @param {string|null} options.window `forms/<name>` or `nodes/<kind>`; null hides the handle
   * @param {() => object} options.structure the window's structure now (layout-model.js)
   * @param {() => boolean} options.customised whether a layout is saved for this window
   * @param {number|null} [options.width] the window's width in rem
   * @param {() => Promise<void>} options.reload draws the window again from the merged manifest
   * @param {(options: {message: string, confirmLabel: string, onConfirm: () => Promise<unknown>|void}) => void} options.confirm
   */
  constructor({ panel, content, window: name, structure, customised, width = null, reload, confirm }) {
    this.panel = panel;
    this.content = content;
    this.window = name;
    this.structure = structure;
    this.customised = customised;
    this.width = width;
    this.reload = reload;
    this.confirm = confirm;
    this.view = null;
    this.original = null;
    this.host = null;
    this.handle = make("button", "layout-handle");
    this.handle.type = "button";
    this.handle.dataset.layoutHandle = "";
    this.handle.setAttribute("aria-haspopup", "menu");
    this.handle.setAttribute("aria-expanded", "false");
    this.handle.setAttribute("aria-label", t("components.layout.window_layout"));
    this.handle.title = t("components.layout.tooltip");
    this.handle.append(icon("layout"));
    this.handle.addEventListener("click", () => this.#menu());
    panel.append(this.handle);
    this.setWindow(name);
  }

  /** The window (and what it shows) changed: another node kind, or none (the handle is hidden). */
  setWindow(name, options = {}) {
    if (this.editing) this.#leave();
    this.window = name;
    Object.assign(this, options);
    this.handle.hidden = !name;
  }

  get editing() {
    return this.view !== null;
  }

  get dirty() {
    return this.editing && !sameLayout(this.original, this.view.structure);
  }

  /** What a window asks before it closes: with an arrangement not saved it asks to discard it. True: close now. */
  guardClose(closeNow) {
    if (!this.dirty) {
      if (this.editing) this.#leave();
      return true;
    }
    this.confirm({
      message: t("components.layout.discard_question"),
      confirmLabel: t("components.layout.discard"),
      onConfirm: () => {
        this.#leave();
        closeNow();
      },
    });
    return false;
  }

  /** Leave the arrange mode without saving (the window closed, or another window opened). */
  cancel() {
    if (this.editing) this.#leave();
  }

  // ── the menu ────────────────────────────────────────────────────────

  #menu() {
    const items = this.editing
      ? [
          { label: t("components.layout.save"), icon: "check", disabledReason: this.dirty ? undefined : t("components.layout.nothing_changed"), onSelect: () => this.#save() },
          { label: t("components.layout.discard"), icon: "x", onSelect: () => this.#discard() },
        ]
      : [
          { label: t("components.layout.edit"), icon: "pencil", onSelect: () => this.#enter() },
          { label: t("components.layout.reset"), icon: "undo", disabledReason: this.customised() ? undefined : t("components.layout.is_shipped"), onSelect: () => this.#reset() },
          { label: t("components.layout.export"), icon: "arrow-down", onSelect: () => this.#export() },
        ];
    menu.toggle(this.handle, items, t("components.layout.window_layout"), { at: this.#menuAt() });
    if (menu.isOpen) {
      const title = make("p", "menu__title", t("components.layout.menu_title"));
      title.setAttribute("role", "presentation");
      menu.el.prepend(title);
      menu.el.dataset.layoutMenu = this.editing ? "editing" : "idle";
    }
  }

  #menuAt() {
    const box = this.handle.getBoundingClientRect();
    return { x: box.left + box.width / 2 - 100, y: box.bottom + 6 };
  }

  // ── arranging ───────────────────────────────────────────────────────

  #enter() {
    this.original = JSON.parse(JSON.stringify(this.structure()));
    this.host = make("div", "lw-host");
    const banner = make("p", "lw-banner", t("components.layout.banner"));
    banner.setAttribute("role", "status");
    const body = make("div", "lw-body");
    this.host.append(banner, body);
    this.content.before(this.host);
    this.content.hidden = true;
    this.panel.classList.add("is-arranging");
    for (const footer of this.panel.querySelectorAll(".modal__footer")) footer.setAttribute("inert", "");
    this.view = new ArrangeView(body, { structure: this.structure(), width: this.width, onChange: () => this.#changed() });
    this.#changed();
    this.view.host.querySelector(".lw-grip")?.focus({ preventScroll: true });
  }

  #leave() {
    this.host?.remove();
    this.host = null;
    this.view = null;
    this.original = null;
    this.content.hidden = false;
    this.panel.classList.remove("is-arranging");
    for (const footer of this.panel.querySelectorAll(".modal__footer")) footer.removeAttribute("inert");
    this.handle.removeAttribute("data-dirty");
    this.handle.focus({ preventScroll: true });
  }

  #changed() {
    this.handle.toggleAttribute("data-dirty", this.dirty);
  }

  #discard() {
    this.#leave();
  }

  async #save() {
    if (!this.dirty) return;
    const layout = toLayout(this.view.structure);
    try {
      await request(`/api/ui-layouts/${this.window}`, { method: "PUT", body: JSON.stringify(layout) });
    } catch (error) {
      this.#show(error.detail ?? error.message ?? t("components.layout.could_not_save"));
      return;
    }
    this.#leave();
    await this.reload();
  }

  #show(message) {
    const banner = this.host?.querySelector(".lw-banner");
    if (banner) {
      banner.textContent = message;
      banner.dataset.error = "";
    }
  }

  #reset() {
    this.confirm({
      message: t("components.layout.reset_question"),
      confirmLabel: t("components.layout.reset"),
      onConfirm: async () => {
        await request(`/api/ui-layouts/${this.window}`, { method: "DELETE" });
        await this.reload();
      },
    });
  }

  async #export() {
    const response = await fetch(`/api/ui-layouts/${this.window}/export`);
    if (!response.ok) return;
    const link = make("a");
    const url = URL.createObjectURL(await response.blob());
    link.href = url;
    link.download = `${this.window.split("/")[1]}.layout.yaml`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
