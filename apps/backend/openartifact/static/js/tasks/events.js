/* Server-sent events client. Events: task.created / task.updated / task.moved / task.deleted.
 * EventSource reconnects by itself; events missed while disconnected are not replayed, so
 * every (re)connect calls onOpen so the caller can resync from the REST API. */

const EVENT_TYPES = ["task.created", "task.updated", "task.moved", "task.deleted", "board.resync", "run.updated"];

/**
 * @param {object} options
 * @param {(type: string, data: object) => void} options.onEvent
 * @param {() => void} options.onOpen called on every successful (re)connect
 * @returns {() => void} disconnect function
 */
export function connectEvents({ onEvent, onOpen, url = "/api/events" }) {
  const source = new EventSource(url);
  source.addEventListener("open", onOpen);
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
