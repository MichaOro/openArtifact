/* The pieces of an execution row that the artifact's History tab and the global execution list share:
 * filling the same cells and the clock that keeps the duration of running executions moving.
 * Everything is textContent; what a click does is up to the caller. */
import { icon } from "../components/icons.js";
import { executionSeconds, formatDuration, formatTime, originLabel } from "./history-format.js";
import { t } from "../i18n.js";

const TICK_MS = 1000;

/** Put a row of the timeline in its place: newest (latest `time`, in ms) first, executions and activity entries in one list. */
export function placeByTime(root, row, time) {
  row.dataset.time = String(time);
  const next = [...root.children].find((other) => other !== row && Number(other.dataset.time) < time);
  if (next !== row.nextElementSibling || row.parentElement !== root) root.insertBefore(row, next ?? null);
}

/** A <time> element showing the local time of a UTC timestamp, with the ISO value as title and datetime. */
export function fillTime(element, iso) {
  element.textContent = formatTime(iso);
  element.title = iso;
  element.dateTime = iso;
}

export const fillDuration = (element, execution) => (element.textContent = formatDuration(executionSeconds(execution)));

/** The origin label; `data-origin` carries the raw value for styling and tests. */
export function fillOrigin(element, startedBy, text = originLabel(startedBy)) {
  element.dataset.origin = startedBy;
  element.title = t("tasks.history_row.started_by_originlabel", { originLabel: originLabel(startedBy) });
  element.textContent = text;
}

/** The base of the row buttons that ask before they act (delete, stop): a glyph, a label naming what it
 * does to what, and a state. A disabled button is not removed, so it keeps its tooltip; the caller must
 * ignore clicks while it is aria-disabled. */
export function fillRowButton(button, { glyph, label, title = label, disabled = false }) {
  button.replaceChildren(icon(glyph));
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-disabled", String(disabled));
  button.title = title;
}

/** The delete button of a row: trash icon, a label naming what it deletes, disabled while the execution runs. */
export function fillDeleteButton(button, execution, subject) {
  const running = execution.status === "running";
  const label = t("tasks.history_row.delete_subject", { subject });
  fillRowButton(button, { glyph: "trash", label, title: running ? t("tasks.history_detail.stop_first") : label, disabled: running });
}

/** The stop button of a row: a square, only there while the execution runs (hidden otherwise). */
export function fillStopButton(button, execution, subject) {
  const running = execution.status === "running";
  button.hidden = !running;
  fillRowButton(button, { glyph: "stop", label: t("tasks.history_row.stop_subject", { subject }) });
}

/** Calls `tick` every second while `update(true)` says something is running; `update(false)` and dispose() stop it. */
export class RunningClock {
  constructor(tick) {
    this.tick = tick;
    this.timer = null;
  }

  update(anyRunning) {
    if (!anyRunning) return this.dispose();
    this.timer ??= window.setInterval(this.tick, TICK_MS);
  }

  dispose() {
    window.clearInterval(this.timer);
    this.timer = null;
  }
}
