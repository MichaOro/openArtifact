/* The run context as a collapsible, read-only block (a <details> with the JSON as text and a copy
 * button). Used by the History tab (the context comes with the execution) and the flow page (it is
 * loaded when the block is opened). Everything is text (textContent). */
import { copyText } from "../components/copy-button.js";
import { contextSummary, formatContext } from "./context-format.js";
import { t } from "../i18n.js";

/**
 * @param {object} options
 * @param {string} options.key identifies the block when the view is rebuilt (to keep it open)
 * @param {boolean} [options.open]
 * @param {(() => void)} [options.onOpen] called when the block is opened (to load the context)
 * @returns {HTMLDetailsElement & {show: (context: object) => void}}
 */
export function contextBlock({ key, open = false, onOpen }) {
  const details = document.createElement("details");
  details.className = "history-step__block history-context";
  details.dataset.key = key;
  details.open = open;
  const summary = document.createElement("summary");
  summary.textContent = t("execution_flow.run_context");
  const pre = document.createElement("pre");
  pre.className = "history-step__pre";
  pre.tabIndex = 0;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "button button--ghost button--sm";
  copy.textContent = t("credentials.copy");
  copy.addEventListener("click", async () => {
    copy.textContent = (await copyText(pre.textContent)) ? t("credentials.credentials_page.copied") : t("tasks.context_block.copy_failed");
    window.setTimeout(() => (copy.textContent = t("credentials.copy")), 1500);
  });
  details.append(summary, pre, copy);
  details.show = (context) => {
    summary.textContent = t("tasks.context_block.run_context_contextsummary", { contextSummary: contextSummary(context) });
    pre.textContent = formatContext(context);
  };
  if (onOpen) details.addEventListener("toggle", () => details.open && onOpen());
  return details;
}
