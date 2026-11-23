import { t } from "../i18n.js";
/* The run context of an execution as text (pure functions, no DOM). The context holds text from
 * outside (outputs of nodes): it is only ever shown with textContent. */

/** The context as indented JSON (vars, card, nodes); an empty context reads as `{}` parts, never as nothing.
 *  `card` (the artifact's parameters at the start) is left out when the artifact had none. */
export function formatContext(context) {
  const card = context?.card ?? {};
  return JSON.stringify({ vars: context?.vars ?? {}, ...(Object.keys(card).length ? { card } : {}), nodes: context?.nodes ?? {} }, null, 2);
}

/** "2 variables · 1 parameter · 3 node results", or "empty". */
export function contextSummary(context) {
  const vars = Object.keys(context?.vars ?? {}).length;
  const card = Object.keys(context?.card ?? {}).length;
  const nodes = Object.keys(context?.nodes ?? {}).length;
  if (vars + card + nodes === 0) return t("common.empty");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  return [plural(vars, "variable"), ...(card ? [plural(card, "parameter")] : []), plural(nodes, "node result")].join(" · ");
}
