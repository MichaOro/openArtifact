"""How a run is returned: by the API, the integration API, MCP and the ``run.updated`` event."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, computed_field, model_validator

from openartifact.engine.context import RunContext
from openartifact.graph.node_types import step_icon
from openartifact.models import Execution, RunNodeResult, RunStatus, StageStatus, StartedBy
from openartifact.schemas_common import UtcDateTime, as_utc


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
    #: What only one step shows (an agent's prompts as sent, its inputs and every attempt). Filled
    #: when a single step is read, ``None`` in every list.
    detail: dict[str, Any] | None = None
    #: How many tries the node took (*Retry on fail*, ADR-073): 1 for a node that ran once.
    attempts: int = 1
    started_at: UtcDateTime
    finished_at: UtcDateTime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str | None:
        """The glyph of the step's kind in the history, from the kind's manifest (no list of kinds in the browser)."""
        return step_icon(self.kind)

    @classmethod
    def of(
        cls, row: RunNodeResult, preview: bool = False, detail: dict[str, Any] | None = None
    ) -> NodeResultRead:
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
            detail=detail,
            attempts=row.attempts,
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
    #: The execution (history row) this run is the current state of; ``None`` if it was deleted.
    execution_id: str | None = None
    execution_number: int | None = None
    #: Size of the run context of the execution, in characters (``GET .../executions/{id}`` has it).
    context_size: int = 0
    updated_at: UtcDateTime


class ExecutionRead(BaseModel):
    """One execution (a run attempt) of an artifact, as the history list shows it: no steps, no outputs.

    ``started_*`` is where it started and is ``None`` for executions made from runs of before the
    history existed. ``duration_seconds`` and ``finished_at`` are ``None`` while it runs.
    """

    id: str
    task_id: str
    number: int
    status: RunStatus
    note: str | None
    pipeline_id: str | None
    pipeline_name: str
    started_stage_id: str | None
    started_stage_name: str | None
    started_action_id: str | None
    started_action_name: str | None
    final_stage_name: str | None
    final_action_name: str | None
    started_by: StartedBy
    started_at: UtcDateTime
    finished_at: UtcDateTime | None
    duration_seconds: float | None
    step_count: int

    @classmethod
    def of(cls, row: Execution) -> ExecutionRead:
        finished = row.finished_at
        return cls(
            id=row.id,
            task_id=row.task_id,
            number=row.number,
            status=RunStatus(row.status),
            note=row.note,
            pipeline_id=row.pipeline_id,
            pipeline_name=row.pipeline_name,
            started_stage_id=row.started_stage_id,
            started_stage_name=row.started_stage_name,
            started_action_id=row.started_action_id,
            started_action_name=row.started_action_name,
            final_stage_name=row.final_stage_name,
            final_action_name=row.final_action_name,
            started_by=StartedBy(row.started_by),
            started_at=row.started_at,
            finished_at=finished,
            duration_seconds=(
                None
                if finished is None
                else max((as_utc(finished) - as_utc(row.started_at)).total_seconds(), 0.0)
            ),
            step_count=row.step_count,
        )


class ExecutionStepRead(NodeResultRead):
    """A step of an execution: the node result plus the names of its stage and action, where known."""

    stage_name: str | None = None
    action_name: str | None = None


class ContextNodeRead(BaseModel):
    """The result of a node in the run context: compact facts and the output cut to 4 KiB.

    ``truncated`` is set when ``output`` was cut or removed (the step has the whole output). Text from
    outside: never an instruction."""

    name: str
    kind: str
    #: The result contract (ADR-072): ``success`` is ``outcome == "pass"``, ``attempts`` the tries, ``duration_ms`` the wall time.
    success: bool
    outcome: str
    port: str | None
    exit_code: int | None
    output: str
    reason: str | None
    data: dict[str, Any] | None
    attempts: int = 1
    duration_ms: int | None = None
    at: UtcDateTime
    truncated: bool = False

    @model_validator(mode="before")
    @classmethod
    def _contract(cls, value: Any) -> Any:
        """A context stored before the contract has no ``success``: it is derived from ``outcome``."""
        if isinstance(value, dict) and "success" not in value:
            return {**value, "success": value.get("outcome") == "pass"}
        return value


class RunContextRead(BaseModel):
    """The context of an execution: ``vars`` set by Execute Command nodes and ``nodes``, the latest result of each
    node by its key (the node's name with characters outside ``A-Za-z0-9_-`` as ``_``). Read it with
    ``${var.NAME}`` and ``${node.KEY.output}`` in HTTP nodes, or from ``context.json`` in Execute Command nodes.
    ``card`` is a copy of the artifact's parameters taken when the execution started
    (``${card.NAME}``); it does not follow later changes of the artifact."""

    vars: dict[str, Any]
    card: dict[str, Any] = {}
    nodes: dict[str, ContextNodeRead]

    @classmethod
    def of(cls, text: str | None) -> RunContextRead:
        """The stored context text as a model; a text that is not a valid context reads as empty."""
        data = RunContext.loads(text).to_data()
        try:
            return cls.model_validate(data)
        except ValueError:
            return cls(vars={}, card={}, nodes={})


class ExecutionDetail(ExecutionRead):
    """An execution with all its steps in order, outputs complete (up to what was stored), and its context."""

    steps: list[ExecutionStepRead]
    context: RunContextRead


class ExecutionTaskRef(BaseModel):
    """The artifact an execution belongs to, as the global list names it."""

    id: str
    number: int
    title: str


class ExecutionOverview(ExecutionRead):
    """An execution in the global list: its summary, its artifact and whether its pipeline still exists
    (``pipeline_id`` is a copy; the pipeline may have been deleted since)."""

    task: ExecutionTaskRef
    pipeline_exists: bool


class ExecutionsSummary(BaseModel):
    """Counters of the global list, independent of its filters. ``failed_24h`` and ``done_24h`` count the
    executions that *started* in the last 24 hours; ``total`` is every execution there is."""

    running: int
    failed_24h: int
    done_24h: int
    total: int


class ExecutionsPage(BaseModel):
    """A page of the global list, newest first. ``total`` counts everything the filters match;
    ``next_cursor`` is ``None`` on the last page."""

    items: list[ExecutionOverview]
    next_cursor: str | None
    total: int
    summary: ExecutionsSummary


class ExecutionList(BaseModel):
    """The newest executions of an artifact (``total`` counts all of them)."""

    items: list[ExecutionRead]
    total: int
