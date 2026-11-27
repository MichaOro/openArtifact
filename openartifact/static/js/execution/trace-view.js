/* The Execution Trace of an agent step, drawn: a header with the numbers and the "Live" pill, a search and a filter, then the rounds,
 * the NEWEST FIRST: the latest three, "Show N more rounds", and the first round at the bottom as an anchor. A round is an accordion
 * row (open: the one that works and one that failed) with the events it held: the model request, each tool call and what came back
 * (names, states and times, never the text of an argument or a result: those come in a later stage), and the answer. Everything is
 * text (textContent). The rules (order, slicing, grouping, filtering) are in `trace-model.js`; this file only draws.
 *
 *   traceView({ rounds, summary, state, live, handlers: {onChange, onJumpLive} })
 *   `state` is kept by the caller between draws: {extra, query, kind, open: Map(turn -> boolean), paused}. */
import { icon } from "../components/icons.js";
import { formatDuration } from "../tasks/history-format.js";
import { arrange, groupCalls, matches, startsOpen, summarize } from "./trace-model.js";
import { t } from "../i18n.js";

const el = (tag, className = "", text = null) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
};

const clock = (value) => (value == null ? "" : new Date(value).toLocaleTimeString(undefined, { hour12: false }));
const seconds = (ms) => (ms == null ? "" : formatDuration(ms / 1000));
const GLYPH = { ok: "check", failed: "x" };

function mark(state) {
  const node = el("span", "live-rounds__mark");
  node.setAttribute("aria-hidden", "true");
  if (GLYPH[state]) node.append(icon(GLYPH[state]));
  return node;
}

function event(kind, state, time) {
  const item = el("li", "trace__event");
  item.dataset.kind = kind;
  if (state) item.dataset.state = state;
  item.append(el("span", "trace__time", time ?? ""));
  return item;
}

/** The events of one round: the model request, then the calls (identical ones grouped) with what came back. */
function events(round, model) {
  const rows = [];
  const request = event("model", round.state === "failed" && !round.calls.length ? "failed" : "", clock(round.startedAt));
  const what = el("span", "trace__what");
  what.append(el("strong", "", t("execution.trace.model_request")));
  const meta = [model, round.tokens != null ? t("execution.live_rounds.tokens", { count: round.tokens }) : ""].filter(Boolean).join(" · ");
  if (meta) what.append(el("span", "trace__meta", meta));
  request.append(what);
  if (round.state === "running" && !round.calls.length) request.append(el("span", "trace__meta trace__waiting", t("execution.trace.waiting")));
  rows.push(request);
  if (round.text) {
    const text = event("text", "", "");
    text.append(el("span", "live-rounds__text", round.text)); // what the events told of the answer (a stage later: the whole message)
    rows.push(text);
  }
  if (round.error) {
    const failed = event("error", "failed", "");
    failed.append(el("span", "trace__what trace__error", `${t("execution.live_rounds.request_failed")}: ${round.error}`));
    rows.push(failed);
  }
  for (const call of groupCalls(round.calls)) {
    const row = event("tool", call.state, "");
    row.classList.add("live-rounds__call");
    const label = el("span", "trace__what");
    label.append(mark(call.state), el("code", "live-rounds__tool", call.count > 1 ? `${call.tool} ×${call.count}` : call.tool));
    if (call.node) label.append(el("span", "trace__meta", call.node));
    const state = call.state === "running" ? t("execution.live_rounds.working") : call.state === "failed" ? t("execution.live_rounds.call_failed") : t("execution.live_rounds.call_ok");
    label.append(el("span", "visually-hidden", ` ${state}`));
    row.append(label);
    if (call.ms != null) row.append(el("span", "live-rounds__time", seconds(call.ms)));
    rows.push(row);
    if (call.state === "ok") {
      const back = event("result", "ok", "");
      back.append(el("span", "trace__what trace__meta", t("execution.trace.result_returned")));
      rows.push(back);
    } else if (call.state === "failed") {
      const back = event("result", "failed", "");
      back.append(el("span", "trace__what trace__error", call.error || t("execution.live_rounds.call_failed")));
      rows.push(back);
    }
  }
  if (round.state === "done" && !round.calls.length && !round.wrapUp) {
    const answer = event("answer", "", "");
    answer.append(el("span", "trace__what", t("execution.trace.final_answer_marker")));
    rows.push(answer);
  }
  return rows;
}

function roundRow(round, view, anchor) {
  const { state, model } = view;
  const item = el("li", "live-rounds__round trace__round");
  item.dataset.state = round.state;
  item.dataset.turn = String(round.turn);
  if (anchor) item.dataset.first = "";
  const body = el("details", "trace__details");
  body.open = state.open.has(round.turn) ? state.open.get(round.turn) : startsOpen(round);
  const head = el("summary", "trace__head-row");
  head.addEventListener("click", () => state.open.set(round.turn, !body.open)); // only what the user chose is kept: a round that was open while it worked closes when it is done
  const status = el("span", "trace__status");
  status.dataset.state = round.state;
  status.setAttribute("aria-hidden", "true");
  if (round.state === "done") status.append(icon("check"));
  else if (round.state === "failed") status.append(icon("x"));
  const title = round.wrapUp ? t("execution.live_rounds.final_answer", { reason: round.wrapUp }) : t("execution.live_rounds.round", { number: round.turn });
  const name = el("strong", "trace__roundname", title);
  if (anchor) name.append(el("span", "trace__anchor", ` · ${t("execution.trace.first_round")}`));
  head.append(status, name);
  const tools = [...new Set(round.calls.map((c) => c.tool))];
  if (tools.length) {
    const chips = el("span", "trace__chips");
    for (const tool of tools.slice(0, 3)) chips.append(el("span", "trace__chip", tool));
    if (tools.length > 3) chips.append(el("span", "trace__chip", `+${tools.length - 3}`));
    head.append(chips);
  }
  const right = el("span", "trace__numbers");
  if (round.state === "running") right.append(el("span", "live-rounds__status", t("execution.live_rounds.asking")));
  else if (round.state === "failed") right.append(el("span", "live-rounds__status", t("execution.live_rounds.request_failed")));
  else if (round.tokens != null) right.append(el("span", "live-rounds__status", t("execution.live_rounds.tokens", { count: round.tokens })));
  if (round.ms != null && round.state !== "running") right.append(el("span", "live-rounds__status", seconds(round.ms)));
  head.append(right);
  const list = el("ul", "trace__events");
  list.append(...events(round, model));
  body.append(head, list);
  item.append(body);
  return item;
}

/**
 * @param {object} view
 * @param {object[]} view.rounds normalised rounds (trace-model.js)
 * @param {{totalTokens?: number|null, durationMs?: number|null}} [view.totals]
 * @param {string} [view.model] the model of the step, when known
 * @param {boolean} view.live the agent is working: the "Live" pill
 * @param {object} view.state {extra, query, kind, open: Map, paused}
 * @param {{onChange: () => void, onJumpLive: () => void}} view.handlers
 */
export function traceView({ rounds, totals = {}, model = "", live, state, handlers }) {
  const root = el("section", "live-rounds trace");
  root.dataset.liveRounds = "";
  root.dataset.trace = "";
  root.setAttribute("aria-label", t("execution.trace.title"));
  const head = el("header", "trace__head");
  head.append(el("h3", "trace__title", t("execution.trace.title")));
  if (live) {
    const pill = el("button", "trace__live");
    pill.type = "button";
    pill.dataset.traceLive = state.paused ? "paused" : "live";
    pill.setAttribute("aria-pressed", String(!state.paused));
    pill.append(el("span", "trace__dot"), el("span", "", state.paused ? t("execution.trace.paused") : t("execution.trace.live")));
    pill.title = state.paused ? t("execution.trace.jump_live") : t("execution.trace.live_help");
    pill.addEventListener("click", () => handlers.onJumpLive());
    head.append(pill);
  }
  root.append(head);
  const sum = summarize(rounds, totals);
  const facts = [t("execution.live_rounds.rounds", { count: sum.rounds }), t("execution.live_rounds.calls", { count: sum.calls })];
  if (sum.failed) facts.push(t("execution.live_rounds.failed_calls", { count: sum.failed }));
  if (sum.tokens != null) facts.push(t("execution.live_rounds.tokens", { count: sum.tokens }));
  if (sum.ms != null) facts.push(seconds(sum.ms));
  root.append(el("p", "live-rounds__facts trace__facts", facts.join(" · ")));

  const tools = el("div", "trace__tools");
  const search = el("input", "field__control trace__search");
  search.type = "search";
  search.placeholder = t("execution.trace.search_placeholder");
  search.setAttribute("aria-label", t("execution.trace.search_label"));
  search.value = state.query;
  search.dataset.traceSearch = "";
  search.addEventListener("input", () => {
    state.query = search.value;
    state.extra = 0;
    handlers.onChange({ focus: "search" });
  });
  const filter = el("select", "field__control trace__filter");
  filter.setAttribute("aria-label", t("execution.trace.filter_label"));
  filter.dataset.traceFilter = "";
  filter.append(new Option(t("execution.trace.filter_all"), "all"), new Option(t("execution.trace.filter_errors"), "errors"), new Option(t("execution.trace.filter_calls"), "calls"));
  filter.value = state.kind;
  filter.addEventListener("change", () => {
    state.kind = filter.value;
    state.extra = 0;
    handlers.onChange({ focus: "filter" });
  });
  tools.append(search, filter);
  root.append(tools);

  const visible = rounds.filter((round) => matches(round, state));
  const list = el("ol", "live-rounds__list trace__list");
  if (!rounds.length) list.append(el("li", "ef-panel__note", t("execution.trace.no_rounds")));
  else if (!visible.length) list.append(el("li", "ef-panel__note", t("execution.trace.no_match")));
  const arranged = arrange(visible, state.extra);
  for (const round of arranged.shown) list.append(roundRow(round, { state, model }, false));
  if (arranged.hidden > 0) {
    const item = el("li", "trace__more");
    const more = el("button", "button button--ghost button--sm", t("execution.trace.show_more", { count: arranged.more }));
    more.type = "button";
    more.dataset.traceMore = "";
    more.title = t("execution.trace.hidden", { count: arranged.hidden });
    more.addEventListener("click", () => {
      state.extra += arranged.more;
      handlers.onChange({ focus: "more" });
    });
    item.append(more, el("span", "trace__meta", t("execution.trace.hidden", { count: arranged.hidden })));
    list.append(item);
  }
  if (arranged.first) list.append(roundRow(arranged.first, { state, model }, true));
  root.append(list);
  return root;
}
