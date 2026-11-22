/* The run context as a collapsible, read-only block (a <details> with the JSON as text and a copy
 * button). Used by the History tab (the context comes with the execution) and the flow page (it is
 * loaded when the block is opened). Everything is text (textContent). */
import { contextSummary, formatContext } from "./context-format.js";

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
  summary.textContent = "Run context";
  const pre = document.createElement("pre");
  pre.className = "history-step__pre";
  pre.tabIndex = 0;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "button button--ghost button--sm";
  copy.textContent = "Copy";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(pre.textContent);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Copy failed";
    }
    window.setTimeout(() => (copy.textContent = "Copy"), 1500);
  });
  details.append(summary, pre, copy);
  details.show = (context) => {
    summary.textContent = `Run context (${contextSummary(context)})`;
    pre.textContent = formatContext(context);
  };
  if (onOpen) details.addEventListener("toggle", () => details.open && onOpen());
  return details;
}
