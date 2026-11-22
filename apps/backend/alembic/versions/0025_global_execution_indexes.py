"""Indexes for the global execution list (``GET /api/executions``).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-22

The global list pages over all executions, newest first, by the keyset ``(started_at, id)``; a filter by
status is the common narrowing, and the summary counts ``running`` / ``failed`` / ``done`` since a time.

* ``ix_executions_started_at`` on ``(started_at, id)``: the default listing and its cursor read the index
  backwards and stop after one page, without sorting (``id`` is part of it because it breaks ties).
* ``ix_executions_status_started_at`` on ``(status, started_at, id)``: the same with a status filter, and
  the summary counts.

Filters by pipeline, origin and text are not indexed: a substring match cannot use an index and the table
is small (retention keeps it so). The downgrade drops the two indexes.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_executions_started_at", "executions", ["started_at", "id"])
    op.create_index("ix_executions_status_started_at", "executions", ["status", "started_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_executions_status_started_at", table_name="executions")
    op.drop_index("ix_executions_started_at", table_name="executions")
