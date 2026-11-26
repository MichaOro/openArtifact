"""The published versions of a pipeline or an action (ADR-070): reading them, and what tells a draft from a published version.

No reading of the draft here (``graph/content.py``) and no repository, so the repository may look at the published version too (the
purpose of an action, where it is used).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Graph, GraphVersion, NodeKind


def fingerprint(content: dict[str, Any]) -> str:
    """A hash of the parts of a graph that decide what runs: the nodes (kind, stage, name, what they link to, their settings, whether
    they have an error output) and the connections. Not the position, the size, the style of a line or the label of a node: moving
    a node does not make the draft a different one."""
    nodes = sorted(
        (
            {
                "id": n.get("id"),
                "kind": n.get("kind"),
                "stage_id": n.get("stage_id"),
                "name": n.get("name"),
                "definition_id": n.get("definition_id"),
                "seconds": n.get("seconds"),
                "config": n.get("config"),
                "fail_enabled": n.get("fail_enabled"),
            }
            for n in content.get("nodes", [])
        ),
        key=lambda n: str(n["id"]),
    )
    edges = sorted(
        (
            {
                "source_id": e.get("source_id"),
                "source_port": e.get("source_port"),
                "target_id": e.get("target_id"),
                "target_port": e.get("target_port"),
            }
            for e in content.get("edges", [])
        ),
        key=lambda e: json.dumps(e, sort_keys=True),
    )
    text = json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


async def versions_of(session: AsyncSession, graph_id: str) -> Sequence[GraphVersion]:
    """Every published version of a graph, newest first."""
    rows = await session.scalars(
        select(GraphVersion)
        .where(GraphVersion.graph_id == graph_id)
        .order_by(GraphVersion.number.desc())
    )
    return rows.all()


async def get_version(session: AsyncSession, graph_id: str, number: int) -> GraphVersion | None:
    return await session.scalar(
        select(GraphVersion).where(GraphVersion.graph_id == graph_id, GraphVersion.number == number)
    )


async def current_version(session: AsyncSession, graph: Graph) -> GraphVersion | None:
    """The version executions use, or ``None`` (nothing published: the draft runs)."""
    if graph.published_number is None:
        return None
    return await get_version(session, graph.id, graph.published_number)


async def next_number(session: AsyncSession, graph_id: str) -> int:
    last = await session.scalar(
        select(GraphVersion.number)
        .where(GraphVersion.graph_id == graph_id)
        .order_by(GraphVersion.number.desc())
        .limit(1)
    )
    return (last or 0) + 1


async def published_node_kinds(session: AsyncSession, graph: Graph) -> set[str]:
    """The kinds of nodes the published version holds (empty when nothing is published)."""
    version = await current_version(session, graph)
    if version is None:
        return set()
    return {str(n.get("kind")) for n in json.loads(version.content).get("nodes", [])}


async def published_users(
    session: AsyncSession, kind: NodeKind, target_id: str
) -> list[tuple[Graph, int]]:
    """The graphs whose published version has a node of ``kind`` that links to ``target_id`` (a pipeline whose published version still
    uses an action), with the number of that version."""
    users: list[tuple[Graph, int]] = []
    rows = await session.execute(
        select(Graph, GraphVersion)
        .join(
            GraphVersion,
            (GraphVersion.graph_id == Graph.id) & (GraphVersion.number == Graph.published_number),
        )
        .order_by(Graph.name)
    )
    for graph, version in rows.all():
        nodes = json.loads(version.content).get("nodes", [])
        if any(n.get("kind") == kind.value and n.get("definition_id") == target_id for n in nodes):
            users.append((graph, version.number))
    return users
