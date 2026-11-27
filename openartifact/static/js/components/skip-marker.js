/* The marker of a step a dry run skipped: the "skip forward" icon of old recorders with a tooltip ("Skipped in a dry run: would have waited 3 s"),
 * on the flow page's node card (an entry of the card's icon list), in the path list and in the step detail. Never colour alone: a shape. */
import { icon } from "./icons.js";
import { attachTip } from "./info-tip.js";
import { skippedWhat } from "./skip-marker-model.js";
import { t } from "../i18n.js";

/** The text of the tooltip and the accessible name, or null when the step was not skipped. */
export function skipText(step) {
  const what = skippedWhat(step);
  return what ? t("execution.skip_marker.title", { what }) : null;
}

/** A focusable marker with the shared tooltip, or null when the step was not skipped (the look and the hover are those of the card's other icons). */
export function skipMarker(step) {
  const text = skipText(step);
  if (!text) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button icon-button--quiet icon-button--xs ge-node__skip";
  button.dataset.skipMarker = "";
  button.setAttribute("aria-label", text);
  button.append(icon("skip-forward"));
  button.addEventListener("pointerdown", (event) => event.stopPropagation());
  button.addEventListener("dblclick", (event) => event.stopPropagation());
  button.addEventListener("click", (event) => event.stopPropagation());
  attachTip(button, text);
  return button;
}
