/* The legend of text that marks resolved references (ADR-064 addendum, the personal setting *Mark resolved references*): a small,
 * passive line (the colour of a marked piece and what it means) that sits in the foot of the artifact dialog's rail, next to the
 * button that expands it, and shows only while the rail is expanded. One component for every place that marks resolved text
 * (the artifact dialog; the board's cards are too small for one and rely on the same colour).
 *
 *   const legend = new ResolvedLegend();  foot.append(legend.element);  legend.show(true | false);
 *
 * The colour is the token `--color-resolved-ref-bg` (css/task-dialog.css `.resolved-legend__mark`), never a character. */
import { t } from "../i18n.js";

export class ResolvedLegend {
  constructor() {
    this.element = document.createElement("span");
    this.element.className = "resolved-legend";
    this.element.hidden = true;
    this.element.title = t("artifact_dialog.resolved_legend");
    const mark = document.createElement("span");
    mark.className = "resolved-legend__mark";
    mark.setAttribute("aria-hidden", "true");
    const words = document.createElement("span");
    words.className = "resolved-legend__text";
    words.textContent = t("artifact_dialog.resolved_explanation");
    this.element.append(mark, words);
  }

  /** Shown while a marked text is on screen, hidden otherwise. */
  show(visible) {
    this.element.hidden = !visible;
  }
}
