"""How a run is returned: by the API, the integration API, MCP and the ``run.updated`` event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from openartifact.models import RunNodeResult, RunStatus, StageStatus, StartedBy
from openartifact.schemas_common import UtcDateTime


class RunStageRead(BaseModel):
    """One stage of the run's (outermost) pipeline and how far the run has come with it."""

    id: str
    name: str
    status: StageStatus


#: Longest output a run read carries per result; ``GET /api/runs/{task_id}/results`` has it whole.
OUTPUT_PREVIEW_CHARS = 4096


class NodeResultRead(BaseModel):
    """One step of the run inside an action definition. Text only: never interpret ``output``.

    ``seq`` orders the steps; ``port`` is the connector left by (``pass``, ``fail``, ``out``; none for
    an output node). Where: ``pipeline_id``/``depth`` (0: the run's own pipeline), ``top_stage_id``,
    ``stage_id``, ``action_id`` and ``definition_id``. Exit code, output, reason and data are
    filled for Code and HTTP nodes.
    """

    id: str
    seq: int
    pipeline_id: str | None
    depth: int
    top_stage_id: str | None
    definition_id: str | None
    port: str | None
    node_id: str
    node_name: str
    stage_id: str | None
    action_id: str | None
    kind: str
    outcome: str
    exit_code: int | None
    output: str
    output_truncated: bool
    reason: str | None
    data: dict[str, Any] | None
    started_at: UtcDateTime
    finished_at: UtcDateTime

    @classmethod
    def of(cls, row: RunNodeResult, preview: bool = False) -> NodeResultRead:
        cut = preview and len(row.output) > OUTPUT_PREVIEW_CHARS
        return cls(
            id=row.id,
            seq=row.seq,
            pipeline_id=row.pipeline_id,
            depth=row.depth,
            top_stage_id=row.top_stage_id,
            definition_id=row.definition_id,
            port=row.port,
            node_id=row.node_id,
            node_name=row.node_name,
            stage_id=row.stage_id,
            action_id=row.action_id,
            kind=row.kind,
            outcome=row.outcome,
            exit_code=row.exit_code,
            output=row.output[:OUTPUT_PREVIEW_CHARS] if cut else row.output,
            output_truncated=cut,
            reason=row.reason,
            data=row.data,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


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
    #: The newest steps executed inside action definitions (at most 200, outputs cut to a preview);
    #: ``node_results_truncated`` says older ones were left out. The whole list: ``GET /api/runs/{task_id}/results``.
    node_results: list[NodeResultRead] = []
    node_results_truncated: bool = False
    updated_at: UtcDateTime
