"""In-process publish/subscribe for server-sent events (SSE).

The bus lives on ``app.state.event_bus``. It fans every published event out to all
connected SSE clients. It is intentionally process-local: with several worker
processes each worker would only reach its own clients (see arc42 chapter 11).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("openartifact")

# Sentinel placed in a subscriber queue to end its stream.
_CLOSE = None
type _Queue = asyncio.Queue[Event | None]


@dataclass(frozen=True, slots=True)
class Event:
    """A single server-sent event."""

    id: int
    type: str
    data: dict[str, Any]

    def encode(self) -> str:
        """Serialize to the SSE wire format."""
        payload = json.dumps(self.data, separators=(",", ":"))
        return f"id: {self.id}\nevent: {self.type}\ndata: {payload}\n\n"


class EventBus:
    """Fan-out of events to subscriber queues."""

    def __init__(self, max_queue: int = 100) -> None:
        self._max_queue = max_queue
        self._subscribers: set[_Queue] = set()
        self._next_id = 1
        self._closed = False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> _Queue:
        queue: _Queue = asyncio.Queue(maxsize=self._max_queue)
        if self._closed:
            queue.put_nowait(_CLOSE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: _Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> Event:
        """Deliver an event to every subscriber. Never blocks."""
        event = Event(id=self._next_id, type=event_type, data=data)
        self._next_id += 1
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A client that stopped reading must not hold memory forever. Ending its
                # stream makes the browser reconnect and resync from the REST API.
                logger.warning("Dropping slow SSE subscriber")
                self._end(queue)
        return event

    def close(self) -> None:
        """End all streams (application shutdown)."""
        self._closed = True
        for queue in list(self._subscribers):
            self._end(queue)

    def _end(self, queue: _Queue) -> None:
        self._subscribers.discard(queue)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(_CLOSE)


async def event_stream(bus: EventBus, heartbeat: float = 15.0) -> AsyncGenerator[str, None]:
    """Yield SSE frames for one client until the bus closes or the client disconnects.

    A comment line is sent every ``heartbeat`` seconds so proxies keep the
    connection open. Disconnects cancel this generator; ``finally`` unsubscribes.
    """
    queue = bus.subscribe()
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event is _CLOSE:
                return
            yield event.encode()
    finally:
        bus.unsubscribe(queue)
