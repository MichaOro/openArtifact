/* The legend under a text that marks resolved references (ADR-064 addendum, the personal setting *Mark resolved references*):
 * a closed disclosure that shows the colour of a marked piece and says what it means. One component for every place that
 * marks resolved text (the artifact dialog; the board's cards are too small for one and rely on the same colour).
 *
 *   const legend = new ResolvedLegend();  parent.after(legend.element);  legend.show(true | false);
 *
 * The colour is the token `--color-resolved-ref-bg` (css/components.css `.resolved-legend__mark`), never a character. */
import { t } from "../i18n.js";

export class ResolvedLegend {
  constructor() {
    this.element = document.createElement("details");
    this.element.className = "resolved-legend";
    this.element.hidden = true;
    const summary = document.createElement("summary");
    summary.textContent = t("artifact_dialog.resolved_legend");
    const line = document.createElement("p");
    line.className = "resolved-legend__line";
    const mark = document.createElement("span");
    mark.className = "resolved-legend__mark";
    mark.setAttribute("aria-hidden", "true");
    line.append(mark, document.createTextNode(t("artifact_dialog.resolved_explanation")));
    this.element.append(summary, line);
  }

  /** Shown while a marked text is on screen, hidden otherwise. */
  show(visible) {
    this.element.hidden = !visible;
  }
}
