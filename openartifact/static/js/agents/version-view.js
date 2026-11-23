/* What a published version was, read-only (ADR-049): its prompts, inputs and model & limits as the areas of the
 * editor show them, without controls. The view is filled into the version dialog's tabs; an area the version did
 * not use has no tab. */
import { LIMIT_DEFAULTS, optionsOf } from "./model.js";
import { el } from "./view.js";

const LIMITS = [
  ["provider_id", "Provider", "the default provider"],
  ["model", "Model", "the provider's default model"],
  ["temperature", "Temperature", "the model's own"],
  ["max_tokens", "Max tokens", "the model's own"],
  ["total_timeout_seconds", "Node time limit", "600 s"],
  ["max_iterations", "Max iterations", "10"],
  ["retries", "Retries", "3"],
  ["request_timeout_seconds", "Request timeout", "60 s"],
];

function block(title, text) {
  const wrap = el("div", "ag-block");
  wrap.append(el("span", "ag-block__title", title), el("pre", "ag-pre", text || "(empty)"));
  return wrap;
}

/** The prompts: the user prompt, and the system prompt when the version sent one. */
export function promptsView(config) {
  const host = el("div", "ag-version-view__panel");
  host.append(block("User prompt", config.user_prompt));
  if (config.system_prompt_enabled) host.append(block("System prompt", config.system_prompt));
  else host.append(el("p", "field__help", "No system prompt."));
  return host;
}

/** The inputs as a table, or null when the version had none in effect. */
export function inputsView(config) {
  if (!optionsOf(config).inputs || !config.inputs?.length) return null;
  const table = el("table", "ag-table");
  const head = el("tr");
  for (const title of ["Name", "Type", "Required", "Default", "Description"]) head.append(el("th", "", title));
  table.append(head);
  for (const input of config.inputs) {
    const row = el("tr");
    for (const value of [input.name, input.type, input.required ? "Required" : "Optional", input.required ? "—" : (input.default ?? "—"), input.description || "—"]) row.append(el("td", "", String(value)));
    table.append(row);
  }
  return table;
}

/** Model & limits: every setting with its value, or the default that applied; null when the area was off. */
export function limitsView(config, providers = []) {
  if (!optionsOf(config).limits) return null;
  const list = el("dl", "ag-facts");
  for (const [key, label, fallback] of LIMITS) {
    const value = config[key] ?? LIMIT_DEFAULTS[key];
    const shown = value === null || value === undefined ? `default (${fallback})` : key === "provider_id" ? (providers.find((p) => p.id === value)?.name ?? "(deleted provider)") : String(value);
    const row = el("div");
    row.append(el("dt", "", label), el("dd", value === null || value === undefined ? "ag-row__meta" : "", shown));
    list.append(row);
  }
  return list;
}
