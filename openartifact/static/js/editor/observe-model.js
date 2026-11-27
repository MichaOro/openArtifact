/* The pure part of the observe mode in the editor (ADR-088): what the server's state means for the bar, the limit fields and the texts. */

export const LIMITS = { days: [1, 365], runs: [1, 100000] };

/** "observing", "ended" (the limit is reached: starts are refused) or "off", from the answer of `GET /api/pipelines/{ref}/observe`. */
export function liveState(read) {
  const state = read?.state;
  if (!state || !read.published?.enabled) return "off";
  if (state.released) return "off";
  if (state.ended) return "ended";
  return state.observing ? "observing" : "off";
}

/** Which entries of the status bar are shown: the eye while it is observing, the stop sign while the observation has ended. */
export function barVisibility(read) {
  const live = liveState(read);
  return { observe: live === "observing", ended: live === "ended" };
}

/**
 * A limit typed in a field: empty is no limit.
 * @param {string} text
 * @param {"days"|"runs"} which
 * @returns {{value: number|null, error: null|"whole"|"range"}}
 */
export function parseLimit(text, which) {
  const typed = String(text ?? "").trim();
  if (!typed) return { value: null, error: null };
  if (!/^\d+$/.test(typed)) return { value: null, error: "whole" };
  const value = Number(typed);
  const [min, max] = LIMITS[which];
  return value < min || value > max ? { value: null, error: "range" } : { value, error: null };
}

/** The setting to send for the draft. */
export function settingOf({ enabled, days = null, runs = null }) {
  return { enabled: Boolean(enabled), days, runs };
}

/** What is live now while it differs from the draft ("observing", "ended" or "off"), else null (they agree: nothing to say). */
export function liveNote(read) {
  return read?.draft_differs ? liveState(read) : null;
}

/** The facts for the popup of the eye: `[key, params]` pairs. */
export function facts(read) {
  const state = read?.state;
  if (!state) return [];
  const out = [];
  if (state.started_at) out.push(["since", { date: state.started_at.slice(0, 10) }]);
  out.push(state.runs ? ["runs_of", { done: state.runs_done, runs: state.runs }] : ["runs", { done: state.runs_done }]);
  if (state.ends_at) out.push(["ends", { date: state.ends_at.slice(0, 10) }]);
  return out;
}
