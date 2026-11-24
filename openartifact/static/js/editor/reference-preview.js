/* The resolved preview under a field that takes references, and the choice of the card it is previewed with (ADR-064).
 * An editor has no artifact of its own, so "Preview with card" names one; it is kept in this browser and may come from
 * `?card=` in the address. The server resolves only `${card...}`; nodes and variables stay readable placeholders and a
 * secret is never shown. The artifact's own text is never changed, and a run uses the card as it is when it starts. */
import { Combobox } from "../components/combobox.js";
import { request } from "../http.js";
import { t } from "../i18n.js";
import { STORAGE_KEY, cardFromLocation, cardOptions, needsPreview, previewLines } from "./reference-preview-model.js";

const listeners = new Set();
let chosen = null;
let tasks = null;

function remembered() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // a private window: the choice then lasts for this page only
  }
}

chosen = cardFromLocation(window.location.search) ?? remembered();

/** The card the previews use (a number or an id), or null. */
export const previewCard = {
  get: () => chosen,
  set(ref) {
    chosen = ref || null;
    try {
      if (chosen) window.localStorage.setItem(STORAGE_KEY, chosen);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* not remembered */
    }
    for (const listener of listeners) listener();
  },
  subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

/** Show under `input` what its text becomes with the chosen card (nothing while no card is chosen or the text has no reference). */
export function attachReferencePreview(input) {
  const out = document.createElement("pre");
  out.className = "field__preview";
  out.hidden = true;
  out.setAttribute("aria-label", t("editor.reference_preview.resolved"));
  let ticket = 0;
  let timer = 0;
  const run = async () => {
    if (!out.isConnected && input.parentNode) input.insertAdjacentElement("afterend", out); // the control is put in the page after it is built
    const card = previewCard.get();
    const text = input.value;
    if (!needsPreview(text, card)) {
      out.hidden = true;
      return;
    }
    const mine = (ticket += 1);
    try {
      const result = await request("/api/previews/references", { method: "POST", body: JSON.stringify({ text, card }) });
      if (mine !== ticket) return; // a newer answer is on its way
      out.textContent = previewLines(result, (names) => t("editor.reference_preview.unresolved", { names })).join("\n");
      out.dataset.state = result.unresolved.length ? "unresolved" : "ok";
    } catch (error) {
      if (mine !== ticket) return;
      out.textContent = error.status === 404 ? t("editor.reference_preview.card_gone", { card }) : (error.detail ?? error.message);
      out.dataset.state = "error";
    }
    out.hidden = false;
  };
  const soon = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(run, 250);
  };
  input.addEventListener("input", soon);
  input.addEventListener("change", run);
  const forget = previewCard.subscribe(() => (input.isConnected ? run() : forget())); // a panel drawn again leaves its old fields behind
  queueMicrotask(run);
}

/** The "Preview with card" field at the top of a node's settings. */
export function previewSelector() {
  const row = document.createElement("div");
  row.className = "ge-preview-card";
  const label = document.createElement("span");
  label.className = "ge-preview-card__label";
  label.textContent = t("editor.reference_preview.preview_with_card");
  const host = document.createElement("div");
  host.className = "ge-preview-card__field";
  row.append(label, host);
  const box = new Combobox(host, {
    label: t("editor.reference_preview.preview_with_card"),
    options: [],
    placeholder: t("editor.reference_preview.no_card_chosen"),
    onChange: (option) => previewCard.set(option?.value ?? null),
  });
  const fill = (list) => {
    box.setOptions(cardOptions(list));
    const current = previewCard.get();
    if (current && !box.selected) box.choose(box.options.find((o) => o.value === current || o.keywords === current)?.value ?? null);
  };
  (tasks ? Promise.resolve(tasks) : request("/api/tasks").then((list) => (tasks = list))).then(fill, () => {});
  return row;
}
