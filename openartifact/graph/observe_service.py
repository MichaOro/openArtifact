"""Reading and deciding the observe mode of a pipeline, for the REST API, the integration API and the MCP server (ADR-088).

One place for what every door does: find the pipeline (by id, slug or name), set the draft, publish only the mode, release, observe again.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph import observe_state, publishing
from openartifact.graph.content import graph_of
from openartifact.graph.observe import of_content
from openartifact.graph.repository import GraphRepository, NodeError
from openartifact.graph.versions import current_version, fingerprint
from openartifact.models import Graph, GraphKind


class ObserveService:
    def __init__(self, session: SessionOpener, bus: EventBus) -> None:
        self._session = session
        self._bus = bus

    async def _find(self, session: AsyncSession, ref: str) -> Graph:
        """The pipeline named by id, slug or name (404 when there is none, 409 when a name fits several)."""
        rows = (
            (await session.execute(select(Graph).where(Graph.kind == GraphKind.PIPELINE)))
            .scalars()
            .all()
        )
        for field in ("id", "slug", "name"):
            found = [g for g in rows if getattr(g, field) == ref]
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                raise ArtifactError(409, f"More than one pipeline is called '{ref}': use its id")
        raise ArtifactError(404, "Pipeline not found")

    async def _read(self, session: AsyncSession, graph: Graph) -> dict[str, Any]:
        content = await graph_of(session, graph.id)
        published = await observe_state.published_setting(session, graph)
        return {
            "pipeline_id": graph.id,
            "pipeline_name": graph.name,
            "draft": content.get("observe"),
            "published": published,
            "draft_differs": of_content(content) != published,
            "state": observe_state.status_of(graph, published),
        }

    async def read(self, ref: str) -> dict[str, Any]:
        async with self._session() as session:
            return await self._read(session, await self._find(session, ref))

    async def set_draft(
        self, ref: str, setting: dict[str, Any], *, publish: bool = False, by: str = "api"
    ) -> dict[str, Any]:
        """Set the mode in the draft (422 for an invalid one). With ``publish`` the pipeline is published in the same call, but only when
        nothing else in the draft is unpublished: the call is the owner's consent to this one change, not to others."""
        async with self._session() as session:
            graph = await self._find(session, ref)
            try:
                await GraphRepository(session).set_observe(graph, setting)
            except NodeError as error:
                raise ArtifactError(422, str(error)) from error
            if publish:
                if not await self._only_the_mode_changed(session, graph):
                    raise ArtifactError(
                        409,
                        "The draft has other unpublished changes than the observe mode, so nothing was changed: set the mode "
                        "without publish and publish the pipeline in the editor, where its check shows every change",
                        "draft_has_other_changes",
                    )
                if await publishing.would_change(session, graph):
                    await publishing.publish(session, graph, "api")
                    self._bus.publish("graph.contract_changed", {"graph_id": graph.id})
            await session.commit()
            return await self._read(session, graph)

    @staticmethod
    async def _only_the_mode_changed(session: AsyncSession, graph: Graph) -> bool:
        """The draft equals the published version in everything but the observe mode (or nothing is published yet)."""
        version = await current_version(session, graph)
        if version is None:
            return True
        draft = await graph_of(session, graph.id)
        held = json.loads(version.content).get("observe")
        swapped = {k: v for k, v in draft.items() if k != "observe"}
        if held is not None:
            swapped["observe"] = held
        return fingerprint(swapped) == version.fingerprint

    async def release(self, ref: str, by: str) -> dict[str, Any]:
        async with self._session() as session:
            graph = await self._find(session, ref)
            await observe_state.release(session, graph, by)
            await session.commit()
            return await self._read(session, graph)

    async def again(self, ref: str, by: str, days: int | None, runs: int | None) -> dict[str, Any]:
        for name, value, top in (("days", days, 365), ("runs", runs, 100_000)):
            if value is not None and not 1 <= value <= top:
                raise ArtifactError(422, f"The limit in {name} is between 1 and {top}")
        async with self._session() as session:
            graph = await self._find(session, ref)
            await observe_state.observe_again(session, graph, by, days, runs)
            await session.commit()
            return await self._read(session, graph)
