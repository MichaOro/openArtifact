import { icon } from "../components/icons.js";
import { t, tn } from "../i18n.js";

/* How the history shows times, durations and statuses: one place for the list and the detail. */

const CHIPS = {
  running: [t("common.running"), "clock"],
  done: [t("common.done"), "check"],
  failed: [t("common.failed"), "x"],
  stopped: [t("common.stopped"), "stop"],
  pass: [t("tasks.history_format.pass"), "check"],
  fail: [t("tasks.history_format.fail"), "x"],
};

/** Local, readable time of a UTC timestamp; "" when there is none. */
export function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}

/** Date and time to the minute ("Nov 27, 2026, 3:04 PM"), for lists and version rows. */
export const formatDateTime = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** The day only ("Nov 27, 2026"), for a card whose one line of facts has no room for the time. */
export const formatDay = (iso) => new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });

/** "0.4 s", "12 s", "3 min 5 s", "2 h 3 min". */
export function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  if (seconds < 10) return `${Math.max(0, Math.round(seconds * 10) / 10)} s`;
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole} s`;
  if (whole < 3600) return `${Math.floor(whole / 60)} min ${whole % 60} s`;
  return `${Math.floor(whole / 3600)} h ${Math.floor((whole % 3600) / 60)} min`;
}

/** Seconds between two timestamps; a missing end means "until now". */
export function secondsBetween(startIso, endIso) {
  if (!startIso) return null;
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  return Math.max(0, (end - new Date(startIso).getTime()) / 1000);
}

/** Duration of an execution summary: the server's, or the elapsed time while it runs. */
export const executionSeconds = (execution) => execution.duration_seconds ?? secondsBetween(execution.started_at, execution.finished_at);

const ORIGINS = { user: t("common.user"), api: "API", mcp: "MCP", system: t("common.system") };

/** Who started an execution, as a label; an unknown origin is shown as it is. */
export const originLabel = (startedBy) => ORIGINS[startedBy] ?? String(startedBy ?? "");

/** "3 executions": the noun is a key of `count.*` (one/other forms). */
export const plural = (n, noun) => tn(`count.${noun.replace(/ /g, "_")}`, n);

/** Fill a chip (markup: .history-chip > [data-chip-icon] + [data-chip-text]) for a status or an outcome. */
export function setChip(chip, status) {
  const [text, name] = CHIPS[status] ?? [status, "clock"];
  chip.dataset.status = status;
  chip.querySelector("[data-chip-icon]").replaceChildren(icon(name));
  chip.querySelector("[data-chip-text]").textContent = text;
}
