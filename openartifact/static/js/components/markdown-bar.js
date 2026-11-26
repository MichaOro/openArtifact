/* The bar under a long text field (ADR-077): bold, italic, strikethrough, a bullet list and a Preview switch. One component for
 * every editor of a long text (the text of a card, a comment, the prompts of an agent).
 *
 *   new MarkdownBar(textarea, { hint: null, renderText });
 *
 * The bar sits right after the textarea, which stays where it is (its id, its listeners, its form). The buttons do what
 * markdown-edit.js works out for the selection; the edit goes in through the browser's own editing (`insertText`), so the undo of
 * the textarea keeps working; where the browser refuses it, `setRangeText` does it and the text field fires `input` itself.
 * Ctrl/Cmd+B and Ctrl/Cmd+I do the same as the buttons. *Preview* shows the text as it will read (markdown.js; `renderText`
 * draws the plain pieces, like the "#12" links of a card), in place of the field; it is not remembered.
 * The look is css/components.css `.md-bar`; its colours are tokens. */
import { icon } from "./icons.js";
import { renderMarkdown } from "./markdown.js";
import { toggleList, toggleWrap } from "./markdown-edit.js";
import { Switch, createSwitch } from "./switch.js";
import { t } from "../i18n.js";

let counter = 0;

function make(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

export class MarkdownBar {
  /**
   * @param {HTMLTextAreaElement} textarea
   * @param {{hint?: string|null, renderText?: (piece: string, start: number) => Node|string}} [options]
   *   `hint`: the line about Markdown in the bar (default says what is supported; null for a field that has its own hint);
   *   `renderText`: how a piece of plain text is drawn in the preview
   */
  constructor(textarea, { hint = undefined, renderText = undefined } = {}) {
    this.textarea = textarea;
    this.renderText = renderText;
    counter += 1;
    this.element = make("div", "md-bar");
    this.buttons = [
      this.#button("bold", t("components.markdown_bar.bold"), () => this.wrap("**")),
      this.#button("italic", t("components.markdown_bar.italic"), () => this.wrap("*")),
      this.#button("strike", t("components.markdown_bar.strikethrough"), () => this.wrap("~~")),
      this.#button("list", t("components.markdown_bar.list"), () => this.list()),
    ];
    const tools = make("div", "md-bar__tools");
    tools.setAttribute("role", "group");
    tools.setAttribute("aria-label", t("components.markdown_bar.formatting"));
    tools.append(...this.buttons);
    this.element.append(tools);
    if (hint !== null) this.element.append(make("span", "md-bar__hint", hint ?? t("components.markdown_bar.hint")));
    const labelId = `md-preview-${counter}`;
    const preview = make("label", "md-bar__preview");
    preview.append(make("span", "md-bar__preview-label", t("components.markdown_bar.preview")));
    preview.firstChild.id = labelId;
    this.switchButton = createSwitch(labelId);
    this.switch = new Switch(this.switchButton, { onChange: (on) => this.#preview(on) });
    preview.append(this.switchButton);
    this.element.append(preview);
    this.view = make("div", "md-preview");
    this.view.hidden = true;
    this.view.setAttribute("aria-label", t("components.markdown_bar.preview"));
    textarea.after(this.element);
    textarea.after(this.view);
    textarea.addEventListener("keydown", (event) => this.#key(event));
  }

  #button(name, label, run) {
    const button = make("button", "icon-button icon-button--sm");
    button.type = "button";
    button.append(icon(name));
    button.setAttribute("aria-label", label);
    button.title = label;
    button.addEventListener("mousedown", (event) => event.preventDefault()); // the selection must stay in the field
    button.addEventListener("click", run);
    return button;
  }

  /** Bold, italic or strikethrough for the selection. */
  wrap(marker) {
    this.#apply(toggleWrap(this.textarea.value, this.textarea.selectionStart, this.textarea.selectionEnd, marker));
  }

  /** The lines of the selection as a bullet list, or no longer one. */
  list() {
    this.#apply(toggleList(this.textarea.value, this.textarea.selectionStart, this.textarea.selectionEnd));
  }

  #apply({ from, to, insert, selStart, selEnd }) {
    const area = this.textarea;
    area.focus();
    area.setSelectionRange(from, to);
    const done = typeof document.execCommand === "function" && document.execCommand("insertText", false, insert);
    if (!done || area.value.slice(from, from + insert.length) !== insert) {
      area.setRangeText(insert, from, to, "end");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    }
    area.setSelectionRange(selStart, selEnd);
  }

  #key(event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
    const marker = { b: "**", i: "*" }[event.key.toLowerCase()];
    if (!marker || this.textarea.hidden) return;
    event.preventDefault();
    this.wrap(marker);
  }

  #preview(on) {
    this.view.hidden = !on;
    this.textarea.hidden = on;
    this.buttons.forEach((button) => (button.disabled = on));
    if (on) this.view.replaceChildren(renderMarkdown(this.textarea.value, { renderText: this.renderText }));
    else this.textarea.focus();
  }

  /** Back to the field (a dialog that closes or opens anew starts with the field, not the preview). */
  reset() {
    if (!this.switch.on) return;
    this.switch.on = false;
    this.#preview(false);
  }
}
