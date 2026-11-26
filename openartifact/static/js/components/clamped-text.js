/* A long text (a prompt, a note) in a panel: it shows its first lines, "Show more" opens all of it, "Copy" puts it on the clipboard.
 * The text is only ever textContent, never markup: what is shown comes from a person or from what ran (ADR-069).
 *
 *   const block = new ClampedText({ text, lines: 6, label: "User prompt" });  parent.append(block.element);
 *
 * `markdown: true` shows the Markdown of the text (ADR-077: bold, italic, strikethrough, lists) as elements built from text nodes; "Copy"
 * still puts the text as written on the clipboard. A prompt is shown as written (no `markdown`), as the model gets it.
 *
 * Without text the block says so (`empty`). The look is css/management.css `.ct`; its colours are tokens. */
import { icon } from "./icons.js";
import { renderMarkdown } from "./markdown.js";
import { t } from "../i18n.js";

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class ClampedText {
  /**
   * @param {{text: string, lines?: number, label?: string, empty?: string}} options
   *   `lines`: how many lines show before "Show more" (the text may be shorter: then there is no button);
   *   `label`: what the text is, for the names of its buttons; `empty`: said when there is no text; `markdown`: draw its Markdown;
   *   `onMore`: when given, "Show more" calls it instead of unfolding the text here (the page opens the text elsewhere)
   */
  constructor({ text, lines = 6, label = "", empty = "–", markdown = false, onMore = null }) {
    this.text = text ?? "";
    this.element = make("div", "ct");
    this.element.style.setProperty("--ct-lines", String(lines));
    if (!this.text.trim()) {
      this.element.append(make("p", "ct__empty", empty));
      return;
    }
    this.body = make("pre", "ct__text", markdown ? null : this.text);
    if (markdown) this.body.append(renderMarkdown(this.text));
    this.body.tabIndex = 0;
    if (label) this.body.setAttribute("aria-label", label);
    this.body.dataset.clamped = "true";
    const bar = make("div", "ct__bar");
    this.more = make("button", "button button--ghost button--sm", t("components.clamped_text.show_more"));
    this.more.type = "button";
    this.more.setAttribute("aria-expanded", "false");
    this.more.addEventListener("click", () => (onMore ? onMore() : this.#toggle()));
    this.copy = make("button", "button button--ghost button--sm");
    this.copy.type = "button";
    this.copy.append(icon("copy"), document.createTextNode(t("components.clamped_text.copy")));
    if (label) this.copy.setAttribute("aria-label", `${t("components.clamped_text.copy")}: ${label}`);
    this.copy.addEventListener("click", () => this.#copy());
    bar.append(this.more, this.copy);
    const box = make("div", "ct__box"); // the frame and padding are on the box: padding on a clamped element shows a piece of the next line
    box.append(this.body);
    this.element.append(box, bar);
    // the button is only there when the text is longer than the lines shown (measured once it is in the page)
    this.more.hidden = typeof ResizeObserver !== "undefined";
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => this.#measure()).observe(this.body);
  }

  #measure() {
    if (this.body.dataset.clamped !== "true") return;
    this.more.hidden = this.body.scrollHeight <= this.body.clientHeight + 1;
  }

  #toggle() {
    const open = this.body.dataset.clamped === "true";
    this.body.dataset.clamped = String(!open);
    this.more.textContent = open ? t("components.clamped_text.show_less") : t("components.clamped_text.show_more");
    this.more.setAttribute("aria-expanded", String(open));
    this.more.hidden = false;
  }

  async #copy() {
    const label = this.copy.lastChild;
    try {
      await navigator.clipboard.writeText(this.text);
      label.textContent = t("components.clamped_text.copied");
    } catch {
      label.textContent = t("components.clamped_text.select_by_hand");
      getSelection().selectAllChildren(this.body);
    }
    window.setTimeout(() => (label.textContent = t("components.clamped_text.copy")), 2000);
  }
}
