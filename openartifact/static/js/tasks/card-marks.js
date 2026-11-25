/* What a card looks like because of the rules (ADR-071): the server derives `marks` for every card
 * (`{done, labels: [{text, tone}], colour: {tone, mode} | null}`) and this draws them, on the board's card, in the card
 * dialog and in the previews of the rules editor. Nothing here is stored on the card: the marks follow the rules. */

export const TONES = ["green", "red", "yellow", "blue", "neutral"];

/** The marks a single rule would give a card (for the preview of that rule); `archive` is drawn as a dashed outline. */
export function marksOfRule(rule) {
  const params = rule.params ?? {};
  switch (rule.action) {
    case "set_done":
      return { done: true, labels: [], colour: null };
    case "label":
      return { done: false, labels: [{ text: params.text || "…", tone: params.tone || "neutral" }], colour: null };
    case "colour":
      return { done: false, labels: [], colour: { tone: params.tone || "neutral", mode: params.mode || "fill" } };
    case "archive":
      return { done: false, labels: [], colour: null, archived: true };
    default:
      return { done: false, labels: [], colour: null };
  }
}

/**
 * Draw `marks` on a card element made from the board's card template (it has `.task-card__title` and
 * `.task-card__labels`).
 * @param {HTMLElement} card
 * @param {{done?: boolean, labels?: {text: string, tone: string}[], colour?: {tone: string, mode: string} | null, archived?: boolean} | null | undefined} marks
 */
export function applyMarks(card, marks) {
  const m = marks ?? {};
  card.classList.toggle("task-card--done", Boolean(m.done));
  card.classList.toggle("task-card--archived", Boolean(m.archived));
  if (m.colour) {
    card.dataset.colourTone = m.colour.tone;
    card.dataset.colourMode = m.colour.mode;
  } else {
    delete card.dataset.colourTone;
    delete card.dataset.colourMode;
  }
  const list = card.querySelector(".task-card__labels");
  if (list) drawLabels(list, m.labels ?? []);
}

/** The label chips of a card in `list` (hidden while there are none). */
export function drawLabels(list, labels) {
  list.replaceChildren(
    ...labels.map(({ text, tone }) => {
      const chip = document.createElement("li");
      chip.className = "card-label";
      chip.dataset.tone = tone;
      chip.textContent = text;
      return chip;
    }),
  );
  list.hidden = labels.length === 0;
}
