/* A round, softly shaded avatar: a circle tinted by a colour token with the icon of a kind in it. It says who is
 * meant without a word next to it (the kind is the accessible name and the tooltip). Today it is drawn by kind
 * (a person at the browser, an API client, an MCP client, a run, the system); the same circle can carry a person's
 * initials later (`initials: "MC"`), with no change to the callers. Colours come from the tokens in avatar.css. */
import { icon } from "./icons.js";

/** The longest initials shown: more would not fit the circle. */
export const MAX_INITIALS = 2;

/**
 * What the circle shows: the initials when there are any, else the icon of the kind.
 * Pure (no document access), so it is tested on its own: tests/js/avatar.test.mjs.
 * @param {{icon?: string, initials?: string | null}} spec
 * @returns {{initials: string} | {icon: string}}
 */
export function faceOf({ icon: name = "user", initials = null } = {}) {
  const text = [...String(initials ?? "").trim()].slice(0, MAX_INITIALS).join("").toUpperCase();
  return text ? { initials: text } : { icon: name };
}

/**
 * The avatar element.
 * @param {object} options
 * @param {string} options.kind the kind of who it is (user, api, mcp, run, system; any other gets the neutral tint): the
 *   tint, `data-kind`
 * @param {string} options.label what it is called for assistive technology and the tooltip ("User", "API"; not the name)
 * @param {string} [options.icon] an icon of icons.html, drawn when there are no initials
 * @param {string | null} [options.initials] one or two letters, e.g. of a person's name: shown instead of the icon
 */
export function avatar({ kind, label, icon: iconName, initials = null }) {
  const el = document.createElement("span");
  el.className = "avatar";
  el.dataset.kind = kind;
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", label);
  el.title = label;
  const face = faceOf({ icon: iconName, initials });
  if ("initials" in face) el.textContent = face.initials;
  else el.append(icon(face.icon));
  return el;
}
