"""Response models of the routes that used to return plain dicts (shapes unchanged).

Optional keys are left out when the code leaves them out: the routes use ``response_model_exclude_unset``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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
    max_length: int | None = None
    placeholder: str | None = None
    help: str | None = None
    group: str | None = None
    references: str | None = None


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


class DeletedCount(BaseModel):
    """``DELETE .../executions``: how many executions were deleted."""

    deleted: int
