"""Publishing a pipeline or an action, and what an execution reads (ADR-070).

An execution reads every graph through :func:`graph_for_run`: the published version when the graph has one, else the draft (so a graph
that was never published runs as it always did).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.exceptions import ArtifactError
from openartifact.graph.content import graph_of
from openartifact.graph.repository import GraphRepository, SyncReport
from openartifact.graph.versions import current_version, fingerprint, get_version, next_number
from openartifact.models import Graph, GraphVersion


async def graph_for_run(session: AsyncSession, graph_id: str) -> dict[str, Any]:
    """The graph as an execution reads it: its published version, else its draft. The name is the current one."""
    graph = await session.get(Graph, graph_id)
    version = await current_version(session, graph) if graph else None
    if graph is None or version is None:
        return await graph_of(session, graph_id)
    content: dict[str, Any] = json.loads(version.content)
    content["name"], content["kind"] = graph.name, graph.kind
    return content


async def draft_changed(session: AsyncSession, graph: Graph) -> bool:
    """Whether the draft differs from the published version (``False`` while nothing is published)."""
    version = await current_version(session, graph)
    if version is None:
        return False
    return fingerprint(await graph_of(session, graph.id)) != version.fingerprint


async def would_change(session: AsyncSession, graph: Graph) -> bool:
    """Whether publishing now would make a new version (it would not when the draft equals the published one)."""
    version = await current_version(session, graph)
    return version is None or fingerprint(await graph_of(session, graph.id)) != version.fingerprint


async def publish(session: AsyncSession, graph: Graph, via: str) -> GraphVersion:
    """Publish the draft as a new version. 409 when it equals the published one (nothing would change)."""
    content = await graph_of(session, graph.id)
    digest = fingerprint(content)
    current = await current_version(session, graph)
    if current is not None and current.fingerprint == digest:
        raise ArtifactError(
            409, f"Nothing changed since version {current.number}: there is nothing new to publish"
        )
    version = GraphVersion(
        id=str(uuid.uuid4()),
        graph_id=graph.id,
        number=await next_number(session, graph.id),
        content=json.dumps(content, sort_keys=True, default=str),
        fingerprint=digest,
        source_number=None,
        published_via=via,
    )
    session.add(version)
    graph.published_number = version.number
    await session.flush()
    return version


async def republish(session: AsyncSession, graph: Graph, number: int, via: str) -> GraphVersion:
    """Publish an earlier version again (a rollback): a new version with that version's content; the history stays, the draft is not touched."""
    source = await get_version(session, graph.id, number)
    if source is None:
        raise ArtifactError(404, f"Version {number} does not exist")
    if graph.published_number == number:
        raise ArtifactError(409, f"Version {number} is the published one already")
    version = GraphVersion(
        id=str(uuid.uuid4()),
        graph_id=graph.id,
        number=await next_number(session, graph.id),
        content=source.content,
        fingerprint=source.fingerprint,
        source_number=number,
        published_via=via,
    )
    session.add(version)
    graph.published_number = version.number
    await session.flush()
    return version


async def discard_draft(session: AsyncSession, graph: Graph) -> SyncReport:
    """Throw the changes of the draft away: it becomes the published version again (ADR-070 addendum). 409 while nothing is published
    (there is no version to go back to) and when the draft equals the published version (nothing to discard)."""
    version = await current_version(session, graph)
    if version is None:
        raise ArtifactError(409, "Nothing is published yet: there is no version to go back to")
    if fingerprint(await graph_of(session, graph.id)) == version.fingerprint:
        raise ArtifactError(
            409, f"The draft equals version {version.number}: there is nothing to discard"
        )
    return await GraphRepository(session).restore(graph, json.loads(version.content))
