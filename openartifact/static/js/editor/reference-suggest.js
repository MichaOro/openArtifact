/* Suggestions while typing a ${...} reference in a text or lines field of the inspector: typing "${"
 * (or Ctrl+Space inside an open one) opens a small list under the caret; Arrow keys move, Enter or
 * Tab insert, Escape closes it, typing filters, a click inserts. Focus never leaves the field
 * (aria-activedescendant), and a polite live region says how many suggestions there are. The
 * logic is in reference-completion.js; the popup looks like the "#" picker (components.css). */
import { icon } from "../components/icons.js";
import { placePopover } from "../components/popover.js";
import { request } from "../http.js";
import { applyCompletion, candidatesFor, openReference, suggestionsFor } from "./reference-completion.js";
import { typeOf } from "./node-types.js";
import { t, tn } from "../i18n.js";

const SECRETS_MAX_AGE_MS = 5000;
const CARD_FIELDS_MAX_AGE_MS = 1000;
let secretNames = [];
let secretsAt = 0;

/** The names of the stored secrets (names only), kept for the page and fetched again when a field gets focus. */
export async function refreshSecretNames() {
  if (Date.now() - secretsAt < SECRETS_MAX_AGE_MS) return;
  secretsAt = Date.now();
  try {
    secretNames = (await request("/api/secrets")).map((s) => s.name);
  } catch {
    secretsAt = 0; // suggestions are a convenience: try again at the next focus
  }
}

let cardFields = [];
let cardFieldsAt = 0;

/** The artifact fields ({name, label}), offered as ${card.NAME}. Fetched again whenever a list opens or a field gets
 * focus (at most once a second), so a field defined meanwhile is offered without reloading the editor. Resolves
 * true when the list changed. */
export async function refreshCardFields() {
  if (Date.now() - cardFieldsAt < CARD_FIELDS_MAX_AGE_MS) return false;
  cardFieldsAt = Date.now();
  try {
    const next = (await request("/api/artifact-fields")).fields.map((f) => ({ name: f.name, label: f.label }));
    const changed = JSON.stringify(next) !== JSON.stringify(cardFields);
    cardFields = next;
    return changed;
  } catch {
    cardFieldsAt = 0;
    return false;
  }
}

let count = 0;

/**
 * Add suggestions to a text input or textarea.
 * @param {HTMLInputElement|HTMLTextAreaElement} input
 * @param {{nodes: () => object[], exceptId?: string}} source the nodes of the graph being edited
 * @param {{allowSecrets: boolean}} options whether ${secret:NAME} is offered (not in conditions)
 */
export function suggestReferences(input, source, { allowSecrets }) {
  let el = null;
  let status = null;
  let matches = [];
  let active = 0;
  let reference = null;
  const id = `ge-suggest-${(count += 1)}`;
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  if (input.tagName === "INPUT") input.setAttribute("role", "combobox"); // not allowed on a textarea

  const close = () => {
    el?.remove();
    status?.remove();
    el = status = null;
    matches = [];
    input.removeAttribute("aria-activedescendant");
    input.removeAttribute("aria-controls");
    input.setAttribute("aria-expanded", "false");
  };

  const highlight = () => {
    [...el.children].forEach((option, i) => {
      option.setAttribute("aria-selected", String(i === active));
      if (i === active) {
        input.setAttribute("aria-activedescendant", option.id);
        option.scrollIntoView({ block: "nearest" });
      }
    });
  };

  const choose = (index) => {
    const candidate = matches[index];
    if (!candidate || !reference) return;
    const done = applyCompletion(input.value, input.selectionStart, reference, candidate);
    input.value = done.text;
    input.setSelectionRange(done.caret, done.caret);
    close();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const place = () => {
    const box = input.getBoundingClientRect();
    if (input.tagName !== "TEXTAREA") {
      placePopover(el, () => ({ left: box.left, top: box.bottom + 4, flipTop: box.top - el.getBoundingClientRect().height - 4 }));
      return;
    }
    const style = getComputedStyle(input);
    const mirror = document.createElement("div");
    for (const prop of ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "padding", "border", "boxSizing", "tabSize"]) mirror.style[prop] = style[prop];
    mirror.style.cssText += `;position:fixed;visibility:hidden;top:0;left:0;width:${box.width}px;white-space:pre-wrap;overflow-wrap:break-word`;
    mirror.textContent = input.value.slice(0, reference.start);
    const marker = document.createElement("span");
    marker.textContent = "$";
    mirror.append(marker);
    document.body.append(mirror);
    const at = marker.getBoundingClientRect();
    const origin = mirror.getBoundingClientRect();
    mirror.remove();
    const top = box.top + (at.bottom - origin.top) - input.scrollTop + 4;
    placePopover(el, (menu) => ({ left: box.left + (at.left - origin.left) - input.scrollLeft, top, flipTop: top - menu.height - at.height - 8 }));
  };

  const redrawWhenFieldsChange = () => refreshCardFields().then((changed) => changed && document.activeElement === input && update());

  const update = () => {
    reference = input.selectionStart === input.selectionEnd ? openReference(input.value, input.selectionStart) : null;
    if (!reference) return close();
    if (!el) redrawWhenFieldsChange(); // a field added meanwhile is offered without reloading the editor
    matches = suggestionsFor(candidatesFor(source.nodes(), { exceptId: source.exceptId, secrets: secretNames, allowSecrets, cardFields, kinds: typeOf }), reference.query);
    if (!matches.length) return close();
    if (!el) {
      el = document.createElement("div");
      el.className = "popover popover--reference popover--suggest";
      el.id = id;
      el.setAttribute("role", "listbox");
      el.setAttribute("aria-label", t("editor.reference_suggest.references"));
      el.addEventListener("mousedown", (event) => {
        event.preventDefault(); // the field keeps its focus
        const option = event.target.closest("[data-index]");
        if (option) choose(Number(option.dataset.index));
      });
      status = document.createElement("div");
      status.className = "visually-hidden";
      status.setAttribute("aria-live", "polite");
      (input.closest("dialog[open]") ?? document.body).append(el, status); // inside a dialog it would hide behind it
      input.setAttribute("aria-controls", id);
      input.setAttribute("aria-expanded", "true");
    }
    active = 0;
    el.replaceChildren(
      ...matches.map((candidate, i) => {
        const option = document.createElement("div");
        option.id = `${id}-${i}`;
        option.className = "popover__option popover__option--reference";
        option.setAttribute("role", "option");
        option.dataset.index = String(i);
        option.title = candidate.detail;
        const name = document.createElement("span");
        name.textContent = candidate.insert;
        const detail = document.createElement("span");
        detail.className = "popover__number popover__detail";
        detail.textContent = candidate.detail;
        if (candidate.icon) option.append(icon(candidate.icon, "popover__icon"));
        option.append(name, detail);
        return option;
      }),
    );
    status.textContent = tn("editor.reference_suggest.suggestions", matches.length);
    highlight();
    place();
  };

  input.addEventListener("input", update);
  input.addEventListener("click", () => el && update());
  input.addEventListener("blur", close);
  input.addEventListener("focus", () => {
    if (allowSecrets) refreshSecretNames();
    redrawWhenFieldsChange(); // ${card.NAME} is offered wherever references are
  });
  // capture: before the field's own Enter / Tab / Escape handling, which must not see a key the list used
  input.addEventListener(
    "keydown",
    (event) => {
      if (event.key === " " && event.ctrlKey) {
        if (openReference(input.value, input.selectionStart)) {
          event.preventDefault();
          update();
        }
        return;
      }
      if (!el) return;
      const last = matches.length - 1;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        active = event.key === "ArrowDown" ? (active >= last ? 0 : active + 1) : active <= 0 ? last : active - 1;
        highlight();
      } else if (event.key === "Enter" || event.key === "Tab") {
        choose(active);
      } else if (event.key === "Escape") {
        close();
      } else {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
    },
    true,
  );
}
