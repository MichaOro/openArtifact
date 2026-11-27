"""The names of the board tools, apart from the tools themselves (``api/board_tools.py``) so that a setting rule can check a name
without loading the services (ADR-079)."""

from __future__ import annotations

#: The tools that only read. The node offers them always.
READ_TOOLS = (
    "list_pipelines",
    "list_lanes",
    "list_artifact_fields",
    "list_artifacts",
    "count_artifacts",
    "search_artifacts",
    "get_artifact",
    "get_artifacts",
    "get_processing_status",
    "get_processing_results",
    "list_comments",
    "list_activity",
    "list_executions",
    "list_all_executions",
    "get_execution",
    "get_execution_flow",
    "get_execution_position",
    "get_graph_neighbours",
)
#: The tools that change something: the node holds them back while *Allow writes* is off.
WRITE_TOOLS = (
    "create_artifact",
    "update_artifact",
    "start_processing",
    "dry_run_graph",
    "stop_processing",
    "add_comment",
    "archive_artifact",
    "unarchive_artifact",
    "move_artifacts",
    "archive_artifacts",
    "set_parent",
    "set_fields",
    "add_comments",
)
BOARD_TOOLS = READ_TOOLS + WRITE_TOOLS
