"""Tests for the in-process event bus and the SSE stream generator."""

from __future__ import annotations

import asyncio
import json

from openartifact.events import EventBus, event_stream


async def _collect(stream: object, n: int) -> list[str]:
    """Take the first ``n`` frames from an async generator."""
    frames: list[str] = []
    async for frame in stream:  # type: ignore[attr-defined]
        frames.append(frame)
        if len(frames) == n:
            break
    return frames


def test_publish_assigns_increasing_ids() -> None:
    bus = EventBus()
    assert [bus.publish("a", {}).id, bus.publish("b", {}).id] == [1, 2]


def test_event_wire_format() -> None:
    event = EventBus().publish("task.deleted", {"id": "x"})
    assert event.encode() == 'id: 1\nevent: task.deleted\ndata: {"id":"x"}\n\n'


async def test_every_subscriber_receives_every_event() -> None:
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("task.created", {"n": 1})
    assert (await a.get()).data == {"n": 1}  # type: ignore[union-attr]
    assert (await b.get()).data == {"n": 1}  # type: ignore[union-attr]


async def test_unsubscribed_queue_gets_nothing() -> None:
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.publish("x", {})
    assert q.empty()
    assert bus.subscriber_count == 0


async def test_slow_subscriber_is_dropped_and_stream_ends() -> None:
    bus = EventBus(max_queue=2)
    slow = bus.subscribe()
    fast = bus.subscribe()
    for i in range(3):
        bus.publish("x", {"i": i})
        fast.get_nowait()  # fast client keeps up
    assert bus.subscriber_count == 1  # slow one removed
    assert slow.get_nowait() is None  # ... and told to end its stream


async def test_stream_emits_retry_then_events() -> None:
    bus = EventBus()
    stream = event_stream(bus)
    first = await anext(stream)
    assert first == "retry: 3000\n\n"
    bus.publish("task.created", {"id": "1"})
    frame = await anext(stream)
    assert "event: task.created" in frame
    assert json.loads(frame.split("data: ")[1]) == {"id": "1"}
    await stream.aclose()
    assert bus.subscriber_count == 0  # finally-block unsubscribed


async def test_stream_sends_heartbeat_when_idle() -> None:
    stream = event_stream(EventBus(), heartbeat=0.01)
    frames = await _collect(stream, 3)
    assert frames[0] == "retry: 3000\n\n"
    assert frames[1:] == [": ping\n\n", ": ping\n\n"]
    await stream.aclose()


async def test_close_ends_all_streams() -> None:
    bus = EventBus()
    streams = [event_stream(bus) for _ in range(2)]
    for s in streams:
        await anext(s)  # subscribed
    bus.close()
    for s in streams:
        assert [f async for f in s] == []


async def test_subscribing_after_close_ends_immediately() -> None:
    bus = EventBus()
    bus.close()
    assert [f async for f in event_stream(bus)] == ["retry: 3000\n\n"]


async def test_cancelled_stream_unsubscribes() -> None:
    bus = EventBus()

    async def consume() -> None:
        async for _ in event_stream(bus):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert bus.subscriber_count == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert bus.subscriber_count == 0
