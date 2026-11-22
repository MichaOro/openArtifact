/* The run context of an execution as text (pure functions, no DOM). The context holds text from
 * outside (outputs of nodes): it is only ever shown with textContent. */

/** The context as indented JSON; an empty context reads as `{}` parts, never as nothing. */
export function formatContext(context) {
  return JSON.stringify({ vars: context?.vars ?? {}, nodes: context?.nodes ?? {} }, null, 2);
}

/** "2 variables · 3 node results", or "empty". */
export function contextSummary(context) {
  const vars = Object.keys(context?.vars ?? {}).length;
  const nodes = Object.keys(context?.nodes ?? {}).length;
  if (vars + nodes === 0) return "empty";
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  return [plural(vars, "variable"), plural(nodes, "node result")].join(" · ");
}
