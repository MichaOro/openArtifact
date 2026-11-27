/* The mark in the toolbar of the pipeline and action editor ("Draft", "v3 published") as a control (ADR-070 addendum): while there is
 * something to do, it is a button with a small arrow that opens a popup next to it with
 *   Publish         makes the draft a new version (the same call as the Versions tab),
 *   Discard draft   after one question in the popup: the draft becomes the published version again.
 * Once the draft equals the published version there is nothing to do and the mark is a plain chip. A refusal of the server is shown in
 * the popup (role alert), the buttons wait while a call runs, and a click elsewhere or Escape closes it. The editor saves every
 * change at once, so there is no unsaved graph; text typed into a field and not left yet is saved first (`beforeAct`).
 *
 *   new PublicationControl(host, {kind, id, beforeAct, onChanged})   host: the element of the mark
 *   control.update(graph)                                            the graph with `published_version` and `draft_changed`
 */
import { icon } from "../components/icons.js";
import { placePopover } from "../components/popover.js";
import { t } from "../i18n.js";
import { discardGraphDraft, publishGraph } from "./api.js";
import { publicationOffer, publicationOf } from "./versions-model.js";
import { editorChip } from "./versions-tab.js";

let nextId = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

const FOCUSABLE = "button:not([disabled])";

export class PublicationControl {
  /**
   * @param {HTMLElement} host
   * @param {{kind: string, id: string, beforeAct?: () => void, onChanged: () => Promise<void>|void}} options `onChanged` is called after
   *   a publication or a discard (the editor reads the graph again, which draws the mark anew)
   */
  constructor(host, { kind, id, beforeAct = () => {}, onChanged }) {
    this.host = host;
    this.kind = kind;
    this.id = id;
    this.beforeAct = beforeAct;
    this.onChanged = onChanged;
    this.graph = null;
    this.step = "offer"; // "offer" or "confirm" (the question before a discard)
    this.busy = false;
    this.trigger = make("button", "ge-state");
    this.trigger.type = "button";
    this.trigger.dataset.publicationTrigger = "";
    this.trigger.setAttribute("aria-haspopup", "dialog");
    this.trigger.setAttribute("aria-expanded", "false");
    this.trigger.addEventListener("click", () => (this.isOpen ? this.close() : this.#open()));
    this.el = make("div", "popover pub-popover");
    this.el.id = `pub-popover-${(nextId += 1)}`;
    this.el.setAttribute("role", "dialog");
    this.el.setAttribute("aria-label", t("graph_versions.popup_label"));
    this.el.hidden = true;
    this.el.dataset.publicationPopover = "";
    this.trigger.setAttribute("aria-controls", this.el.id);
    this.el.addEventListener("keydown", (event) => this.#onKeydown(event));
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (this.isOpen && !this.el.contains(event.target) && !this.trigger.contains(event.target)) this.close({ restoreFocus: false });
      },
      true,
    );
    window.addEventListener("resize", () => this.close({ restoreFocus: false }));
  }

  get isOpen() {
    return !this.el.hidden;
  }

  /** Draw the mark for the graph as it is now; an open popup follows it (and closes when nothing is left to do). */
  update(graph) {
    this.graph = graph;
    const offer = publicationOffer(graph);
    const chip = editorChip(graph);
    if (!offer.publish && !offer.discard) {
      this.close({ restoreFocus: false });
      this.host.replaceChildren(chip);
      return;
    }
    const caret = icon("chevron-down");
    caret.classList.add("ge-state__caret");
    this.trigger.replaceChildren(chip, caret);
    this.trigger.title = chip.title;
    this.trigger.setAttribute("aria-label", `${chip.textContent}: ${t("graph_versions.popup_label")}`);
    if (this.host.firstElementChild !== this.trigger) this.host.replaceChildren(this.trigger);
    if (this.isOpen && !this.busy) {
      if (this.step === "confirm" && !offer.discard) this.step = "offer";
      this.#render();
      this.#place();
    }
  }

  close({ restoreFocus = true } = {}) {
    if (!this.isOpen) return;
    this.el.hidden = true;
    this.step = "offer";
    this.trigger.setAttribute("aria-expanded", "false");
    if (restoreFocus && this.trigger.isConnected) this.trigger.focus({ preventScroll: true });
  }

  #open() {
    if (this.el.parentElement !== document.body) document.body.append(this.el);
    this.step = "offer";
    this.#render();
    this.el.hidden = false;
    this.#place();
    this.trigger.setAttribute("aria-expanded", "true");
    (this.el.querySelector(FOCUSABLE) ?? this.el).focus({ preventScroll: true });
  }

  #place() {
    const rect = this.trigger.getBoundingClientRect();
    placePopover(this.el, (size) => ({ left: rect.left, top: rect.bottom + 6, flipTop: rect.top - size.height - 6 }));
  }

  #render(error = null) {
    const where = publicationOf(this.graph);
    const offer = publicationOffer(this.graph);
    const parts = [];
    const note = make("p", "popover__caption pub-popover__note");
    if (this.step === "confirm") {
      note.textContent = t("graph_versions.discard_confirm", { number: where.number });
      parts.push(note, this.#buttons([this.#button("discard-confirm", t("graph_versions.discard_draft"), "button--danger", () => this.#discard()), this.#button("cancel", t("common.cancel"), "button--ghost", () => this.#back())]));
    } else {
      note.textContent = where.state === "draft" ? t("graph_versions.note_nothing_published") : t("graph_versions.note_changed", { number: where.number });
      const buttons = [];
      if (offer.discard) buttons.push(this.#button("discard", t("graph_versions.discard_draft"), "button--ghost", () => this.#ask()));
      if (offer.publish) buttons.push(this.#button("publish", t("graph_versions.publish"), "button--primary", () => this.#publish()));
      parts.push(note, this.#buttons(buttons));
    }
    const alert = make("p", "field__error pub-popover__error", error ?? "");
    alert.setAttribute("role", "alert");
    alert.hidden = !error;
    this.error = alert;
    parts.push(alert);
    this.el.replaceChildren(...parts);
  }

  #buttons(list) {
    const row = make("div", "pub-popover__actions");
    row.append(...list);
    return row;
  }

  #button(key, text, tone, onClick) {
    const button = make("button", `button ${tone} button--sm`, text);
    button.type = "button";
    button.dataset.publicationAction = key;
    button.addEventListener("click", onClick);
    return button;
  }

  #ask() {
    this.step = "confirm";
    this.#render();
    this.#place();
    (this.el.querySelector('[data-publication-action="cancel"]') ?? this.el).focus({ preventScroll: true });
  }

  #back() {
    this.step = "offer";
    this.#render();
    this.#place();
    (this.el.querySelector(FOCUSABLE) ?? this.el).focus({ preventScroll: true });
  }

  async #publish() {
    await this.#run(() => publishGraph(this.kind, this.id));
  }

  async #discard() {
    await this.#run(() => discardGraphDraft(this.kind, this.id));
  }

  /** One call of the server: the buttons wait, a refusal is shown here, success closes the popup and lets the editor read the graph. */
  async #run(call) {
    if (this.busy) return;
    this.busy = true;
    this.beforeAct();
    for (const button of this.el.querySelectorAll("button")) button.disabled = true;
    try {
      await call();
    } catch (error) {
      this.busy = false;
      this.#render(error?.message || t("graph_versions.action_failed"));
      this.#place();
      (this.el.querySelector(FOCUSABLE) ?? this.el).focus({ preventScroll: true });
      return;
    }
    this.busy = false;
    this.close();
    await this.onChanged();
  }

  #onKeydown(event) {
    if (event.key === "Escape") {
      event.stopPropagation();
      this.close();
    }
  }
}
