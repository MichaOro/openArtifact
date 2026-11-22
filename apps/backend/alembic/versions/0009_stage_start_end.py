"""One start and one end port per stage.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-21

A stage had separate ports for the outside (``in``/``out``) and for its actions
(``entry``/``exit``). Now the stage's ``start`` is both what the trigger or a previous stage feeds
and what feeds the first action; its ``end`` is both what the actions feed and what leads on.
Which side an edge is on follows from its other end, so the old edges map one to one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = "(SELECT id FROM workflow_nodes WHERE kind = 'stage')"


def _remap(column: str, mapping: dict[str, str]) -> None:
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
    node = "source_id" if column == "source_port" else "target_id"
    op.execute(
        sa.text(
            f"UPDATE workflow_edges SET {column} = CASE {column} {cases} ELSE {column} END "
            f"WHERE {node} IN {_STAGES}"
        )
    )


def upgrade() -> None:
    """Merge the inner and outer ports of stages."""

    _remap("source_port", {"entry": "start", "out": "end"})
    _remap("target_port", {"in": "start", "exit": "end"})


def downgrade() -> None:
    """Split them again: a source ``start`` leads inside, an ``end`` leads on; for targets the reverse."""

    _remap("source_port", {"start": "entry", "end": "out"})
    _remap("target_port", {"start": "in", "end": "exit"})
