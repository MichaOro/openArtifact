"""Every workflow has a complete node, connected to its trigger by default.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-21

Trigger and complete are part of every workflow and cannot be added or removed by hand. Workflows
created before have no complete yet: it is added to the right of everything else, and connected to
the trigger when the trigger is not connected to anything.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GAP = 96.0


def upgrade() -> None:
    conn = op.get_bind()
    workflows = conn.execute(
        sa.text(
            "SELECT id FROM workflows WHERE kind = 'workflow' AND id NOT IN "
            "(SELECT workflow_id FROM workflow_nodes WHERE kind = 'complete')"
        )
    ).fetchall()
    for (workflow_id,) in workflows:
        right = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(x + COALESCE(width, 160)), 60) FROM workflow_nodes "
                "WHERE workflow_id = :w AND kind != 'action'"
            ),
            {"w": workflow_id},
        ).scalar_one()
        complete_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO workflow_nodes (id, workflow_id, kind, name, x, y) "
                "VALUES (:id, :w, 'complete', 'Complete', :x, 164)"
            ),
            {"id": complete_id, "w": workflow_id, "x": right + _GAP},
        )
        trigger = conn.execute(
            sa.text(
                "SELECT id FROM workflow_nodes WHERE workflow_id = :w AND kind = 'trigger' "
                "AND id NOT IN (SELECT source_id FROM workflow_edges WHERE source_port = 'out') "
                "LIMIT 1"
            ),
            {"w": workflow_id},
        ).scalar()
        if trigger:
            conn.execute(
                sa.text(
                    "INSERT INTO workflow_edges (id, workflow_id, source_id, source_port, "
                    "target_id, target_port) VALUES (:id, :w, :s, 'out', :t, 'in')"
                ),
                {"id": str(uuid.uuid4()), "w": workflow_id, "s": trigger, "t": complete_id},
            )


def downgrade() -> None:
    """Nothing to undo: a complete node is valid in every earlier schema."""
