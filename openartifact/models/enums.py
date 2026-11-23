"""The value sets stored in string columns (kinds, statuses, origins)."""

from __future__ import annotations

import enum


class CreatedBy(enum.StrEnum):
    """How a task came to be (``tasks.created_by``)."""

    USER = "user"
    API = "api"
    MCP = "mcp"
    ACTION = "action"


class StartedBy(enum.StrEnum):
    """How a run was started (``pipeline_runs.started_by``, ``executions.started_by``); the business
    logic is the same for all of them, the history shows the way."""

    USER = "user"  # the browser
    API = "api"  # the REST integration API
    MCP = "mcp"  # the MCP server
    SYSTEM = "system"  # the application itself


class RunStatus(enum.StrEnum):
    """State of a run (``pipeline_runs.status``)."""

    RUNNING = "running"
    STOPPED = "stopped"
    DONE = "done"
    FAILED = "failed"


class StageStatus(enum.StrEnum):
    """State of one stage of a run (``run_stages.status``)."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class GraphKind(enum.StrEnum):
    """What a ``graphs`` row is: a pipeline, or the definition of what an action does."""

    PIPELINE = "pipeline"
    ACTION = "action"


class NodeKind(enum.StrEnum):
    """Kinds of nodes in a graph."""

    TRIGGER = "trigger"
    STAGE = "stage"
    ACTION = "action"
    COMPLETE = "complete"
    OUTPUT = "output"
    TIMER = "timer"
    PIPELINE = "pipeline"
    CODE = "code"
    HTTP = "http"
    IF = "if"
    SWITCH = "switch"
    AGENT = "agent"
    SET = "set"
    MCP_TOOL = "mcp_tool"
    HTTP_TOOL = "http_tool"
    CODE_TOOL = "code_tool"
    GITHUB = "github"
    POSTGRES = "postgres"
    POSTGRES_TOOL = "postgres_tool"
    ARTIFACT = "artifact"


class ProviderKind(enum.StrEnum):
    """What an ``llm_providers`` row is: the built-in OpenRouter, or an OpenAI-compatible endpoint."""

    OPENROUTER = "openrouter"
    OPENAI_COMPATIBLE = "openai_compatible"
