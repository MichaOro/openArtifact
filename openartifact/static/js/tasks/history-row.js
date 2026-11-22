/* The pieces of an execution row that the artifact's History tab and the global execution list share:
 * filling the same cells and the clock that keeps the duration of running executions moving.
 * Everything is textContent; what a click does is up to the caller. */
import { icon } from "../components/icons.js";
import { executionSeconds, formatDuration, formatTime, originLabel } from "./history-format.js";

const TICK_MS = 1000;

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
  element.title = `Started by: ${originLabel(startedBy)}`;
  element.textContent = text;
}

/** The delete button of a row: trash icon, a label naming what it deletes, disabled (not removed, so it
 * keeps its tooltip) while the execution runs. The caller must ignore clicks while aria-disabled. */
export function fillDeleteButton(button, execution, subject) {
  const running = execution.status === "running";
  button.replaceChildren(icon("trash"));
  button.setAttribute("aria-label", `Delete ${subject}`);
  button.setAttribute("aria-disabled", String(running));
  button.title = running ? "Stop it first" : `Delete ${subject}`;
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
