"""The technical card of a graph (ADR-089): a dry run does not need a card of the board, but an execution belongs to one (its number, its
history, its address), so a dry run started without a card belongs to a hidden one, made when it is first needed and used again.

A technical card is in no list, count or rule of the board: every query that lists or counts cards leaves it out with
:func:`visible`. It is reached by its id or number only (the history and the execution page address it like any card)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Graph, Lane, Task
from openartifact.tasks.repository import TaskRepository


def visible() -> ColumnElement[bool]:
    """The condition every listing and count of cards adds: not a technical card."""
    return Task.technical.is_(False)


def only_visible(query: Select[Any]) -> Select[Any]:
    """``query`` (over ``Task``) without the technical cards."""
    return query.where(visible())


async def card_of_graph(session: AsyncSession, graph: Graph) -> Task:
    """The technical card of ``graph`` (a pipeline or an action), made when there is none. It sits in the first lane (a card needs one;
    nobody sees it there) and names the graph in ``pipeline_id`` (a dry run does not change a card's own target, so the column is free)."""
    found = await session.scalar(
        select(Task).where(Task.technical.is_(True), Task.pipeline_id == graph.id)
    )
    if found is not None:
        return found
    lane = await session.scalar(select(Lane.key).order_by(Lane.position).limit(1))
    if lane is None:
        raise RuntimeError("the board has no lane")
    repo = TaskRepository(session)
    task = Task(
        id=str(uuid.uuid4()),
        number=await repo._next_number(),
        title=f"Dry runs of {graph.name}",
        status=lane,
        position=0.0,
        pipeline_id=graph.id,
        created_by="user",
        technical=True,
    )
    session.add(task)
    await session.flush()
    return task


async def existing_card_of_graph(session: AsyncSession, graph_id: str) -> Task | None:
    """The technical card of the graph if a dry run made it, else ``None`` (nothing is made by asking)."""
    return await session.scalar(
        select(Task).where(Task.technical.is_(True), Task.pipeline_id == graph_id)
    )
