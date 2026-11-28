/* The Execution Trace of an agent step, as questions the panel asks: which rounds there are (heard while the agent runs, or kept in the
 * finished step), in which order and how many of them are drawn, what a round did, how identical calls are grouped, what a search and a
 * filter leave. Pure logic over plain data (no DOM), so the view only draws and the rules are tested on their own.
 *
 * A normalised round: {turn, state: "running"|"done"|"failed", tokens, ms, startedAt, error, wrapUp, finishReason, text, calls}, a call:
 * {tool, node, state: "running"|"ok"|"failed", ms, error}. Nothing but names, counts, states and times: the texts of the messages
 * belong to the next stage. */

/** How many of the newest rounds are drawn before "Show more", and how many more one click adds. */
export const SHOWN = 3;
export const CHUNK = 20;

const CALL_STATE = (call) => (call.state === "running" ? "running" : call.state === "failed" || call.error ? "failed" : "ok");

/**
 * The rounds of an agent that is working, from what the events told (`visit-model.js` `noteAgentTurn`, `noteAgentCall`).
 * @param {{rounds: object[], tokens: number|null}|undefined} agent
 */
export function roundsFromLive(agent) {
  return (agent?.rounds ?? []).map((round) => ({
    turn: round.turn,
    state: round.state === "failed" ? "failed" : round.state === "done" ? "done" : "running",
    tokens: round.tokens ?? null,
    ms: round.ms ?? null,
    startedAt: round.startedAt ?? null,
    error: round.error ?? null,
    wrapUp: round.wrapUp ?? null,
    finishReason: round.finishReason ?? null,
    text: round.text ?? "",
    calls: (round.calls ?? []).map((call) => ({ tool: call.tool, node: call.node ?? "", state: CALL_STATE(call), ms: call.ms ?? null, error: null })),
  }));
}

/**
 * The rounds of a finished agent step, from its `detail.turns` (each turn: attempts, text, finish_reason, tokens, tool_calls, wrap_up,
 * error). A tool call that failed has `error: true` and the message in `result`: the first part of it is kept as the error text.
 * @param {{turns?: object[]}|null|undefined} detail
 */
export function roundsFromDetail(detail) {
  return (detail?.turns ?? []).map((turn, index) => {
    const attempts = turn.attempts ?? [];
    const calls = (turn.tool_calls ?? []).map((call) => ({
      tool: call.tool,
      node: call.node_name ?? "",
      state: call.error ? "failed" : "ok",
      ms: call.duration_ms ?? null,
      error: call.error ? clip(call.result) : null,
    }));
    return {
      turn: index + 1,
      state: turn.error ? "failed" : "done",
      tokens: turn.tokens ?? null,
      ms: attempts.length ? attempts.reduce((sum, a) => sum + (a.duration_ms ?? 0), 0) : null,
      startedAt: attempts[0]?.started_at ?? null,
      error: turn.error ?? null,
      wrapUp: turn.wrap_up ?? null,
      finishReason: turn.finish_reason ?? null,
      text: "", // the message itself is for a later stage; the live events carry a clipped start of it, that stays
      calls,
    };
  });
}

function clip(text, limit = 200) {
  const value = String(text ?? "").replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

/** The numbers over the rounds: how many, how many calls (and failed), the tokens (the total when it is known, else the sum) and the time. */
export function summarize(rounds, { totalTokens = null, durationMs = null } = {}) {
  const calls = rounds.flatMap((r) => r.calls);
  const summed = rounds.some((r) => r.tokens != null) ? rounds.reduce((sum, r) => sum + (r.tokens ?? 0), 0) : null;
  return {
    rounds: rounds.length,
    calls: calls.length,
    failed: calls.filter((c) => c.state === "failed").length,
    tokens: totalTokens ?? summed,
    ms: durationMs ?? (rounds.length && rounds.every((r) => r.ms != null) ? rounds.reduce((sum, r) => sum + r.ms, 0) : null),
  };
}

/**
 * What is drawn: the newest rounds first. Up to `SHOWN + extra` of the newest rounds, then the number of rounds left out, then the
 * FIRST round as an anchor (it holds the request), also when rounds in between are hidden. With few rounds nothing is hidden.
 * @returns {{shown: object[], hidden: number, first: object|null, more: number}} `more`: how many one "Show more" click reveals
 */
export function arrange(rounds, extra = 0) {
  const newest = [...rounds].sort((a, b) => b.turn - a.turn);
  if (newest.length <= SHOWN + extra + 1) {
    const first = newest.length > 1 ? newest[newest.length - 1] : null;
    return { shown: first ? newest.slice(0, -1) : newest, hidden: 0, first, more: 0 };
  }
  const first = newest[newest.length - 1];
  const middle = newest.slice(0, -1);
  const shown = middle.slice(0, SHOWN + extra);
  const hidden = middle.length - shown.length;
  return { shown, hidden, first, more: Math.min(CHUNK, hidden) };
}

/** Calls of one round, consecutive identical ones as one ("get_artifacts" ×3, the time added up, failed or running wins). */
export function groupCalls(calls) {
  const groups = [];
  for (const call of calls) {
    const last = groups[groups.length - 1];
    if (last && last.tool === call.tool && last.node === call.node) {
      last.count += 1;
      last.ms = last.ms == null && call.ms == null ? null : (last.ms ?? 0) + (call.ms ?? 0);
      if (call.state === "failed") last.state = "failed";
      else if (call.state === "running" && last.state !== "failed") last.state = "running";
      last.error = last.error ?? call.error;
    } else {
      groups.push({ ...call, count: 1 });
    }
  }
  return groups;
}

/** Whether a round passes the search (tool names, node names, the error texts) and the filter (`all`, `errors`, `calls`). */
export function matches(round, { query = "", kind = "all" } = {}) {
  const failed = round.state === "failed" || round.calls.some((c) => c.state === "failed");
  if (kind === "errors" && !failed) return false;
  if (kind === "calls" && !round.calls.length) return false;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [round.error, round.wrapUp, ...round.calls.flatMap((c) => [c.tool, c.node, c.error])].filter(Boolean).join(" ").toLowerCase();
  return haystack.includes(needle);
}

/** Whether a round is drawn open by default: the one that works and one that failed. */
export const startsOpen = (round) => round.state === "running" || round.state === "failed" || round.calls.some((c) => c.state === "failed");
