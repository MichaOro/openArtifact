/* Server-sent events client. The server sends named events; only the names in EVENT_TYPES get a listener here, any other one is
 * dropped by the browser. tests/test_event_contract.py checks that every name here is published, that every published name is here
 * (or server-only, with a reason) and that every name a page compares against is here.
 * EventSource reconnects by itself after a lost connection; events missed meanwhile are not
 * replayed, so every (re)connect calls onOpen so the caller can resync from the REST API. A refused
 * connection (the sign-in expired: 401) is not retried by the browser; onClosed tells the caller.
 * Every caller of the default URL shares ONE connection per page (the STOP banner of every page listens next to the page's
 * own code, and a browser keeps only six connections per host open across all tabs): the connection closes when the last
 * caller has gone. A custom URL gets a connection of its own. */

const EVENT_TYPES = ["task.created", "task.updated", "task.moved", "task.deleted", "board.resync", "board.lanes", "run.updated", "execution.updated", "execution.deleted", "comment.created", "comment.updated", "comment.deleted", "activity.created", "artifact_fields.changed", "agents.changed", "providers.changed", "settings.changed", "graph.changed", "graph.contract_changed", "agent.tool_call", "agent.turn", "board.updated", "cards.rules.changed", "storage.cleaned", "credentials.changed"];

/** The one connection of the page to the default URL: the source, who listens, and whether it has opened. */
let hub = null;

function openHub(url) {
  const source = new EventSource(url);
  const shared = { source, listeners: new Set(), opened: false, failed: false };
  source.addEventListener("open", () => {
    shared.opened = true;
    for (const listener of [...shared.listeners]) listener.onOpen?.();
  });
  source.addEventListener("error", () => {
    if (source.readyState !== EventSource.CLOSED) return;
    shared.failed = true;
    for (const listener of [...shared.listeners]) listener.onClosed?.();
  });
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return; /* ignore a malformed frame; the next resync repairs any drift */
      }
      for (const listener of [...shared.listeners]) listener.onEvent(type, data);
    });
  }
  return shared;
}

/**
 * @param {object} options
 * @param {(type: string, data: object) => void} options.onEvent
 * @param {() => void} options.onOpen called on every successful (re)connect (at once if the shared connection is already open)
 * @param {() => void} options.onClosed called when the connection failed for good and will not be retried
 * @returns {() => void} disconnect function
 */
export function connectEvents({ onEvent, onOpen, onClosed, url = "/api/events" }) {
  if (url !== "/api/events") return connectAlone({ onEvent, onOpen, onClosed, url });
  hub ??= openHub(url);
  const shared = hub;
  const listener = { onEvent, onOpen, onClosed };
  shared.listeners.add(listener);
  // a caller that joins late hears what it missed: the connection is open, or it was refused before this caller came
  if (shared.opened) queueMicrotask(() => shared.listeners.has(listener) && onOpen?.());
  if (shared.failed) queueMicrotask(() => shared.listeners.has(listener) && onClosed?.());
  return () => {
    shared.listeners.delete(listener);
    if (!shared.listeners.size) {
      shared.source.close();
      if (hub === shared) hub = null;
    }
  };
}

function connectAlone({ onEvent, onOpen, onClosed, url }) {
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
