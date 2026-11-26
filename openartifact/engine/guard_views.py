"""The views a guard action reads the application's data through (ADR-068): a stable, documented interface, without the columns that
hold content or secrets. The SQLite node reads these and nothing else of the application's own database; a migration that changes
a table behind a view only has to keep the view working, and the views are made again at every start so they follow the tables.

======================  =========================================================================================================
View                    What it holds
======================  =========================================================================================================
``v_guard_runs``        One row per execution: its artifact, pipeline, status, who started it, step count, the times.
``v_guard_steps``       One row per step of an execution (a node that ran): node, kind, outcome, success, tries, port, reason, the times.
``v_guard_tool_calls``  One row per tool call of an Agent step: the tool, its node, the first 200 characters of the arguments,
                        whether it failed, its duration (only for finished steps).
``v_guard_artifacts``   One row per artifact (card): number, title, lane, parent, where it sits in a pipeline, the times.
``v_guard_lanes``       The lanes of the board in order.
======================  =========================================================================================================
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

VIEWS: dict[str, str] = {
    "v_guard_runs": (
        "SELECT id, task_id, number, pipeline_name, started_stage_name, started_action_name, final_stage_name, "
        "final_action_name, status, started_by, step_count, created_at, started_at, finished_at FROM executions"
    ),
    "v_guard_steps": (
        "SELECT id, execution_id, seq, node_id, node_name, kind, outcome, (outcome = 'pass') AS success, attempts, port, exit_code, reason, started_at, finished_at "
        "FROM run_node_results"
    ),
    "v_guard_tool_calls": (
        "SELECT n.execution_id AS execution_id, n.id AS step_id, n.node_name AS step_name, n.seq AS step_seq, "
        "t.key AS turn, json_extract(c.value, '$.tool') AS tool, json_extract(c.value, '$.node_name') AS tool_node, "
        "substr(json_extract(c.value, '$.arguments'), 1, 200) AS arguments, "
        "json_extract(c.value, '$.error') AS is_error, json_extract(c.value, '$.duration_ms') AS duration_ms "
        "FROM run_node_results n, json_each(n.detail, '$.turns') t, json_each(t.value, '$.tool_calls') c "
        "WHERE n.kind = 'agent'"
    ),
    "v_guard_artifacts": (
        "SELECT id, number, title, status AS lane, parent_id, pipeline_id, stage_id, action_id, created_by, created_at, "
        "updated_at FROM tasks"
    ),
    "v_guard_lanes": "SELECT key, title, position FROM lanes",
}


def install(path: Path) -> None:
    """Make the views again in the database at ``path`` (after the migrations; a view that cannot be made, because a table is not
    there yet, is left out)."""
    conn = sqlite3.connect(str(path))
    try:
        for name, select in VIEWS.items():
            conn.execute(f"DROP VIEW IF EXISTS {name}")
            try:
                conn.execute(f"CREATE VIEW {name} AS {select}")
            except sqlite3.OperationalError:
                continue
        conn.commit()
    finally:
        conn.close()
