/* Server-sent events client. Events: task.created / task.updated / task.moved / task.deleted / board.lanes / artifact_fields.changed / agents.changed / providers.changed / settings.changed (and the run, execution and comment events).
 * EventSource reconnects by itself after a lost connection; events missed meanwhile are not
 * replayed, so every (re)connect calls onOpen so the caller can resync from the REST API. A refused
 * connection (the sign-in expired: 401) is not retried by the browser; onClosed tells the caller. */

const EVENT_TYPES = ["task.created", "task.updated", "task.moved", "task.deleted", "board.resync", "board.lanes", "run.updated", "execution.updated", "execution.deleted", "comment.created", "comment.updated", "comment.deleted", "activity.created", "artifact_fields.changed", "agents.changed", "providers.changed", "settings.changed", "graph.changed", "agent.tool_call", "agent.turn"];

/**
 * @param {object} options
 * @param {(type: string, data: object) => void} options.onEvent
 * @param {() => void} options.onOpen called on every successful (re)connect
 * @param {() => void} options.onClosed called when the connection failed for good and will not be retried
 * @returns {() => void} disconnect function
 */
export function connectEvents({ onEvent, onOpen, onClosed, url = "/api/events" }) {
  const source = new EventSource(url);
  source.addEventListener("open", onOpen);
  source.addEventListener("error", () => {
    if (source.readyState === EventSource.CLOSED) onClosed?.();
  });
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      try {
        onEvent(type, JSON.parse(event.data));
      } catch {
        /* ignore a malformed frame; the next resync repairs any drift */
      }
    });
  }
  return () => source.close();
}
