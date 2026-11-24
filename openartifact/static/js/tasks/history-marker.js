/* The round marker at the left of every entry of the timeline: its icon and tone say what kind of event it is
 * (activity-model.js `markerOf`). Decoration only: the sentence next to it says the same in words. */
import { icon } from "../components/icons.js";

/** @param {{icon: string, tone: string}} spec */
export function marker(spec) {
  const el = document.createElement("span");
  el.className = "history-marker";
  el.dataset.tone = spec.tone;
  el.setAttribute("aria-hidden", "true");
  el.append(icon(spec.icon));
  return el;
}

/** Put (or replace) the marker in a row: it is the row's first child. */
export function setMarker(row, spec) {
  const old = row.querySelector(":scope > .history-marker");
  const next = marker(spec);
  if (old) old.replaceWith(next);
  else row.prepend(next);
}
