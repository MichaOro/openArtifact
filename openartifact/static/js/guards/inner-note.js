/* The note under the guards that sit INSIDE the action a card runs (ADR-060): they belong to the action and watch it in every pipeline
 * that uses it, so a pipeline cannot detach them; the note says so and the link opens the action, where Detach is. Used by the card's
 * popup and by the Guards section of the node window. */
import { icon } from "../components/icons.js";
import { t } from "../i18n.js";
import * as model from "./model.js";

/** The note and the link as elements: `[<p class="field__help">, <a class="button">]` (the link only when the action has an address). */
export function innerNote(inner, actionHref) {
  const note = document.createElement("p");
  note.className = "field__help gd-inner-note";
  note.dataset.innerNote = "";
  note.textContent = t("guards.inner_note", { name: model.innerHolderName(inner) || t("guards.inner_this_action") });
  const parts = [note];
  if (actionHref) {
    const open = document.createElement("a");
    open.className = "button button--ghost button--sm gd-popover__open-action";
    open.href = actionHref;
    open.dataset.openAction = "";
    open.dataset.focusKey = "open-action";
    open.append(icon("pencil"), document.createTextNode(t("guards.open_the_action")));
    parts.push(open);
  }
  return parts;
}
