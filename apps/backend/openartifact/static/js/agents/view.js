/* DOM building blocks shared by the agent pages, the agent node's inspector and the agent block of a
 * step. Everything is text (textContent, never innerHTML): prompts, values and provider messages come
 * from users and from outside. */
import { fieldLabel, inputStateText, seconds, showValue } from "./model.js";

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
    "Inputs",
    ["Input", "Source", "Value"],
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
    "Attempts",
    ["#", "Took", "HTTP", "Result", "Then waited"],
    attempts.map((a) => [
      String(a.number),
      seconds(a.duration_ms),
      a.http_status == null ? "–" : String(a.http_status),
      a.error ? { text: a.error, state: "error" } : "Answered",
      a.wait_seconds == null ? "" : `${a.wait_seconds} s${a.retry_after != null ? " (Retry-After)" : ""}`,
    ]),
  );
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
  parts.push(el("p", "ag-facts", `Provider: ${preview.provider ?? "none"} · Model: ${preview.model ?? "none"}`));
  if (preview.system_prompt != null) parts.push(block("System prompt", preview.system_prompt));
  parts.push(block("User prompt", preview.user_prompt));
  const inputs = inputsTable(preview.inputs);
  if (inputs) parts.push(inputs);
  return parts;
}

/** The detail of an agent step (see agents/runtime.py): what was sent, with what, and every attempt. */
export function detailView(detail) {
  const wrap = el("div", "ag-detail");
  if (!detail) {
    wrap.append(el("p", "ag-facts", "This step kept no detail."));
    return wrap;
  }
  const facts = [
    detail.agent ? `Agent: ${detail.agent.name} (version ${detail.agent.version})` : null,
    detail.provider ? `Provider: ${detail.provider.name}` : null,
    detail.model ? `Model: ${detail.model}` : null,
    detail.duration_ms != null ? `Took ${seconds(detail.duration_ms)}` : null,
  ].filter(Boolean);
  wrap.append(el("p", "ag-facts", facts.join(" · ")));
  const settings = detail.settings ?? {};
  const limits = [
    settings.temperature != null ? `Temperature ${settings.temperature}` : null,
    settings.max_tokens != null ? `Max tokens ${settings.max_tokens}` : null,
    `Request timeout ${settings.request_timeout_seconds} s`,
    `Time limit ${settings.total_timeout_seconds} s`,
    `Retries ${settings.retries}`,
  ].filter(Boolean);
  wrap.append(el("p", "ag-facts", limits.join(" · ")));
  const overrides = Object.keys(detail.overrides ?? {});
  wrap.append(el("p", "ag-facts", overrides.length ? `Set by the node itself: ${overrides.map(fieldLabel).join(", ")}` : "The node used the agent's settings as they are."));
  if (detail.system_prompt != null) wrap.append(block("System prompt as sent", detail.system_prompt));
  if (detail.user_prompt != null) wrap.append(block("User prompt as sent", detail.user_prompt));
  for (const part of [inputsTable(detail.inputs), attemptsTable(detail.attempts)]) if (part) wrap.append(part);
  return wrap;
}

/** A version's configuration in a few lines (the versions list of the agent page). */
export function configFacts(config) {
  const facts = [
    `Inputs: ${config.inputs.length ? config.inputs.map((i) => i.name).join(", ") : "none"}`,
    `System prompt: ${showValue(config.system_prompt_enabled, "switch")}`,
    config.model ? `Model: ${config.model}` : null,
    config.temperature != null ? `Temperature: ${config.temperature}` : null,
    config.max_tokens != null ? `Max tokens: ${config.max_tokens}` : null,
    `Retries: ${config.retries}`,
  ];
  return facts.filter(Boolean).join(" · ");
}
