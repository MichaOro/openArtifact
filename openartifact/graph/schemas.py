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

#: At most this many tags on a definition, each this long.
MAX_TAGS, MAX_TAG_LENGTH, MAX_DESCRIPTION = 20, 32, 1000
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_DESCRIPTION)]


def _clean_tags(tags: list[str]) -> list[str]:
    """The tags trimmed and without empty ones or repeats (the first spelling stays; case does not make a tag a new one)."""
    clean: list[str] = []
    for tag in tags:
        text = " ".join(str(tag).split())
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            raise ValueError(f"a tag has at most {MAX_TAG_LENGTH} characters")
        if text.lower() not in (c.lower() for c in clean):
            clean.append(text)
    if len(clean) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return clean


Tags = Annotated[list[str], Field(max_length=100)]


class GraphCreate(_Strict):
    """Body of ``POST /api/pipelines`` and ``POST /api/actions``. ``purpose`` (actions only, ADR-067): ``pipeline`` (used by the
    stages of a pipeline, the default) or ``guard`` (used only by guards)."""

    name: Name
    purpose: Purpose = "pipeline"
    description: Description = ""
    tags: Tags = Field(default_factory=list)

    @model_validator(mode="after")
    def _tidy(self) -> GraphCreate:
        self.tags = _clean_tags(self.tags)
        return self


class GraphUpdate(_Strict):
    """Body of ``PATCH /api/pipelines/{id}`` (or ``/api/actions/{id}``): the new ``name`` and/or, for an action definition, its
    ``purpose``. A purpose cannot change while the definition is used on the other side (a stage or a guard) or holds a node of a
    kind that is not for the new purpose: the answer says where."""

    name: Name | None = None
    purpose: Purpose | None = None
    description: Description | None = None
    tags: Tags | None = None

    @model_validator(mode="after")
    def _something(self) -> GraphUpdate:
        if self.tags is not None:
            self.tags = _clean_tags(self.tags)
        if (
            self.name is None
            and self.purpose is None
            and self.description is None
            and self.tags is None
        ):
            raise ValueError("send a name, a purpose, a description or tags")
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
    #: What it is for, in a sentence or two, and the short labels to find it by (the management pages, ADR-069).
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    #: The version executions use (ADR-070; ``None``: nothing published, the draft runs) and whether the draft differs from it.
    published_version: int | None = Field(default=None, validation_alias="published_number")
    draft_changed: bool = False


class GraphVersionRead(BaseModel):
    """A published version. ``source_number``: the version it repeats (a rollback), else ``None``; ``current``: executions use it."""

    number: int
    published_at: UtcDateTime
    published_via: str
    source_number: int | None
    current: bool
    node_count: int = 0


class GraphVersionDetail(GraphVersionRead):
    """A published version with the frozen graph (``nodes`` and ``edges`` as the graph had them), for showing it read-only."""

    name: str = ""
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class GraphListRead(GraphRead):
    """A pipeline or action in the list: with the number of its nodes (the management pages draw it on the card)."""

    node_count: int = 0


class GraphUse(BaseModel):
    """One place a definition is used: ``kind`` says what the place is (``pipeline``, ``stage``, ``guard``, ``artifact``,
    ``execution``), ``name`` names it and ``href`` is where to go (empty when there is no page for it)."""

    kind: str
    name: str
    href: str = ""
    detail: str = ""


class GraphUses(BaseModel):
    """Where a pipeline or an action definition is used (the Usage tab of the management pages)."""

    uses: list[GraphUse]
    #: How many artifacts start in a pipeline and how many runs it has had (pipelines only; ``None`` for an action).
    artifacts: int | None = None
    executions: int | None = None


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


class PublishedGraph(BaseModel):
    """What publishing answers: the graph as it is now and the version that was made."""

    graph: GraphListRead
    version: GraphVersionRead


class GraphDetail(BaseModel):
    """A pipeline or action definition with its nodes and edges (``GET /api/pipelines/{id}``)."""

    graph: GraphRead
    nodes: list[NodeRead]
    edges: list[EdgeRead]
