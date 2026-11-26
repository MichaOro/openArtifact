"""Comments in the activity, and slimmer traces of deleted executions (ADR-058).

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-24

Every existing comment gets a ``comment`` entry at its creation time with its author (the entry holds the comment's id,
never its text). The traces of deleted executions written before this revision named the one who *started* the run and
carried pipeline, status and duration; they now say "someone deleted execution N": the actor becomes ``system`` /
``unknown`` and the data keeps only the number and when it ran (the deletion time was not recorded then; the row keeps
its old time). Plain INSERT and UPDATE only. The downgrade removes the ``comment`` and ``comment_deleted`` entries.
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _when(value: object) -> object:
    """The stored timestamp as a datetime (SQLite returns text for a raw query)."""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def upgrade() -> None:
    connection = op.get_bind()
    activity = sa.table(
        "task_activity",
        sa.column("id", sa.String),
        sa.column("task_id", sa.String),
        sa.column("kind", sa.String),
        sa.column("actor_kind", sa.String),
        sa.column("actor_name", sa.String),
        sa.column("execution_id", sa.String),
        sa.column("data", sa.Text),
        sa.column("created_at", sa.DateTime),
    )
    comments = connection.execute(
        sa.text(
            "SELECT id, task_id, author_kind, author, execution_id, created_at FROM task_comments"
        )
    ).all()
    op.bulk_insert(
        activity,
        [
            {
                "id": str(uuid.uuid4()),
                "task_id": row.task_id,
                "kind": "comment",
                "actor_kind": row.author_kind,
                "actor_name": row.author,
                "execution_id": row.execution_id,
                "data": json.dumps({"comment_id": row.id}),
                "created_at": _when(row.created_at),
            }
            for row in comments
        ],
    )
    connection.execute(
        sa.text(
            "UPDATE task_activity SET actor_kind = 'system', actor_name = 'unknown', "
            "data = json_object('number', json_extract(data, '$.number'), "
            "'started_at', json_extract(data, '$.started_at')) "
            "WHERE kind = 'run' AND json_extract(data, '$.status') IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM task_activity WHERE kind IN ('comment', 'comment_deleted')")
