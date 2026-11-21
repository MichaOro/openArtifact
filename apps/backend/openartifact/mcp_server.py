"""The MCP server: lets an AI agent work with the application (``/mcp``, Streamable HTTP).

The tools are a thin layer over :class:`~openartifact.tasks.service.ArtifactService`, the same
operations the REST API offers, with names instead of ids where an agent would use them: a pipeline,
stage or action may be given by name, an artifact by its number (``12`` or ``#12``). Creating and
starting an artifact are separate tools. A request needs the API token (``Authorization: Bearer``).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from openartifact.api.auth import token_error
from openartifact.models import TaskStatus
from openartifact.tasks.schemas import TaskCreate, TaskUpdate
from openartifact.tasks.service import ArtifactError, ArtifactService

INSTRUCTIONS = (
    "OpenArtifact is a Kanban board whose cards (artifacts) are processed by pipelines. "
    "Use list_pipelines to see the pipelines with their stages and actions, create_artifact to add a "
    "card (optionally with a parent and the pipeline it starts with), start_processing to run it "
    "through its pipeline and get_processing_status to follow it. Artifacts are addressed by number."
)


class McpError(ToolError):
    """A tool call that cannot be done; the message goes back to the agent (any other exception
    would reach it only as "Error executing tool")."""


def _named(items: list[dict[str, Any]], wanted: str, what: str) -> dict[str, Any]:
    """The item whose id or (case-insensitive) name is ``wanted``."""
    for item in items:
        if wanted in (item["id"], item.get("slug")) or item["name"].lower() == wanted.lower():
            return item
    names = ", ".join(i["name"] for i in items) or "none"
    raise McpError(f"Unknown {what} '{wanted}'. Available: {names}")


async def _target(
    service: ArtifactService, pipeline: str | None, stage: str | None, action: str | None
) -> tuple[str | None, str | None, str | None]:
    """Pipeline, stage and action given by name (or id) as ids; the defaults are the first ones."""
    if pipeline is None:
        if stage or action:
            raise McpError("A stage or an action needs a pipeline")
        return None, None, None
    chosen = _named(await service.pipelines(), pipeline, "pipeline")
    stage_item = _named(chosen["stages"], stage, "stage") if stage else None
    action_item = None
    if action:
        if stage_item is None:
            raise McpError("An action needs its stage")
        action_item = _named(stage_item["actions"], action, "action")
    return (
        chosen["id"],
        stage_item["id"] if stage_item else None,
        action_item["id"] if action_item else None,
    )


def build_mcp(service: ArtifactService) -> MCPServer:
    """The server with its tools (see the module docstring)."""
    mcp = MCPServer("OpenArtifact", instructions=INSTRUCTIONS)

    async def guarded[T](call: Awaitable[T]) -> T:
        try:
            return await call
        except ArtifactError as error:
            raise McpError(error.message) from error

    @mcp.tool()
    async def list_pipelines() -> list[dict[str, Any]]:
        """The pipelines with their stages in running order and the actions of every stage."""
        return await service.pipelines()

    @mcp.tool()
    async def list_artifacts(lane: str | None = None) -> list[dict[str, Any]]:
        """All artifacts (cards) in board order; ``lane`` (backlog, in_progress, done) filters."""
        artifacts = await service.list_all()
        return [a.model_dump(mode="json") for a in artifacts if lane is None or a.status == lane]

    @mcp.tool()
    async def get_artifact(artifact: str) -> dict[str, Any]:
        """One artifact by number (``12`` or ``#12``) or id."""
        return (await guarded(service.get(artifact))).model_dump(mode="json")

    @mcp.tool()
    async def create_artifact(
        title: str,
        body: str | None = None,
        lane: str = "backlog",
        parent: str | None = None,
        pipeline: str | None = None,
        stage: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        """Create an artifact (card). ``lane`` is backlog, in_progress or done; ``parent`` is the number of
        another artifact; ``pipeline`` (by name) is where it starts, with the first stage and its first
        action unless ``stage`` and ``action`` (by name) say otherwise. It is not started."""
        try:
            lane_value = TaskStatus(lane)
        except ValueError as error:
            raise McpError("lane must be backlog, in_progress or done") from error
        pipeline_id, stage_id, action_id = await _target(service, pipeline, stage, action)
        parent_id = (await guarded(service.get(parent))).id if parent else None
        data = TaskCreate(
            title=title,
            body=body,
            status=lane_value,
            parent_id=parent_id,
            pipeline_id=pipeline_id,
            stage_id=stage_id,
            action_id=action_id,
        )
        return (await guarded(service.create(data, created_by="mcp"))).model_dump(mode="json")

    @mcp.tool()
    async def update_artifact(
        artifact: str,
        title: str | None = None,
        body: str | None = None,
        lane: str | None = None,
    ) -> dict[str, Any]:
        """Change the title, body or lane of an artifact (not while it is being processed)."""
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if body is not None:
            fields["body"] = body
        if lane is not None:
            try:
                fields["status"] = TaskStatus(lane)
            except ValueError as error:
                raise McpError("lane must be backlog, in_progress or done") from error
        if not fields:
            raise McpError("Give a title, a body or a lane to change")
        return (await guarded(service.update(artifact, TaskUpdate(**fields)))).model_dump(
            mode="json"
        )

    @mcp.tool()
    async def start_processing(
        artifact: str,
        pipeline: str | None = None,
        stage: str | None = None,
        action: str | None = None,
    ) -> dict[str, Any]:
        """Start processing an artifact. Without a choice it starts with the pipeline, stage and action it has.
        Stages before the starting stage count as done."""
        pipeline_id, stage_id, action_id = await _target(service, pipeline, stage, action)
        return await guarded(
            service.start(artifact, pipeline_id, stage_id, action_id, started_by="system")
        )

    @mcp.tool()
    async def stop_processing(artifact: str) -> dict[str, Any]:
        """Stop processing an artifact; it keeps its stage and action."""
        return await guarded(service.stop(artifact))

    @mcp.tool()
    async def get_processing_status(artifact: str) -> dict[str, Any]:
        """How the processing of an artifact stands: status, where it is, the status of every stage."""
        run = await guarded(service.run(artifact))
        if run is None:
            return {"status": "never processed"}
        result: dict[str, Any] = json.loads(json.dumps(run, default=str))
        return result

    return mcp


class TokenProtected:
    """ASGI wrapper that lets a request through only with the API token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            header = dict(scope["headers"]).get(b"authorization")
            message = token_error(self.token, header.decode() if header else None)
            if message is not None:
                response = JSONResponse(
                    {"detail": message}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
