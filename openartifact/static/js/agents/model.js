/* Agents without the DOM: what a list shows, the settings a node may override, the input mapping of a
 * node and the facts of an agent step. The rules themselves live on the server (agents/resolve.py,
 * agents/render.py); these functions only display what it sent and build what is sent to it. */

import { t, tn } from "../i18n.js";
/** The names of the agent's fields as the agent pages and the step details show them. (The node's dialog gets its
 * labels, bounds and kinds from the server's description of the node, GET /api/node-types; only the names live here.) */
const LABELS = {
  user_prompt: t("agent_editor.user_prompt"),
  system_prompt_enabled: t("agents.model.use_system_prompt"),
  system_prompt: t("agent_editor.system_prompt"),
  provider_id: t("common.provider"),
  model: t("agents.editor_page.model"),
  temperature: t("agents.editor_page.temperature"),
  max_tokens: t("agents.editor_page.max_tokens"),
  request_timeout_seconds: t("agents.model.request_timeout_seconds"),
  total_timeout_seconds: t("agents.model.time_limit_node_seconds"),
  retries: t("agents.editor_page.retries"),
  max_iterations: t("agents.editor_page.max_iterations"),
  token_budget: t("agents.editor_page.token_budget"),
  tool_result_chars: t("agents.editor_page.tool_result_limit"),
  inputs: t("common.inputs"),
};

/** The name a field has in the interface ("max_tokens" -> "Max tokens"). */
export const fieldLabel = (key) => LABELS[key] ?? key;

/** The chips of an agent: `[text, tone]` with tone "ok", "warn", "bad" or "". */
export function agentChips(agent) {
  const chips = [agent.active ? [t("common.active"), "ok"] : [t("agents.model.inactive"), "bad"]];
  chips.push(agent.published_number == null ? [t("agents.editor_page.not_published"), "warn"] : [t("agents.editor_page.v_published_number_published", { published_number: agent.published_number }), ""]);
  if (agent.published_number != null && agent.draft_changed) chips.push([t("agents.model.draft_has_changes"), "accent"]);
  return chips;
}

/** "Used by 2 nodes" / "Not used by a node". */
export function useText(count) {
  if (!count) return t("agents.model.not_used_by_node");
  return tn("agents.model.used_by", count);
}

/** The overrides of a node: the settings that inherit from the agent (`inherits`, as the server describes them) whose
 * value the node stores (false and 0 are values). */
export function overridesOf(config, settings) {
  return settings.filter((s) => s.inherits && config?.[s.key] !== null && config?.[s.key] !== undefined).map((s) => s.key);
}

/** How a value is shown where it is not edited (an inherited value, a version's setting). */
export function showValue(value, kind = "") {
  if (value === null || value === undefined || value === "") return "not set";
  if (kind === "switch" || typeof value === "boolean") return value ? t("common.on") : t("common.off");
  return String(value);
}

/** A value as one short line, for a row that names what a setting inherits (a prompt of thousands of characters is not a
 * label): the markup marks go, line breaks become a space, and a longer text is cut with an ellipsis. */
export function preview(value, limit = 70) {
  const flat = String(value).replace(/[*_`#>]+/g, "").replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1).trimEnd()}…` : flat;
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
    .map(([name, value]) => `${name} = ${(value ?? "").trim().replace(/[\r\n]+/g, " ")}`)
    .join("\n");
}

/** The parts of the artifact an input can take (agents/schemas.py ARTIFACT_PARTS), in the order a menu shows them. */
export const ARTIFACT_PARTS = ["title", "body", "title_body", "number", "comments"];

/** What an input of an agent says about where its value comes from: `value` (the node maps it) or `artifact`. Older
 * shapes read the same as the server reads them: no source is a value, the type `artifact` is the artifact with title and body. */
export function sourceOf(input) {
  if (input.source === "artifact" || input.type === "artifact") return "artifact";
  return "value";
}

export function partOf(input) {
  return input.part ?? "title_body";
}

/** The name of a part of the artifact, for people. */
export const partText = (part) => t(`agents.model.part_${part}`);

/**
 * The mapping rows of a node. `value`: one per input the node maps (the inputs that take a value). `artifact`: the inputs
 * the agent fixes to the artifact (shown, never mapped). `stale`: lines the node still has for an input that now comes from
 * the artifact (ignored by a run, shown so they can be removed). `undeclared`: lines for names the agent does not declare.
 */
export function mappingRows(inputs, text) {
  const mapping = parseMapping(text);
  const byName = new Map(inputs.map((input) => [input.name, input]));
  const rows = { value: [], artifact: [], stale: [], undeclared: [] };
  for (const input of inputs) {
    if (sourceOf(input) === "artifact") rows.artifact.push({ ...input, part: partOf(input) });
    else rows.value.push({ ...input, value: mapping[input.name] ?? "" });
  }
  for (const [name, value] of Object.entries(mapping)) {
    const declared = byName.get(name);
    if (!declared) rows.undeclared.push({ name, value });
    else if (sourceOf(declared) === "artifact") rows.stale.push({ name, value });
  }
  return rows;
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
  if (data.agent_version != null) facts.push(t("agents.model.agent_version_agent_version", { agent_version: data.agent_version }));
  const usage = data.usage;
  if (usage) {
    const total = usage.total_tokens ?? (usage.prompt_tokens != null && usage.completion_tokens != null ? usage.prompt_tokens + usage.completion_tokens : null);
    const parts = [usage.prompt_tokens != null ? `${usage.prompt_tokens} in` : null, usage.completion_tokens != null ? `${usage.completion_tokens} out` : null].filter(Boolean);
    if (total != null) facts.push(`${total} tokens${parts.length ? ` (${parts.join(", ")})` : ""}`);
    else facts.push(t("agents.model.tokens_not_reported_by_provider"));
  }
  if (data.attempts > 1) facts.push(`${data.attempts} attempts`);
  if (data.finish_reason && data.finish_reason !== "stop") facts.push(`Finish reason: ${data.finish_reason}`);
  return facts;
}

const STATES = {
  mapped: t("agents.model.from_run"),
  sample: t("agents.model.example_value"),
  default: "default",
  unset: t("agents.model.not_set_empty"),
  pending: t("agents.model.known_when_node_runs"),
  artifact: t("agents.model.from_artifact"),
  stale: t("agents.model.stale_ignored"),
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

/** The settings of "Model & Limits" (agents/schemas.py LIMIT_KEYS); not set is null (ADR-046). */
export const LIMIT_DEFAULTS = { provider_id: null, model: null, temperature: null, max_tokens: null, request_timeout_seconds: null, total_timeout_seconds: null, retries: null, max_iterations: null, token_budget: null, tool_result_chars: null };

/**
 * Which optional areas of an agent are switched on (ADR-045), as the backend reads them: a stored switch wins;
 * an agent from before the switches has Inputs when it declares any and Model & Limits when a value differs
 * from the default.
 */
export function optionsOf(config) {
  const inputs = config.inputs_enabled ?? (config.inputs?.length ?? 0) > 0;
  const limits = config.limits_enabled ?? Object.entries(LIMIT_DEFAULTS).some(([key, value]) => (config[key] ?? null) !== value);
  return { system_prompt: Boolean(config.system_prompt_enabled), inputs, limits };
}

/** The limits of an agent a list shows (`[key, value]`, in this order), only those it sets and only while its own limits are in effect. */
export const PAGE_LIMITS = ["max_iterations", "total_timeout_seconds", "request_timeout_seconds", "retries", "token_budget", "tool_result_chars"];
export function limitRows(config) {
  if (!optionsOf(config).limits) return [];
  return PAGE_LIMITS.filter((key) => config[key] !== null && config[key] !== undefined).map((key) => [key, config[key]]);
}

/** The grey example in a Quick test field of a value input: its default, else its description, else a value of its type. */
export function sampleHint(input) {
  if (input.default !== null && input.default !== undefined && input.default !== "") return `e.g. ${input.default}`;
  if (input.description) return `e.g. ${input.description}`;
  return { number: "e.g. 3", boolean: "e.g. true" }[input.type] ?? t("agents.model.e_g_login_fails_after");
}
