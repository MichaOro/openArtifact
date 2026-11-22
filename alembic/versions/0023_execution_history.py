"""Execution history: the ``executions`` table, per-execution results, the retention policy of a task.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-22

``pipeline_runs`` stays the current state of an artifact's processing. ``executions`` keeps one row per
start (restarts included). ``run_node_results`` gets ``execution_id`` (its steps now belong to an execution,
``seq`` counts per execution) and ``pipeline_runs.execution_id`` points to the current execution.
``tasks`` gets the retention policy (``history_keep_last``, ``history_keep_hours``) and ``execution_seq``,
the counter that numbers the executions of an artifact.

Every existing ``pipeline_runs`` row becomes execution number 1 with its results attached. What the old
row does not know stays empty: where it started (it knows only where it is), and the start time is the
run's ``created_at``. A run that was ``running`` stays so; ``recover()`` closes it at the next start.

The downgrade keeps, of each run, the results of its newest execution only (the old unique key
``run_id, seq`` cannot hold more), then drops the new columns and the table; the older executions are lost.
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_RESULTS = "fk_run_node_results_execution_id_executions"
FK_RUNS = "fk_pipeline_runs_execution_id_executions"


def _pipeline_name(snapshot: str) -> str:
    try:
        name = json.loads(snapshot).get("name", "")
    except (ValueError, AttributeError):
        return ""
    return name if isinstance(name, str) else ""


def _stage_and_action_names(
    snapshot: str, stage_id: str | None, action_id: str | None
) -> tuple[str | None, str | None]:
    try:
        document = json.loads(snapshot)
        graphs = [document, *document.get("pipelines", {}).values()]
        labels = {n["id"]: n.get("label") for g in graphs for n in g["nodes"]}
    except (ValueError, AttributeError, KeyError, TypeError):
        return None, None
    return labels.get(stage_id or ""), labels.get(action_id or "")


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("pipeline_id", sa.String(36), nullable=True),
        sa.Column("pipeline_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("started_stage_id", sa.String(36), nullable=True),
        sa.Column("started_stage_name", sa.String(255), nullable=True),
        sa.Column("started_action_id", sa.String(36), nullable=True),
        sa.Column("started_action_name", sa.String(255), nullable=True),
        sa.Column("final_stage_name", sa.String(255), nullable=True),
        sa.Column("final_action_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_by", sa.String(16), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ux_executions_task_number", "executions", ["task_id", "number"], unique=True)

    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.add_column(sa.Column("history_keep_last", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("history_keep_hours", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("execution_seq", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("pipeline_runs", recreate="always") as batch:
        batch.add_column(sa.Column("execution_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            FK_RUNS, "executions", ["execution_id"], ["id"], ondelete="SET NULL"
        )
    op.drop_index("ux_run_node_results_run_seq", table_name="run_node_results")
    with op.batch_alter_table("run_node_results", recreate="always") as batch:
        batch.add_column(sa.Column("execution_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            FK_RESULTS, "executions", ["execution_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index(
        "ux_run_node_results_execution_seq",
        "run_node_results",
        ["execution_id", "seq"],
        unique=True,
    )

    connection = op.get_bind()
    runs = connection.execute(
        sa.text(
            "SELECT id, task_id, pipeline_id, status, started_by, stage_id, action_id, note, "
            "snapshot, created_at, updated_at FROM pipeline_runs"
        )
    ).all()
    for run in runs:
        execution_id = str(uuid.uuid4())
        stage_name, action_name = _stage_and_action_names(run.snapshot, run.stage_id, run.action_id)
        steps = connection.execute(
            sa.text("SELECT count(*) FROM run_node_results WHERE run_id = :run"), {"run": run.id}
        ).scalar_one()
        connection.execute(
            sa.text(
                "INSERT INTO executions (id, task_id, number, pipeline_id, pipeline_name, "
                "final_stage_name, final_action_name, status, note, started_by, step_count, "
                "snapshot, created_at, started_at, finished_at) VALUES (:id, :task, 1, :pipeline, "
                ":pipeline_name, :stage, :action, :status, :note, :by, :steps, :snapshot, "
                ":created, :created, :finished)"
            ),
            {
                "id": execution_id,
                "task": run.task_id,
                "pipeline": run.pipeline_id,
                "pipeline_name": _pipeline_name(run.snapshot),
                "stage": stage_name,
                "action": action_name,
                "status": run.status,
                "note": run.note,
                "by": run.started_by,
                "steps": steps,
                "snapshot": run.snapshot,
                "created": run.created_at,
                "finished": None if run.status == "running" else run.updated_at,
            },
        )
        connection.execute(
            sa.text("UPDATE run_node_results SET execution_id = :e WHERE run_id = :r"),
            {"e": execution_id, "r": run.id},
        )
        connection.execute(
            sa.text("UPDATE pipeline_runs SET execution_id = :e WHERE id = :r"),
            {"e": execution_id, "r": run.id},
        )
        connection.execute(
            sa.text("UPDATE tasks SET execution_seq = 1 WHERE id = :t"), {"t": run.task_id}
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM run_node_results WHERE execution_id IS NOT NULL AND execution_id NOT IN ("
            "SELECT e.id FROM executions e WHERE e.number = "
            "(SELECT max(number) FROM executions WHERE task_id = e.task_id))"
        )
    )
    op.drop_index("ux_run_node_results_execution_seq", table_name="run_node_results")
    with op.batch_alter_table("run_node_results", recreate="always") as batch:
        batch.drop_constraint(FK_RESULTS, type_="foreignkey")
        batch.drop_column("execution_id")
    op.create_index(
        "ux_run_node_results_run_seq", "run_node_results", ["run_id", "seq"], unique=True
    )
    with op.batch_alter_table("pipeline_runs", recreate="always") as batch:
        batch.drop_constraint(FK_RUNS, type_="foreignkey")
        batch.drop_column("execution_id")
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_column("execution_seq")
        batch.drop_column("history_keep_hours")
        batch.drop_column("history_keep_last")
    op.drop_index("ux_executions_task_number", table_name="executions")
    op.drop_table("executions")
