"""The output of an action definition has an On Pass and an On Fail input.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-21

The output node had one input, ``in``. It now has two: ``pass``, always, and ``fail``, when the
definition has On Fail switched on, so that the logic in between can route successful and failed
runs to separate connectors. Existing connections end at ``pass``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTPUTS = "(SELECT id FROM workflow_nodes WHERE kind = 'output')"


def upgrade() -> None:
    op.execute(
        f"UPDATE workflow_edges SET target_port = 'pass' "
        f"WHERE target_port = 'in' AND target_id IN {_OUTPUTS}"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE workflow_edges SET target_port = 'in' "
        f"WHERE target_port IN ('pass', 'fail') AND target_id IN {_OUTPUTS}"
    )
