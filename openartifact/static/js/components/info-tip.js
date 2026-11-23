/* A small (i) after a label that explains the field in a tooltip, so the explanation takes no room until it is wanted.
 * It opens on hover, on keyboard focus and on click (touch), closes on leaving, blur and Escape, and is tied to the field
 * it explains with aria-describedby (the tooltip stays in the document, hidden), so assistive technology reads it.
 * One component for every field with a help text. */
import { icon } from "./icons.js";
import { placePopover } from "./popover.js";

let count = 0;
/** Every tooltip made, so one whose label has been drawn away (a panel drawn again) is removed from the document. */
const made = [];

/**
 * @param {string} text the explanation (blank lines separate paragraphs)
 * @param {{label?: string}} [options] what it explains ("Query"), kept as `data-about` so a page can find it
 * @returns {{button: HTMLButtonElement, tip: HTMLElement, id: string}} put `button` after the label; give the field
 *   `aria-describedby=id`
 */
export function infoTip(text, { label = "this field" } = {}) {
  for (let i = made.length - 1; i >= 0; i -= 1) {
    if (!made[i].button.isConnected) {
      made[i].tip.remove();
      made.splice(i, 1);
    }
  }
  const id = `info-tip-${(count += 1)}`;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "info-tip";
  // named by its content, not by the field's label: a label lookup must find the field, not this button
  button.setAttribute("aria-describedby", id);
  button.append(icon("info"), Object.assign(document.createElement("span"), { className: "visually-hidden", textContent: "Help" }));
  button.dataset.about = label;
  const tip = document.createElement("div");
  tip.className = "info-tip__text";
  tip.id = id;
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  for (const paragraph of text.split(/\n{2,}/)) tip.append(Object.assign(document.createElement("p"), { textContent: paragraph.trim() }));
  button.dataset.tipId = id;

  const show = () => {
    // inside an open dialog the tooltip must live in it: the dialog is in the top layer, the body is under it
    const host = button.closest("dialog[open]") ?? document.body;
    if (tip.parentElement !== host) host.append(tip);
    tip.hidden = false;
    const box = button.getBoundingClientRect();
    placePopover(tip, (size) => ({ left: box.left, top: box.bottom + 6, flipTop: box.top - size.height - 6 }));
  };
  const hide = () => {
    tip.hidden = true;
  };
  button.addEventListener("pointerenter", show);
  button.addEventListener("pointerleave", hide);
  button.addEventListener("focus", show);
  button.addEventListener("blur", hide);
  button.addEventListener("click", () => (tip.hidden ? show() : hide()));
  button.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !tip.hidden) {
      event.preventDefault();
      event.stopPropagation(); // the tooltip closes first; a dialog around it stays
      hide();
    }
  });
  // the tooltip lives in the document (hidden) from the start, so aria-describedby always finds it
  queueMicrotask(() => button.isConnected && !tip.isConnected && (button.closest("dialog") ?? document.body).append(tip));
  made.push({ button, tip });
  return { button, tip, id };
}
