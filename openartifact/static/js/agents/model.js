/* Agents without the DOM: what a list shows, the settings a node may override, the input mapping of a
 * node and the facts of an agent step. The rules themselves live on the server (agents/resolve.py,
 * agents/render.py); these functions only display what it sent and build what is sent to it. */

/** The settings an agent node may override, in the order they are shown. `kind` picks the control. */
export const OVERRIDES = [
  { key: "user_prompt", label: "User prompt", kind: "lines" },
  { key: "system_prompt_enabled", label: "Use a system prompt", kind: "switch" },
  { key: "system_prompt", label: "System prompt", kind: "lines" },
  { key: "provider_id", label: "Provider", kind: "provider" },
  { key: "model", label: "Model", kind: "model" },
  { key: "temperature", label: "Temperature", kind: "number", min: 0, max: 2, step: 0.1 },
  { key: "max_tokens", label: "Max tokens", kind: "integer", min: 1, max: 8192 },
  { key: "request_timeout_seconds", label: "Request timeout (seconds)", kind: "integer", min: 1, max: 300 },
  { key: "total_timeout_seconds", label: "Time limit of the node (seconds)", kind: "integer", min: 1, max: 1800 },
  { key: "retries", label: "Retries", kind: "integer", min: 0, max: 4 },
  { key: "max_iterations", label: "Max iterations", kind: "integer", min: 1, max: 50 },
];

const LABELS = Object.fromEntries([...OVERRIDES.map((o) => [o.key, o.label]), ["inputs", "Inputs"]]);

/** The name a field has in the interface ("max_tokens" -> "Max tokens"). */
export const fieldLabel = (key) => LABELS[key] ?? key;

/** The chips of an agent: `[text, tone]` with tone "ok", "warn", "bad" or "". */
export function agentChips(agent) {
  const chips = [agent.active ? ["Active", "ok"] : ["Inactive", "bad"]];
  chips.push(agent.published_number == null ? ["Not published", "warn"] : [`v${agent.published_number} published`, ""]);
  if (agent.published_number != null && agent.draft_changed) chips.push(["Draft has changes", "accent"]);
  return chips;
}

/** "Used by 2 nodes" / "Not used by a node". */
export function useText(count) {
  if (!count) return "Not used by a node";
  return `Used by ${count} node${count === 1 ? "" : "s"}`;
}

/** The overrides of a node: the keys of OVERRIDES whose value is set (false and 0 are values). */
export function overridesOf(config) {
  return OVERRIDES.map((o) => o.key).filter((key) => config?.[key] !== null && config?.[key] !== undefined);
}

/** How a value is shown where it is not edited (an inherited value, a version's setting). */
export function showValue(value, kind = "") {
  if (value === null || value === undefined || value === "") return "not set";
  if (kind === "switch" || typeof value === "boolean") return value ? "On" : "Off";
  return String(value);
}

/** `name = value` per line as {name: value}; lines that are not such a pair are left out. */
export function parseMapping(text) {
  const mapping = {};
  for (const line of (text ?? "").split("\n")) {
    const at = line.indexOf("=");
    if (at < 0) continue;
    const name = line.slice(0, at).trim().replace(/^input\./, "");
    if (/^[a-z][a-z0-9_]{0,31}$/.test(name) && !(name in mapping)) mapping[name] = line.slice(at + 1).trim();
  }
  return mapping;
}

/** {name: value} as the text the node stores; inputs without a value are left out (not mapped). */
export function formatMapping(mapping) {
  return Object.entries(mapping)
    .filter(([, value]) => (value ?? "").trim() !== "")
    .map(([name, value]) => `${name} = ${value.trim().replace(/[\r\n]+/g, " ")}`)
    .join("\n");
}

/** The mapping rows of a node: one per declared input, then what is mapped but not declared. */
export function mappingRows(inputs, text) {
  const mapping = parseMapping(text);
  const declared = new Set(inputs.map((i) => i.name));
  return [
    ...inputs.map((input) => ({ ...input, value: mapping[input.name] ?? "", declared: true })),
    ...Object.entries(mapping)
      .filter(([name]) => !declared.has(name))
      .map(([name, value]) => ({ name, type: "string", required: false, value, declared: false })),
  ];
}

/** Whether an address is plain http: the only kind that needs the owner's confirmation. */
export function isPlainHttp(url) {
  return /^\s*http:\/\//i.test(url ?? "");
}

/** The models of a provider that can be chosen (enabled and still listed), by id. */
export function usableModels(provider) {
  return (provider?.models ?? []).filter((m) => m.enabled && m.available).map((m) => m.model_id);
}

/** The provider an agent (or node) ends up with: the named one, else the default one. */
export function providerInEffect(providers, providerId) {
  return providers.find((p) => p.id === providerId) ?? (providerId ? null : providers.find((p) => p.is_default)) ?? null;
}

/** A number of a form field: null when empty, NaN when it is not a number. */
export function numberOf(text) {
  const trimmed = String(text ?? "").trim();
  return trimmed === "" ? null : Number(trimmed);
}

/** What an agent step says in one line: model, tokens, attempts ("small · 18 tokens (11 in, 7 out) · 2 attempts"). */
export function agentFacts(data) {
  if (!data) return [];
  const facts = [];
  if (data.provider && data.model) facts.push(`${data.provider}: ${data.model}`);
  if (data.agent_version != null) facts.push(`Agent version ${data.agent_version}`);
  const usage = data.usage;
  if (usage) {
    const total = usage.total_tokens ?? (usage.prompt_tokens != null && usage.completion_tokens != null ? usage.prompt_tokens + usage.completion_tokens : null);
    const parts = [usage.prompt_tokens != null ? `${usage.prompt_tokens} in` : null, usage.completion_tokens != null ? `${usage.completion_tokens} out` : null].filter(Boolean);
    if (total != null) facts.push(`${total} tokens${parts.length ? ` (${parts.join(", ")})` : ""}`);
    else facts.push("Tokens: not reported by the provider");
  }
  if (data.attempts > 1) facts.push(`${data.attempts} attempts`);
  if (data.finish_reason && data.finish_reason !== "stop") facts.push(`Finish reason: ${data.finish_reason}`);
  return facts;
}

const STATES = {
  mapped: "from the run",
  sample: "example value",
  default: "default",
  unset: "not set (empty)",
  pending: "known when the node runs",
  error: "error",
};

/** How an input got its value, for a table cell. */
export const inputStateText = (state) => STATES[state] ?? state;

/** "3.0 s" from milliseconds. */
export function seconds(ms) {
  return ms == null ? "" : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

/** The rows of the tool calls of an agent step (ADR-040): turn, tool, arguments, result, time. */
export function toolCallRows(turns) {
  return (turns ?? []).flatMap((turn, index) =>
    (turn.tool_calls ?? []).map((call) => [String(index + 1), call.tool, call.arguments, { text: call.result, state: call.error ? "error" : "" }, seconds(call.duration_ms)]),
  );
}
