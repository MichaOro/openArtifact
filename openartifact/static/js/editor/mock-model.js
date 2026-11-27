/* Mock data of a node (ADR-087): the pure part of the Mock tab. The server decides what a mock may hold; this only turns the form into the body of the
 * request and a stored mock into the form, and reads the data text the way the server will (a JSON object). */

/** The kinds that decide or wait instead of handing over a result take no mock (the server refuses them too). */
const NO_MOCK = new Set(["if", "switch", "timer"]);

/** Whether the node's window gets a Mock tab: a node that leaves a result of its own. */
export function mockable(type, node) {
  return Boolean(type?.produces_result) && !NO_MOCK.has(node.kind);
}

/** Whether the mock of the node is switched on (the pin on the card, the dry run uses it). */
export function mockActive(node) {
  return node?.mock?.enabled === true;
}

/** The form state of a node: what is stored, else a passing, empty result that is still switched off. */
export function formOf(node) {
  const mock = node.mock ?? {};
  return {
    enabled: mock.enabled === true,
    outcome: mock.outcome === "fail" ? "fail" : "pass",
    output: mock.output ?? "",
    data: Object.keys(mock.data ?? {}).length ? JSON.stringify(mock.data, null, 2) : "",
    reason: mock.reason ?? "",
  };
}

/** The text of the data field as an object: `{value}` (empty text is `{}`) or `{error: "invalid"|"not_object"}` for the plain message. */
export function parseData(text) {
  const trimmed = text.trim();
  if (!trimmed) return { value: {} };
  let value;
  try {
    value = JSON.parse(trimmed);
  } catch {
    return { error: "invalid" };
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) return { error: "not_object" };
  return { value };
}

/** The body of the request for a form; `{error}` while the data is not valid (nothing is sent then). */
export function payloadOf(form) {
  const data = parseData(form.data);
  if (data.error) return { error: data.error };
  return { mock: { enabled: form.enabled, outcome: form.outcome, output: form.output, data: data.value, reason: form.reason } };
}

/** A result of the last run (the server's `last-result`) as a mock: switched on, so the dry run uses it. */
export function mockOfResult(found) {
  return { enabled: true, outcome: found.outcome, output: found.output, data: found.data ?? {}, reason: found.reason ?? "" };
}

/** A stored step (history, flow) as a mock: the same shape; the marks of a dry run are not part of it. */
export function mockOfStep(step) {
  const data = Object.fromEntries(Object.entries(step.data ?? {}).filter(([key]) => key !== "mock" && key !== "dry_run"));
  return { enabled: true, outcome: step.outcome === "fail" ? "fail" : "pass", output: step.output ?? "", data, reason: step.reason ?? "" };
}
