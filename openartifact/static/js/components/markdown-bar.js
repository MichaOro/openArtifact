/* The bar under a long text field (ADR-077): heading, bold, italic, strikethrough, a bulleted and a numbered list, a quote, code, a code block,
 * a link and a Preview switch. One component for every editor of a long text (the text of a card, a comment, the prompts of an agent).
 *
 *   new MarkdownBar(textarea, { hint: null, renderText });
 *
 * The bar sits right after the textarea, which stays where it is (its id, its listeners, its form). The buttons do what
 * markdown-edit.js works out for the selection; the edit goes in through the browser's own editing (`insertText`), so the undo of
 * the textarea keeps working; where the browser refuses it, `setRangeText` does it and the text field fires `input` itself.
 * Ctrl/Cmd+B and Ctrl/Cmd+I do the same as the buttons, Ctrl/Cmd+K opens the link popup. The heading button goes through
 * "#", "##", "###" and none again. *Link* opens a small popup under its button with two lines, Text and Address (the address is
 * checked: http, https and mailto only; "www.x.de" becomes https://www.x.de); with the caret in a link it edits that link.
 * *Preview* shows the text as it will read (markdown.js; `renderText` draws the plain pieces, like the "#12" links of a card), in
 * place of the field; it is not remembered. No button for a table or an image: a table is written by hand and drawn.
 * The look is css/components.css `.md-bar` and `.md-link-popup`; its colours are tokens. */
import { icon } from "./icons.js";
import { renderMarkdown } from "./markdown.js";
import { cycleHeading, findLink, linkEdit, normalizeAddress, toggleCodeBlock, toggleList, toggleOrdered, toggleQuote, toggleWrap } from "./markdown-edit.js";
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
    this.id = counter;
    this.element = make("div", "md-bar");
    this.linkButton = this.#button("link", t("components.markdown_bar.link"), () => this.openLink());
    this.buttons = [
      this.#button("heading", t("components.markdown_bar.heading"), () => this.#apply(cycleHeading(...this.#selection()))),
      this.#button("bold", t("components.markdown_bar.bold"), () => this.wrap("**")),
      this.#button("italic", t("components.markdown_bar.italic"), () => this.wrap("*")),
      this.#button("strike", t("components.markdown_bar.strikethrough"), () => this.wrap("~~")),
      this.#button("list", t("components.markdown_bar.list"), () => this.list()),
      this.#button("list-ordered", t("components.markdown_bar.list_ordered"), () => this.#apply(toggleOrdered(...this.#selection()))),
      this.#button("quote", t("components.markdown_bar.quote"), () => this.#apply(toggleQuote(...this.#selection()))),
      this.#button("code", t("components.markdown_bar.code"), () => this.wrap("`")),
      this.#button("code-block", t("components.markdown_bar.code_block"), () => this.#apply(toggleCodeBlock(...this.#selection()))),
      this.linkButton,
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
    this.#buildPopup();
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

  #selection() {
    return [this.textarea.value, this.textarea.selectionStart, this.textarea.selectionEnd];
  }

  /** Bold, italic, strikethrough or code for the selection. */
  wrap(marker) {
    this.#apply(toggleWrap(...this.#selection(), marker));
  }

  /** The lines of the selection as a bullet list, or no longer one. */
  list() {
    this.#apply(toggleList(...this.#selection()));
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

  // ── the link popup ─────────────────────────────────────────────────────────────

  #buildPopup() {
    const popup = make("div", "md-link-popup");
    popup.hidden = true;
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", t("components.markdown_bar.link_dialog"));
    const field = (label, input) => {
      const row = make("label", "md-link-popup__field");
      row.append(make("span", "", label), input);
      return row;
    };
    this.linkText = make("input", "field__control");
    this.linkText.type = "text";
    this.linkText.autocomplete = "off";
    this.linkAddress = make("input", "field__control");
    this.linkAddress.type = "text";
    this.linkAddress.autocomplete = "off";
    this.linkAddress.placeholder = "https://";
    this.linkAddress.setAttribute("inputmode", "url");
    this.linkError = make("p", "md-link-popup__error");
    this.linkError.setAttribute("role", "alert");
    const actions = make("div", "md-link-popup__actions");
    const cancel = make("button", "button button--ghost button--sm", t("components.markdown_bar.link_cancel"));
    cancel.type = "button";
    const insert = make("button", "button button--primary button--sm", t("components.markdown_bar.link_insert"));
    insert.type = "button";
    actions.append(cancel, insert);
    popup.append(field(t("components.markdown_bar.link_text"), this.linkText), field(t("components.markdown_bar.link_address"), this.linkAddress), this.linkError, actions);
    cancel.addEventListener("click", () => this.closeLink());
    insert.addEventListener("click", () => this.#insertLink());
    popup.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation(); // the window around the field must not close with it
        this.closeLink();
      } else if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
        event.preventDefault();
        this.#insertLink();
      }
    });
    this.popup = popup;
    this.element.append(popup);
    this.outside = (event) => {
      if (!popup.contains(event.target) && !this.linkButton.contains(event.target)) this.closeLink(false);
    };
  }

  /** Open the link popup under the Link button: the selected text goes into Text; with the caret in a link, that link is edited. */
  openLink() {
    if (!this.popup.hidden) return;
    const [text, start, end] = this.#selection();
    const existing = findLink(text, start);
    this.linkTarget = { start, end, existing };
    this.linkText.value = existing ? existing.label : text.slice(start, end).replace(/\s*\n\s*/g, " ");
    this.linkAddress.value = existing ? existing.address : "";
    this.linkError.textContent = "";
    this.popup.hidden = false;
    this.#place();
    (this.linkText.value ? this.linkAddress : this.linkText).focus();
    document.addEventListener("pointerdown", this.outside, true);
  }

  /**
   * Under the Link button, or above it when there is no room below, within the window. The window of a dialog blurs its backdrop,
   * which makes it the frame of everything that is `position: fixed` inside it: so the place is worked out from where the popup's own
   * (0, 0) lies on the screen, not from the window's corner.
   */
  #place() {
    const popup = this.popup;
    popup.style.left = "0px";
    popup.style.top = "0px";
    const origin = popup.getBoundingClientRect();
    const button = this.linkButton.getBoundingClientRect();
    const margin = 8;
    const x = Math.min(Math.max(margin, button.left), window.innerWidth - origin.width - margin);
    const below = button.bottom + 6;
    const y = below + origin.height > window.innerHeight - margin ? Math.max(margin, button.top - origin.height - 6) : below;
    popup.style.left = `${x - origin.left}px`;
    popup.style.top = `${y - origin.top}px`;
  }

  /** Close the popup; the focus goes back to the field. */
  closeLink(focus = true) {
    if (this.popup.hidden) return;
    this.popup.hidden = true;
    document.removeEventListener("pointerdown", this.outside, true);
    if (focus) this.textarea.focus();
  }

  #insertLink() {
    const checked = normalizeAddress(this.linkAddress.value);
    if (checked.error) {
      this.linkError.textContent = checked.error === "empty" ? t("components.markdown_bar.link_error_empty") : t("components.markdown_bar.link_error_invalid");
      this.linkAddress.focus();
      return;
    }
    const { start, end, existing } = this.linkTarget;
    const edit = linkEdit(this.textarea.value, start, end, this.linkText.value, checked.href, existing);
    this.popup.hidden = true;
    document.removeEventListener("pointerdown", this.outside, true);
    this.#apply(edit);
  }

  #key(event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return;
    const key = event.key.toLowerCase();
    if (this.textarea.hidden) return;
    if (key === "k") {
      event.preventDefault();
      this.openLink();
      return;
    }
    const marker = { b: "**", i: "*" }[key];
    if (!marker) return;
    event.preventDefault();
    this.wrap(marker);
  }

  #preview(on) {
    this.closeLink(false);
    this.view.hidden = !on;
    this.textarea.hidden = on;
    this.buttons.forEach((button) => (button.disabled = on));
    if (on) this.view.replaceChildren(renderMarkdown(this.textarea.value, { renderText: this.renderText }));
    else this.textarea.focus();
  }

  /** Back to the field (a dialog that closes or opens anew starts with the field, not the preview). */
  reset() {
    this.closeLink(false);
    if (!this.switch.on) return;
    this.switch.on = false;
    this.#preview(false);
  }
}
