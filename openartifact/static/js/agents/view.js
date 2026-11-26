/* DOM building blocks shared by the agent pages, the agent node's inspector and the agent block of a
 * step. Everything is text (textContent, never innerHTML): prompts, values and provider messages come
 * from users and from outside. */
import { fieldLabel, inputStateText, seconds, showValue, toolCallRows } from "./model.js";
import { t } from "../i18n.js";

export function el(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

export function chip(text, tone = "") {
  const node = el("span", "ag-chip", text);
  if (tone) node.dataset.tone = tone;
  return node;
}

/** A titled block with a preformatted text (a prompt). */
export function block(title, text) {
  const wrap = el("div", "ag-block");
  const pre = el("pre", "ag-pre", text);
  pre.tabIndex = 0;
  pre.setAttribute("aria-label", title);
  wrap.append(el("p", "ag-block__title", title), pre);
  return wrap;
}

function table(caption, heads, rows) {
  const wrap = el("div", "ag-block");
  const scroll = el("div", "ag-scroll");
  const tableEl = el("table", "ag-table");
  tableEl.setAttribute("aria-label", caption);
  const head = el("tr");
  for (const text of heads) {
    const th = el("th", "", text);
    th.scope = "col";
    head.append(th);
  }
  const body = el("tbody");
  for (const cells of rows) {
    const tr = el("tr");
    for (const cell of cells) {
      const td = el("td", "", cell?.text ?? cell ?? "");
      if (cell?.state) td.dataset.state = cell.state;
      tr.append(td);
    }
    body.append(tr);
  }
  const thead = el("thead");
  thead.append(head);
  tableEl.append(thead, body);
  scroll.append(tableEl);
  wrap.append(el("p", "ag-block__title", caption), scroll);
  return wrap;
}

/** The inputs of a preview or of a step: name, where the value comes from, the value or the problem. */
export function inputsTable(inputs) {
  if (!inputs?.length) return null;
  return table(
    t("common.inputs"),
    [t("agents.view.input"), t("agents.view.source"), t("agents.view.value")],
    inputs.map((input) => [
      `${input.name}${input.required ? " *" : ""}`,
      { text: input.source ? `${inputStateText(input.state)}: ${input.source}` : inputStateText(input.state), state: input.state },
      input.state === "error" ? { text: input.error ?? "error", state: "error" } : { text: input.value ?? "", state: input.state },
    ]),
  );
}

/** Every attempt of a step: when, how long, the status, the error and the wait that followed. */
export function attemptsTable(attempts) {
  if (!attempts?.length) return null;
  return table(
    t("agents.view.attempts"),
    ["#", t("agents.view.took"), "HTTP", t("agents.view.result"), t("agents.view.then_waited")],
    attempts.map((a) => [
      String(a.number),
      seconds(a.duration_ms),
      a.http_status == null ? "–" : String(a.http_status),
      a.error ? { text: a.error, state: "error" } : t("agents.view.answered"),
      a.wait_seconds == null ? "" : `${a.wait_seconds} s${a.retry_after != null ? " (Retry-After)" : ""}`,
    ]),
  );
}

/** The tools the model called, turn by turn (nothing when it called none). */
export function toolCallsTable(turns) {
  const rows = toolCallRows(turns);
  if (!rows.length) return null;
  return table(t("agents.view.tool_calls"), [t("agents.view.turn"), t("agents.view.tool"), t("agents.view.arguments"), t("agents.view.result"), t("agents.view.took")], rows);
}

/** A list of problems as warnings (nothing if there are none). */
export function problemList(problems) {
  const list = el("ul", "ag-problems");
  for (const problem of problems ?? []) list.append(el("li", "", problem));
  return list;
}

/** The result of POST .../preview. */
export function previewView(preview) {
  const parts = [];
  if (preview.problems.length) parts.push(problemList(preview.problems));
  parts.push(el("p", "ag-facts", t("agents.view.preview_facts", { provider: preview.provider ?? t("common.none"), model: preview.model ?? t("common.none") })));
  if (preview.system_prompt != null) parts.push(block(t("agent_editor.system_prompt"), preview.system_prompt));
  parts.push(block(t("agent_editor.user_prompt"), preview.user_prompt));
  const inputs = inputsTable(preview.inputs);
  if (inputs) parts.push(inputs);
  return parts;
}

/** The detail of an agent step (see agents/runtime.py): what was sent, with what, and every attempt. */
export function detailView(detail) {
  const wrap = el("div", "ag-detail");
  if (!detail) {
    wrap.append(el("p", "ag-facts", t("agents.view.step_kept_no_detail")));
    return wrap;
  }
  const facts = [
    detail.agent ? t("agents.view.agent_name_version_version", { name: detail.agent.name, version: detail.agent.version }) : null,
    detail.provider ? t("agents.view.provider_name", { name: detail.provider.name }) : null,
    detail.model ? t("agents.view.model_model", { model: detail.model }) : null,
    detail.duration_ms != null ? t("agents.view.took_seconds", { seconds: seconds(detail.duration_ms) }) : null,
  ].filter(Boolean);
  wrap.append(el("p", "ag-facts", facts.join(" · ")));
  const settings = detail.settings ?? {};
  const limits = [
    settings.temperature != null ? t("agents.view.temperature_temperature", { temperature: settings.temperature }) : null,
    settings.max_tokens != null ? t("agents.view.max_tokens_max_tokens", { max_tokens: settings.max_tokens }) : null,
    t("agents.view.request_timeout_request_timeout_seconds", { request_timeout_seconds: settings.request_timeout_seconds }),
    t("agents.view.time_limit_total_timeout_seconds", { total_timeout_seconds: settings.total_timeout_seconds }),
    t("agents.view.retries_retries", { retries: settings.retries }),
    settings.max_iterations != null ? t("agents.view.max_iterations_max_iterations", { max_iterations: settings.max_iterations }) : null,
    settings.token_budget != null ? t("agents.view.token_budget_value", { value: settings.token_budget }) : null,
  ].filter(Boolean);
  wrap.append(el("p", "ag-facts", limits.join(" · ")));
  const overrides = Object.keys(detail.overrides ?? {});
  wrap.append(el("p", "ag-facts", overrides.length ? t("agents.view.set_by_node", { fields: overrides.map(fieldLabel).join(", ") }) : "The node used the agent's settings as they are."));
  if (detail.system_prompt != null) wrap.append(block(t("agents.view.system_prompt_as_sent"), detail.system_prompt));
  if (detail.user_prompt != null) wrap.append(block(t("agents.view.user_prompt_as_sent"), detail.user_prompt));
  for (const part of [inputsTable(detail.inputs), answerView(detail.answer), toolCallsTable(detail.turns), attemptsTable(detail.attempts)]) if (part) wrap.append(part);
  return wrap;
}

/** What the answer format did in this step (ADR-085), in plain words: every call of the report tool, whether the server accepted it and,
 * when not, what was wrong. Null for a step of an agent without an answer format. */
export function answerView(answer) {
  if (!answer || !answer.calls) return null;
  const host = el("div", "ag-answer-view");
  host.append(el("h4", "ag-answer-view__title", t("agents.view.answer_title")));
  const list = el("ol", "ag-answer-view__calls");
  const refused = answer.refused ?? [];
  refused.forEach((problems, index) => list.append(el("li", "", t("agents.view.answer_refused", { n: index + 1, problems: problems.join("; ") }))));
  if (answer.document) list.append(el("li", "", t("agents.view.answer_accepted", { n: refused.length + 1 })));
  host.append(list);
  if (refused.length && answer.document) host.append(el("p", "ag-facts", t("agents.view.answer_repaired")));
  return host;
}

/** A version's configuration in a few lines (the versions list of the agent page). */
export function configFacts(config) {
  const facts = [
    t("agents.view.inputs_value", { value: config.inputs.length ? config.inputs.map((i) => i.name).join(", ") : t("common.none") }),
    t("agents.view.system_prompt_value", { value: showValue(config.system_prompt_enabled, "switch") }),
    config.model ? t("agents.view.model_model", { model: config.model }) : null,
    config.temperature != null ? t("agents.view.temperature_temperature_2", { temperature: config.temperature }) : null,
    config.max_tokens != null ? t("agents.view.max_tokens_max_tokens_2", { max_tokens: config.max_tokens }) : null,
    t("agents.view.retries_retries_2", { retries: config.retries }),
    config.max_iterations != null ? t("agents.view.max_iterations_max_iterations_2", { max_iterations: config.max_iterations }) : null,
  ];
  return facts.filter(Boolean).join(" · ");
}
