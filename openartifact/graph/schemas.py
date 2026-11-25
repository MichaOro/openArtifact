"""Request and response models of the pipeline and action API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from openartifact.graph.node_types import TIMER_MAX_SECONDS, TIMER_MIN_SECONDS
from openartifact.models import GraphKind, NodeKind
from openartifact.schemas_common import UtcDateTime

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1e6, le=1e6)]
Extent = Annotated[float, Field(allow_inf_nan=False, gt=0, le=1e6)]  # width or height
Seconds = Annotated[int, Field(ge=TIMER_MIN_SECONDS, le=TIMER_MAX_SECONDS)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Purpose = Literal["pipeline", "guard"]


class GraphCreate(_Strict):
    """Body of ``POST /api/pipelines`` and ``POST /api/actions``. ``purpose`` (actions only, ADR-067): ``pipeline`` (used by the
    stages of a pipeline, the default) or ``guard`` (used only by guards)."""

    name: Name
    purpose: Purpose = "pipeline"


class GraphUpdate(_Strict):
    """Body of ``PATCH /api/pipelines/{id}`` (or ``/api/actions/{id}``): the new ``name`` and/or, for an action definition, its
    ``purpose``. A purpose cannot change while the definition is used on the other side (a stage or a guard) or holds a node of a
    kind that is not for the new purpose: the answer says where."""

    name: Name | None = None
    purpose: Purpose | None = None

    @model_validator(mode="after")
    def _something(self) -> GraphUpdate:
        if self.name is None and self.purpose is None:
            raise ValueError("send a name or a purpose")
        return self


class NodeCreate(_Strict):
    """Body of ``POST /api/pipelines/{id}/nodes``. Actions need ``stage_id`` and are placed relative to it."""

    kind: NodeKind
    name: Name | None = None
    x: Coordinate = 0.0
    y: Coordinate = 0.0
    stage_id: str | None = None
    seconds: Seconds | None = None
    config: dict[str, Any] | None = None


class NodeUpdate(_Strict):
    """Body of ``PATCH``: any of name, position, size (stages), fail_enabled (outputs), seconds (timers),
    definition_id (what an action or a pipeline node links to; ``null`` unlinks), config (the settings
    of Code and HTTP nodes, merged per key; ``null`` as a value resets a key)."""

    name: Name | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    width: Extent | None = None
    height: Extent | None = None
    fail_enabled: bool | None = None
    definition_id: str | None = None
    seconds: Seconds | None = None
    config: dict[str, Any] | None = None


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
    #: What an action definition is for (``pipeline`` or ``guard``, ADR-067); every pipeline is ``pipeline``.
    purpose: Purpose = "pipeline"


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
    #: Settings of Code and HTTP nodes, defaults filled in (``{}`` for other kinds).
    config: dict[str, Any] = Field(default_factory=dict)
    definition_id: str | None
    definition_name: str | None = None
    definition_slug: str | None = None
    definition_fail_enabled: bool | None = None
    #: Hints about the node's ``${node...}`` / ``${var...}`` references (unknown or ambiguous node
    #: names, malformed references) on a node just created or changed; the node is saved anyway.
    warnings: list[str] = Field(default_factory=list)
    #: What a change of an error output did beyond this node (ADR-061 addendum): ``definition_on`` (the action
    #: definition got On Fail too), ``definition_stays_on`` (other uses still need it), ``disconnected`` (connections
    #: that went with a connector). Machine readable; the editor turns them into short messages. Only on a change.
    notices: list[dict[str, Any]] = Field(default_factory=list)
    #: Other nodes of this graph changed with it (the uses of one definition): reload the graph.
    reload: bool = False


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
