"""How a run is returned: by the API, the integration API, MCP and the ``run.updated`` event."""

from __future__ import annotations

from pydantic import BaseModel

from openartifact.models import RunStatus, StageStatus, StartedBy
from openartifact.schemas_common import UtcDateTime


class RunStageRead(BaseModel):
    """One stage of the run's (outermost) pipeline and how far the run has come with it."""

    id: str
    name: str
    status: StageStatus


class RunRead(BaseModel):
    """The processing of an artifact: where it is, in ids and names, and the status of every stage."""

    id: str
    task_id: str
    root_pipeline_id: str | None
    root_pipeline_name: str
    #: Where the run is, following the flow into called pipelines.
    pipeline_id: str | None
    pipeline_name: str
    #: Where to start again: the entry of the run's own pipeline (the call, if it is inside one).
    resume_stage_id: str | None
    resume_action_id: str | None
    status: RunStatus
    started_by: StartedBy
    note: str | None
    stage_id: str | None
    stage_name: str | None
    action_id: str | None
    action_name: str | None
    stages: list[RunStageRead]
    updated_at: UtcDateTime
