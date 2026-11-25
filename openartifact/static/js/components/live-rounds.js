/* The rounds of an agent node while it runs (the flow page, the panel of the running agent): each request to the model with the start
 * of its answer and the tokens, and under it the calls it made, working, ok or failed. It is drawn from the events of the run
 * (execution/visit-model.js `noteAgentTurn`, `noteAgentCall`), so it only holds names, counts and states, never an argument or a
 * result; the step shows those when it is done. Everything is text (textContent).
 *
 *   panel.append(liveRounds(agent, liveSummary(agent)));   // agent: {rounds, tokens}; the summary: execution/visit-model.js
 */
import { icon } from "./icons.js";
import { t } from "../i18n.js";

function el(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

const GLYPH = { ok: "check", failed: "x" };

function callItem(call) {
  const item = el("li", "live-rounds__call");
  item.dataset.state = call.state;
  const mark = el("span", "live-rounds__mark");
  mark.setAttribute("aria-hidden", "true");
  if (GLYPH[call.state]) mark.append(icon(GLYPH[call.state]));
  item.append(mark, el("span", "live-rounds__tool", call.tool));
  const state = call.state === "running" ? t("execution.live_rounds.working") : call.state === "failed" ? t("execution.live_rounds.call_failed") : t("execution.live_rounds.call_ok");
  item.append(el("span", "visually-hidden", ` ${state}`));
  if (call.ms != null) item.append(el("span", "live-rounds__time", `${(call.ms / 1000).toFixed(call.ms < 10000 ? 1 : 0)} s`));
  return item;
}

function roundItem(round) {
  const item = el("li", "live-rounds__round");
  item.dataset.state = round.state;
  item.dataset.turn = String(round.turn);
  const head = el("p", "live-rounds__head");
  const title = round.wrapUp ? t("execution.live_rounds.final_answer", { reason: round.wrapUp }) : t("execution.live_rounds.round", { number: round.turn });
  head.append(el("strong", "", title));
  const status =
    round.state === "running" ? t("execution.live_rounds.asking") : round.state === "failed" ? t("execution.live_rounds.request_failed") : round.tokens != null ? t("execution.live_rounds.tokens", { count: round.tokens }) : "";
  if (status) head.append(el("span", "live-rounds__status", status));
  item.append(head);
  if (round.text) item.append(el("p", "live-rounds__text", round.text));
  if (round.calls.length) {
    const calls = el("ul", "live-rounds__calls");
    calls.append(...round.calls.map(callItem));
    item.append(calls);
  }
  return item;
}

/** The live view of one running agent node (`summary`: its numbers); `null` when nothing was heard of it yet. */
export function liveRounds(agent, summary) {
  if (!summary) return null;
  const root = el("section", "live-rounds");
  root.setAttribute("aria-live", "polite");
  root.dataset.liveRounds = "";
  const facts = [t("execution.live_rounds.rounds", { count: summary.rounds }), t("execution.live_rounds.calls", { count: summary.calls })];
  if (summary.failed) facts.push(t("execution.live_rounds.failed_calls", { count: summary.failed }));
  if (summary.tokens != null) facts.push(t("execution.live_rounds.tokens", { count: summary.tokens }));
  const list = el("ol", "live-rounds__list");
  list.append(...agent.rounds.map(roundItem));
  root.append(el("h5", "live-rounds__title", t("execution.live_rounds.title")), el("p", "live-rounds__facts", facts.join(" · ")), list);
  return root;
}
