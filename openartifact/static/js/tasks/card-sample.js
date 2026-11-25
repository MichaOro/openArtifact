/* A picture of a card for the previews of the card rules: a copy of the board's own card template, so it is the real
 * card component, drawn with the marks a rule would give it. Nothing to open, move or delete. */
import { applyMarks } from "./card-marks.js";
import { t } from "../i18n.js";

/**
 * @param {object} marks as `marksOfRule` or the server's `marks`
 * @returns {HTMLElement}
 */
export function sampleCard(marks) {
  const card = document.getElementById("task-card-template").content.firstElementChild.cloneNode(true);
  card.querySelector(".task-card__title").textContent = t("cards_rules.sample_title");
  card.querySelector(".task-card__body").textContent = t("cards_rules.sample_body");
  const meta = card.querySelector(".task-card__meta");
  meta.textContent = "";
  meta.hidden = true;
  card.querySelector("[data-delete-task]").remove();
  for (const name of ["tabindex", "aria-haspopup", "aria-keyshortcuts"]) card.removeAttribute(name);
  applyMarks(card, marks);
  return card;
}
