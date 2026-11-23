"""Response models of the routes that used to return plain dicts (shapes unchanged).

Optional keys are left out when the code leaves them out: the routes use ``response_model_exclude_unset``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthRead(BaseModel):
    """``GET /health``."""

    status: str
    application: str
    version: str
    uptime_status: str


class InfoRead(BaseModel):
    """``GET /api/info``."""

    application: str
    version: str
    status: str
    environment: str


class PortRead(BaseModel):
    name: str
    label: str
    #: ``top`` / ``bottom`` for the attachment ports of tools (ADR-040); ``None``: the usual side.
    side: str | None = None
    #: When the port is there, for the editor: ``{"fn": name}`` or ``{"node": field}`` (``graph/manifest.py``).
    visible_when: dict[str, str] | None = None
    #: A function of the editor that labels the port from the node's settings.
    label_from: str | None = None


class SettingRead(BaseModel):
    """One setting of a node kind (the editor draws its field from this)."""

    key: str
    label: str
    type: str
    minimum: int | None
    maximum: int | None
    default: Any
    stored_in: str
    options: list[str] | None = None
    #: The shown text of options whose text is translated (the stored value is the option itself).
    option_labels: dict[str, str] | None = None
    max_length: int | None = None
    placeholder: str | None = None
    help: str | None = None
    group: str | None = None
    references: str | None = None
    #: Where it goes in the node's dialog, how prominent it is and what it inherits from (ADR-053).
    section: str = "definition"
    level: str = "core"
    inherits: str | None = None


class NodeTypeRead(BaseModel):
    """``GET /api/node-types``: one kind of node."""

    kind: str
    label: str
    scopes: list[str]
    fixed: bool
    addable: bool
    chain: bool
    ending: bool
    inputs: list[PortRead]
    outputs: list[PortRead]
    settings: list[SettingRead]
    links_to: str | None
    #: A tool node (ADR-040): attached to an Agent node's Tools port, not part of the flow.
    tool: bool = False
    #: How the kind connects and is drawn (``plain``, ``flow``, ``stage``, ``action``, ``pipeline``, ``output``, ``tool``, ``switch``).
    behaviour: str = "plain"
    #: Where the kind sits in the "+" menu: its cluster, the cluster's place and its own place in it.
    menu: dict[str, Any] | None = None
    #: How its card looks: icon, size, caption, ... (``graph/manifest.py`` ``UiSpec``).
    ui: dict[str, Any] = {}


class ChainActionRead(BaseModel):
    id: str
    name: str


class ChainEntryRead(BaseModel):
    """A step of a pipeline: a stage with its actions, or a call of another pipeline (``kind: pipeline``)."""

    id: str
    kind: str
    name: str
    first_action_id: str | None
    actions: list[ChainActionRead]
    pipeline_id: str | None = None


class PipelineChainRead(BaseModel):
    """``GET /api/v1/pipelines``: a pipeline with its stages in running order."""

    id: str
    name: str
    slug: str
    stages: list[ChainEntryRead]


class ExecutionsDelete(BaseModel):
    """``POST /api/executions/delete``: the executions to delete, by id (several artifacts at once)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=1, max_length=500)


class ExecutionsDeleted(BaseModel):
    """What a delete of several executions did: those deleted, and those refused because they are still running."""

    deleted: int
    skipped_running: int


class DeletedCount(BaseModel):
    """``DELETE .../executions``: how many executions were deleted."""

    deleted: int
