/* The emergency stop's state in the browser (ADR-076): one copy per page that the banner, the switch of the Executions page and
 * anything else subscribe to. It is read from `GET /api/settings/stop`, set with `PUT`, and follows `settings.changed` with a
 * `stop` part, so every open tab shows the same. */
import { request } from "../http.js";
import { connectEvents } from "../tasks/events.js";

const URL = "/api/settings/stop";
let state = null;
const subscribers = new Set();
let connected = false;

function apply(next) {
  state = next;
  for (const subscriber of [...subscribers]) subscriber(state);
}

/** The state as last seen, or `null` before the first answer. */
export const currentStop = () => state;

/** Call `fn(state)` now (when there is a state) and at every change; returns the function that stops it. */
export function subscribeStop(fn) {
  subscribers.add(fn);
  if (state) fn(state);
  return () => subscribers.delete(fn);
}

/** Read the state (the page's first look, and a fresh count of running executions before a question). */
export async function loadStop() {
  apply(await request(URL));
  return state;
}

/** Switch STOP on or off; the server's answer (`aborted` says how many executions it ended) is the new state. */
export async function setStop(active) {
  apply(await request(URL, { method: "PUT", body: JSON.stringify({ active }) }));
  return state;
}

/** Start following the server (once per page): the first read, and what the event stream says; a reconnect reads again. */
export function followStop() {
  if (connected) return;
  connected = true;
  connectEvents({
    onEvent: (type, data) => {
      if (type === "settings.changed" && data.stop) apply(data.stop);
    },
    onOpen: () => loadStop().catch(() => {}), // a missed event is repaired by the read
    onClosed: () => {},
  });
}

/** For tests: forget everything. */
export function resetStop() {
  state = null;
  subscribers.clear();
  connected = false;
}
