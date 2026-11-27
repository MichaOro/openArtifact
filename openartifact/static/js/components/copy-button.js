/* The copy button for long texts: one small icon button at the top right INSIDE a text block, so a long output, a prompt, the body of a card
 * can be copied whole without scrolling to select it. It copies the full text (never only what is visible), exactly what the page shows (a
 * hidden or masked value is never read), and says so: the icon becomes a tick for a moment ("Copied", also announced politely); where the
 * clipboard is not available it says "Copying is not possible here" instead of failing silently.
 *
 *   attachCopy(pre);                          // the text content of the block; the button appears when the text is long enough
 *   attachCopy(textarea, () => textarea.value, { always: true });   // a field: the current value
 *
 * The block is put into a `.copy-host` whose first child is a `.copy-bar` of no height with the button at its right end; the bar is sticky, so the button stays in
 * view at the block's top right however the block or the page around it scrolls; the block gets right padding (`.has-copy`) so the button never covers text. The button hides itself when the text
 * is too short (copy-model.js `shouldOffer`: more than one line or 80 characters or more); changes follow the block (a field's input, a block's
 * text). The look is css/components.css `.copy-host`. */
import { icon } from "./icons.js";
import { blockText, shouldOffer } from "./copy-model.js";
import { t } from "../i18n.js";

const TICK_MS = 1500;
const MESSAGE_MS = 4000;

/** Put `text` on the clipboard: true when it worked. The Clipboard API first, a hidden field and the copy command as the fallback. */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // not allowed here (an insecure page, a denied permission): try the older way, which works from a click
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
  document.body.append(area);
  area.select();
  let done = false;
  try {
    done = typeof document.execCommand === "function" && document.execCommand("copy");
  } catch {
    done = false;
  }
  area.remove();
  return done;
}

export class CopyButton {
  /**
   * @param {{getText: () => string, label?: string, always?: boolean, minLength?: number}} options
   *   `getText`: the full text, asked when the button is used and when its visibility is decided
   */
  constructor({ getText, label = t("components.copy_button.copy"), always = false, minLength = undefined } = {}) {
    this.getText = getText;
    this.label = label;
    this.options = { always, minLength };
    this.element = document.createElement("button");
    this.element.type = "button";
    this.element.className = "icon-button icon-button--quiet icon-button--xs copy-button";
    this.element.append(icon("copy"));
    this.#setLabel(label);
    this.status = document.createElement("span");
    this.status.className = "copy-button__status visually-hidden";
    this.status.setAttribute("role", "status");
    this.status.setAttribute("aria-live", "polite");
    this.element.addEventListener("click", () => this.copy());
    this.timer = 0;
    this.host = null;
    this.block = null;
    this.refresh();
  }

  #setLabel(text) {
    this.element.title = text;
    this.element.setAttribute("aria-label", text);
  }

  /** Show or hide the button as the text now stands. */
  refresh() {
    const show = shouldOffer(this.getText(), this.options);
    this.element.hidden = !show;
    this.host?.classList.toggle("copy-host--on", show);
    this.block?.classList.toggle("has-copy", show);
    return show;
  }

  /** Copy the full text; the button says what happened. Returns whether it worked. */
  async copy() {
    window.clearTimeout(this.timer);
    const ok = await copyText(this.getText());
    if (ok) {
      this.element.replaceChildren(icon("check"));
      this.element.dataset.state = "copied";
      this.#setLabel(t("components.copy_button.copied"));
      this.status.classList.add("visually-hidden");
      this.status.textContent = t("components.copy_button.copied");
      this.timer = window.setTimeout(() => this.#reset(), TICK_MS);
    } else {
      this.element.dataset.state = "failed";
      this.status.classList.remove("visually-hidden"); // the message is for everyone: shown, and announced
      this.status.textContent = t("components.copy_button.not_possible");
      this.timer = window.setTimeout(() => this.#reset(), MESSAGE_MS);
    }
    return ok;
  }

  #reset() {
    this.element.replaceChildren(icon("copy"));
    delete this.element.dataset.state;
    this.#setLabel(this.label);
    this.status.textContent = "";
    this.status.classList.add("visually-hidden");
  }
}

/**
 * Give a block a copy button. The block is wrapped in a `.copy-host` (in place when it is in the page already; a block that has no parent yet is
 * wrapped too, and the host, `button.host`, is what the caller then appends).
 * @param {HTMLElement} block @param {() => string} [getText] default: the value of a field, else the text content
 * @param {{always?: boolean, minLength?: number, label?: string}} [options] @returns {CopyButton}
 */
export function attachCopy(block, getText = () => blockText(block), options = {}) {
  const button = new CopyButton({ getText, ...options });
  let host = block.parentElement?.classList.contains("copy-host") ? block.parentElement : null;
  if (!host) {
    host = document.createElement("div");
    host.className = "copy-host";
    if (block.parentNode) block.replaceWith(host);
    host.append(block);
  }
  const bar = document.createElement("div"); // a row of no height at the top of the host: it sticks while a long block scrolls past, in whatever scrolls
  bar.className = "copy-bar";
  bar.append(button.status, button.element);
  host.prepend(bar);
  button.host = host;
  button.block = block;
  if ("value" in block) {
    block.addEventListener("input", () => button.refresh());
    block.addEventListener("change", () => button.refresh());
  } else {
    new MutationObserver(() => button.refresh()).observe(block, { childList: true, characterData: true, subtree: true });
  }
  button.refresh();
  return button;
}
