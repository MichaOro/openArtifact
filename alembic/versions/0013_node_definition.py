"""An action in a workflow can be linked to an action definition.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21

``workflow_nodes.definition_id`` points at a ``workflows`` row of kind ``action``. An action without
it is an empty shell. Deleting the definition turns the action back into a shell.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_workflow_nodes_definition"


def upgrade() -> None:
    with op.batch_alter_table("workflow_nodes", recreate="always") as batch:
        batch.add_column(sa.Column("definition_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            FK_NAME, "workflows", ["definition_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_nodes", recreate="always") as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("definition_id")
