/* A navigation entry with sub-entries that a page fills in (templates/components/nav.html, kind "group"): it
 * works like every other entry of a collapsible rail. With the rail open the sub-entries hang below the entry,
 * indented, like the sub-entries of the main navigation (a click opens and closes them); with the rail
 * collapsed a click opens them as a popover beside the icon, the way the Lane and Parent entries open their
 * lists, and the rail stays as narrow as it is. */
import { placePopover } from "./popover.js";

export class NavGroup {
  /**
   * @param {HTMLElement} root the `[data-nav-group]` element
   * @param {import("./collapsible-nav.js").CollapsibleNav} nav the rail it sits in
   * @param {{onLayout?: () => void}} [hooks] onLayout: the rail's height changed (the sub-entries came or went), so a
   *   dialog that is sized from its content can grow or shrink with it
   */
  constructor(root, nav, { onLayout = () => {} } = {}) {
    this.root = root;
    this.nav = nav;
    this.onLayout = onLayout;
    this.toggle = root.querySelector("[data-nav-group-toggle]");
    this.list = root.querySelector("[data-nav-group-list]");
    this.mode = null; // "inline" | "popover" | null (closed)
    this.toggle.addEventListener("click", () => this.#click());
    nav.toggle.addEventListener("click", () => {
      // the rail changed its width: a popover goes, an open list stays only while the rail is open
      if (this.mode) this.close({ restoreFocus: false });
    });
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.mode === "popover" && !this.list.contains(event.target) && !this.toggle.contains(event.target)) this.close({ restoreFocus: false });
      },
      true,
    );
    this.list.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.mode) {
        event.stopPropagation(); // the dialog stays open
        this.close();
      }
    });
  }

  get isOpen() {
    return this.mode !== null;
  }

  /** The sub-entries (the page's own elements). */
  fill(...entries) {
    this.list.replaceChildren(...entries);
    if (this.mode === "inline") this.onLayout();
  }

  #click() {
    if (this.mode) this.close();
    else this.open();
  }

  open() {
    this.mode = this.nav.expanded ? "inline" : "popover";
    this.toggle.setAttribute("aria-expanded", "true");
    this.root.classList.add("is-open");
    this.list.hidden = false;
    if (this.mode === "popover") this.#popover();
    else this.onLayout();
  }

  /** The list leaves the rail (it is clipped there) and floats beside the icon, inside the open dialog. */
  #popover() {
    const host = this.root.closest("dialog[open]") ?? document.body;
    host.append(this.list);
    this.list.classList.add("nav-popover");
    const t = this.toggle.getBoundingClientRect();
    placePopover(this.list, (size) => ({ left: t.left - size.width - 8, top: t.top, flipTop: t.bottom - size.height }));
    (this.list.querySelector("input, select, button") ?? this.list).focus?.({ preventScroll: true });
  }

  close({ restoreFocus = true } = {}) {
    if (!this.mode) return;
    const was = this.mode;
    this.mode = null;
    this.list.hidden = true;
    this.list.classList.remove("nav-popover");
    this.list.style.left = this.list.style.top = "";
    if (this.list.parentElement !== this.root) this.root.append(this.list);
    this.toggle.setAttribute("aria-expanded", "false");
    this.root.classList.remove("is-open");
    if (restoreFocus) this.toggle.focus();
    if (was === "inline") this.onLayout();
  }
}
