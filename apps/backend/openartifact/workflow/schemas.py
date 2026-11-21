"""Request and response models of the workflow API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer

from openartifact.models import NodeKind

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


WorkflowKind = Literal["workflow", "action"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowCreate(_Strict):
    """Body of ``POST /api/workflows`` (``kind`` ``action``: the definition of an action)."""

    name: Name
    kind: WorkflowKind = "workflow"


class WorkflowUpdate(_Strict):
    """Body of ``PATCH /api/workflows/{id}``."""

    name: Name


class NodeCreate(_Strict):
    """Body of ``POST /api/workflows/{id}/nodes``. Actions need ``stage_id`` and are placed relative to it."""

    kind: NodeKind
    name: Name | None = None
    x: float = 0.0
    y: float = 0.0
    stage_id: str | None = None


class NodeUpdate(_Strict):
    """Body of ``PATCH``: any of name, position, size (stages), fail_enabled (outputs)."""

    name: Name | None = None
    x: float | None = None
    y: float | None = None
    width: Annotated[float, Field(gt=0)] | None = None
    height: Annotated[float, Field(gt=0)] | None = None
    fail_enabled: bool | None = None


EdgeStyle = Literal["curved", "straight", "elbow"]
Slot = Annotated[int, Field(ge=0, le=2)]


class EdgeCreate(_Strict):
    """Body of ``POST /api/workflows/{id}/edges``. An existing edge on the same output is replaced."""

    source_id: str
    source_port: str
    target_id: str
    target_port: str
    style: EdgeStyle = "curved"
    source_slot: Slot = 0
    target_slot: Slot = 0


class EdgeUpdate(_Strict):
    """Body of ``PATCH /api/workflows/{id}/edges/{edge_id}``."""

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


class WorkflowRead(_Timestamps):
    """A workflow as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    kind: WorkflowKind


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


class WorkflowDetail(BaseModel):
    """A workflow with its whole graph (``GET /api/workflows/{id}``)."""

    workflow: WorkflowRead
    nodes: list[NodeRead]
    edges: list[EdgeRead]
