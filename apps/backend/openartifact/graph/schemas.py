"""Request and response models of the pipeline and action API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from openartifact.graph.node_types import TIMER_MAX_SECONDS, TIMER_MIN_SECONDS
from openartifact.models import GraphKind, NodeKind
from openartifact.schemas_common import UtcDateTime

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]
Extent = Annotated[float, Field(allow_inf_nan=False, gt=0, le=1e6)]  # width or height
Seconds = Annotated[int, Field(ge=TIMER_MIN_SECONDS, le=TIMER_MAX_SECONDS)]


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
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    stage_id: str | None = None
    seconds: Seconds | None = None


class NodeUpdate(_Strict):
    """Body of ``PATCH``: any of name, position, size (stages), fail_enabled (outputs), seconds (timers),
    definition_id (what an action or a pipeline node links to; ``null`` unlinks)."""

    name: Name | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    width: Extent | None = None
    height: Extent | None = None
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
    created_at: UtcDateTime
    updated_at: UtcDateTime


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
