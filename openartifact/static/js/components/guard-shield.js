/* The shield of a scope that guards watch (ADR-060): ONE small icon where a guard is attached - the editor's canvas (a button that opens
 * the guards of the scope) and the read-only flow of an execution (a plain icon that says whether a guard is watching now).
 * One component for both: the editor makes the button, the flow asks for `readOnly`. The tooltip and the accessible name say how
 * many guards are configured there. */
import { icon } from "./icons.js";
import * as model from "../guards/model.js";

/**
 * @param {number} count the guards at this scope
 * @param {string} scopeName what they watch (part of the accessible name)
 * @param {{readOnly?: boolean}} [options] readOnly: a plain icon, no button (the flow of an execution changes nothing)
 */
export function shieldButton(count, scopeName, { readOnly = false } = {}) {
  const button = document.createElement(readOnly ? "span" : "button");
  button.className = `${readOnly ? "" : "icon-button icon-button--quiet icon-button--xs "}gd-shield`.trim();
  button.dataset.guardShield = "";
  if (readOnly) {
    button.setAttribute("role", "img");
  } else {
    button.type = "button";
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("pointerdown", (event) => event.stopPropagation()); // not the start of dragging a node
    button.addEventListener("dblclick", (event) => event.stopPropagation()); // not the node's settings
  }
  button.append(icon("shield"));
  updateShield(button, count, scopeName);
  return button;
}

export function updateShield(button, count, scopeName) {
  const text = model.shieldText(count);
  button.title = text;
  button.setAttribute("aria-label", scopeName ? `${text}: ${scopeName}` : text);
  button.dataset.count = String(count);
}
