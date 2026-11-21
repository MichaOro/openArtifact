"""Request and response models of the pipeline and action API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer

from openartifact.models import NodeKind

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


GraphKind = Literal["pipeline", "action"]
Seconds = Annotated[int, Field(ge=1, le=86400)]  # a timer: one second to one day


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphCreate(_Strict):
    """Body of ``POST /api/pipelines`` and ``POST /api/actions``."""

    name: Name


class GraphUpdate(_Strict):
    """Body of ``PATCH /api/pipelines/{id}`` (or ``/api/actions/{id}``)."""

    name: Name


class NodeCreate(_Strict):
    """Body of ``POST /api/pipelines/{id}/nodes``. Actions need ``stage_id`` and are placed relative to it."""

    kind: NodeKind
    name: Name | None = None
    x: float = 0.0
    y: float = 0.0
    stage_id: str | None = None
    seconds: Seconds | None = None


class NodeUpdate(_Strict):
    """Body of ``PATCH``: any of name, position, size (stages), fail_enabled (outputs), seconds (timers), definition_id (actions; ``null`` unlinks)."""

    name: Name | None = None
    x: float | None = None
    y: float | None = None
    width: Annotated[float, Field(gt=0)] | None = None
    height: Annotated[float, Field(gt=0)] | None = None
    fail_enabled: bool | None = None
    definition_id: str | None = None
    seconds: Seconds | None = None


EdgeStyle = Literal["curved", "straight", "elbow"]
Slot = Annotated[int, Field(ge=0, le=2)]


class EdgeCreate(_Strict):
    """Body of ``POST /api/pipelines/{id}/edges``. An existing edge on the same output is replaced."""

    source_id: str
    source_port: str
    target_id: str
    target_port: str
    style: EdgeStyle = "curved"
    source_slot: Slot = 0
    target_slot: Slot = 0


class EdgeUpdate(_Strict):
    """Body of ``PATCH /api/pipelines/{id}/edges/{edge_id}``."""

    style: EdgeStyle


class _Timestamps(BaseModel):
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _utc(self, value: datetime) -> str:
        """SQLite returns naive datetimes; they are always UTC."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat().replace("+00:00", "Z")


class GraphRead(_Timestamps):
    """A pipeline or action definition as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    kind: GraphKind
    slug: str


class NodeRead(BaseModel):
    """A node as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: NodeKind
    stage_id: str | None
    name: str
    x: float
    y: float
    width: float | None
    height: float | None
    fail_enabled: bool
    seconds: int | None
    definition_id: str | None
    definition_name: str | None = None
    definition_slug: str | None = None
    definition_fail_enabled: bool | None = None


class EdgeRead(BaseModel):
    """An edge as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    source_port: str
    target_id: str
    target_port: str
    style: str
    source_slot: int
    target_slot: int


class GraphDetail(BaseModel):
    """A pipeline or action definition with its nodes and edges (``GET /api/pipelines/{id}``)."""

    graph: GraphRead
    nodes: list[NodeRead]
    edges: list[EdgeRead]
