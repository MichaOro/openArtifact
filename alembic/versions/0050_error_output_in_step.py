"""The error output of an action is one state of its definition and its uses (ADR-061 addendum).

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-24

A definition's Output has the switch *On Fail* (``graph_nodes.fail_enabled``), a use of the definition (an action node)
has *If the action fails* (``config.on_failure``). From now on the server keeps them in step; this brings the existing
data in step too:

* a use set to ``error_output`` whose definition has no *On Fail* switches it on (the use followed the error output, so
  the definition offers it); this comes first, so that its other uses are carried along by the next step;
* every use that stops the run on a failure (``fail`` or unset) of a definition with *On Fail* gets ``error_output``.
  Nothing changes in behaviour: an error output with nothing connected fails the run like *Stop the run*.

A use set to ``continue`` is left alone. Only ``config`` JSON and ``fail_enabled`` change: no table is rebuilt (see 0043).
The downgrade does nothing: both states are legal before this revision, and which one was brought in step is not known.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _config(raw: object) -> dict[str, object]:
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    return dict(raw) if isinstance(raw, dict) else {}


def upgrade() -> None:
    bind = op.get_bind()
    uses = [
        (use_id, definition_id, _config(raw))
        for use_id, definition_id, raw in bind.execute(
            sa.text(
                "SELECT id, definition_id, config FROM graph_nodes "
                "WHERE kind = 'action' AND definition_id IS NOT NULL"
            )
        ).fetchall()
    ]
    # (b) a use in the error output mode offers the definition's On Fail
    for definition_id in {
        d for _u, d, config in uses if config.get("on_failure") == "error_output"
    }:
        bind.execute(
            sa.text(
                "UPDATE graph_nodes SET fail_enabled = 1 WHERE graph_id = :g AND kind = 'output'"
            ),
            {"g": definition_id},
        )
    # (a) every use that stops the run follows a definition that has On Fail
    with_fail = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT DISTINCT graph_id FROM graph_nodes WHERE kind = 'output' AND fail_enabled = 1"
            )
        ).fetchall()
    }
    for use_id, definition_id, config in uses:
        if definition_id in with_fail and config.get("on_failure", "fail") == "fail":
            config["on_failure"] = "error_output"
            bind.execute(
                sa.text("UPDATE graph_nodes SET config = :config WHERE id = :id"),
                {"config": json.dumps(config), "id": use_id},
            )


def downgrade() -> None:
    """Nothing to undo: both states were legal before, and nothing says which one this revision brought in step."""
