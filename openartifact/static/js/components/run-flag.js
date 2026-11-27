/* The flag that marks a run that changed nothing: "Observed" for a run of an observed pipeline (ADR-088) and "Dry run" for one started by hand (ADR-086).
 * A run of an observed pipeline is a dry run too, but it says only *Observed*. One place for the history rows, the executions table and the flow page. */
import { t } from "../i18n.js";

/** @param {HTMLElement} el the flag element @param {{dry_run?: boolean, observed?: boolean}} execution */
export function drawRunFlag(el, execution) {
  el.hidden = !execution.dry_run && !execution.observed;
  el.textContent = execution.observed ? t("executions.observed") : t("executions.dry_run");
  el.dataset.kind = execution.observed ? "observed" : "dry";
}
