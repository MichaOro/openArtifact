"""Graphs and the pipeline vocabulary: ``workflows`` become ``graphs``.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-21

A pipeline and an action definition are both stored as a graph (nodes and connections), so the
tables are ``graphs``, ``graph_nodes`` and ``graph_edges``, the kind ``workflow`` is now
``pipeline``, and the pipeline a run started in is ``pipeline_runs.pipeline_id``. Only names and
the kind value change; rows and ids stay. Foreign keys of other tables (``tasks.pipeline_id``,
``graph_nodes.definition_id``) follow the rename. Stored run snapshots are not rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NODE_KINDS = "'trigger', 'stage', 'action', 'complete', 'output', 'timer', 'pipeline'"


def _rename(old: str, new: str, kind_from: str, kind_to: str) -> None:
    """Rename ``old`` (tables ``<old>s``, ``<old>_nodes``, ``<old>_edges``) to ``new``."""
    graphs_o, nodes_o, edges_o = f"{old}s", f"{old}_nodes", f"{old}_edges"
    graphs_n, nodes_n, edges_n = f"{new}s", f"{new}_nodes", f"{new}_edges"
    id_o, id_n = f"{old}_id", f"{new}_id"

    op.rename_table(graphs_o, graphs_n)
    op.rename_table(nodes_o, nodes_n)
    op.rename_table(edges_o, edges_n)

    op.drop_index(f"ux_{graphs_o}_kind_slug", table_name=graphs_n)
    with op.batch_alter_table(graphs_n, recreate="always") as batch:
        batch.drop_constraint(f"ck_{graphs_o}_kind", type_="check")
        batch.alter_column("kind", existing_type=sa.String(16), server_default=kind_to)
    op.execute(
        sa.text(f"UPDATE {graphs_n} SET kind = :to WHERE kind = :from").bindparams(
            to=kind_to, **{"from": kind_from}
        )
    )
    with op.batch_alter_table(graphs_n, recreate="always") as batch:
        batch.create_check_constraint(f"ck_{graphs_n}_kind", f"kind IN ('{kind_to}', 'action')")
    op.create_index(f"ux_{graphs_n}_kind_slug", graphs_n, ["kind", "slug"], unique=True)

    op.drop_index(f"ix_{nodes_o}_{id_o}", table_name=nodes_n)
    op.drop_index(f"ix_{nodes_o}_stage_id", table_name=nodes_n)
    with op.batch_alter_table(nodes_n, recreate="always") as batch:
        batch.drop_constraint(f"ck_{nodes_o}_kind", type_="check")
        batch.drop_constraint(f"fk_{nodes_o}_definition", type_="foreignkey")
        batch.alter_column(id_o, existing_type=sa.String(36), new_column_name=id_n)
        batch.create_check_constraint(f"ck_{nodes_n}_kind", f"kind IN ({NODE_KINDS})")
        batch.create_foreign_key(
            f"fk_{nodes_n}_definition", graphs_n, ["definition_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index(f"ix_{nodes_n}_{id_n}", nodes_n, [id_n])
    op.create_index(f"ix_{nodes_n}_stage_id", nodes_n, ["stage_id"])

    op.drop_index(f"ix_{edges_o}_{id_o}", table_name=edges_n)
    op.drop_index(f"ix_{edges_o}_target_id", table_name=edges_n)
    with op.batch_alter_table(edges_n, recreate="always") as batch:
        batch.drop_constraint(f"ux_{edges_o}_output", type_="unique")
        batch.drop_constraint(f"ck_{edges_o}_style", type_="check")
        batch.drop_constraint(f"ck_{edges_o}_slots", type_="check")
        batch.alter_column(id_o, existing_type=sa.String(36), new_column_name=id_n)
        batch.create_unique_constraint(f"ux_{edges_n}_output", ["source_id", "source_port"])
        batch.create_check_constraint(
            f"ck_{edges_n}_style", "style IN ('curved', 'straight', 'elbow')"
        )
        batch.create_check_constraint(
            f"ck_{edges_n}_slots", "source_slot BETWEEN 0 AND 2 AND target_slot BETWEEN 0 AND 2"
        )
    op.create_index(f"ix_{edges_n}_{id_n}", edges_n, [id_n])
    op.create_index(f"ix_{edges_n}_target_id", edges_n, ["target_id"])


def _runs(old: str, new: str) -> None:
    with op.batch_alter_table("pipeline_runs", recreate="always") as batch:
        batch.alter_column(old, existing_type=sa.String(36), new_column_name=new)


def upgrade() -> None:
    _rename("workflow", "graph", "workflow", "pipeline")
    _runs("workflow_id", "pipeline_id")


def downgrade() -> None:
    _runs("pipeline_id", "workflow_id")
    _rename("graph", "workflow", "pipeline", "workflow")
